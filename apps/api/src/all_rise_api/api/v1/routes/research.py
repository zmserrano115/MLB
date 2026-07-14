from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any, Literal

from all_rise.application.research import ResearchService
from fastapi import APIRouter, Depends, Path, Query, Request, Response

from all_rise_api.api.v1.routes.operations import request_meta
from all_rise_api.api.v1.routes.slate import conditional_response
from all_rise_api.dependencies import get_research_service
from all_rise_api.errors import ApiError
from all_rise_api.schemas.common import ApiEnvelope, ErrorEnvelope, PaginationMeta
from all_rise_api.schemas.research import (
    BatterPitcherMatchupData,
    BattingSummaryData,
    PitchingSummaryData,
    PlayerData,
    PlayerGameLogData,
    PlayerProfileData,
)

router = APIRouter(prefix="/api/v1", tags=["research"])
ResearchServiceDependency = Annotated[ResearchService, Depends(get_research_service)]
READ_RESPONSES: dict[int | str, dict[str, Any]] = {
    304: {"description": "The persisted data version has not changed"},
    422: {"model": ErrorEnvelope},
    500: {"model": ErrorEnvelope},
}
ITEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorEnvelope},
    **READ_RESPONSES,
}


@router.get(
    "/players",
    response_model=ApiEnvelope[list[PlayerData]],
    responses=READ_RESPONSES,
)
def players(
    request: Request,
    response: Response,
    service: ResearchServiceDependency,
    query: str | None = Query(default=None, min_length=1, max_length=80),
    role: Literal["batter", "pitcher", "two-way"] | None = Query(default=None),
    season: int | None = Query(default=None, ge=1876, le=2200),
    limit: int = Query(default=30, ge=1, le=100),
    cursor: str | None = Query(default=None, min_length=1, max_length=20, pattern=r"^\d+$"),
) -> ApiEnvelope[list[PlayerData]] | Response:
    result = service.players(query=query, role=role, season=season, limit=limit, cursor=cursor)
    not_modified = conditional_response(request, response, result.data_version)
    if not_modified:
        return not_modified
    response.headers["x-cache-status"] = result.cache_outcome
    return ApiEnvelope(
        data=[PlayerData.model_validate(asdict(record)) for record in result.records],
        meta=request_meta(
            request,
            data_version=result.data_version,
            pagination=PaginationMeta(limit=limit, next_cursor=result.next_cursor),
        ).model_copy(update={"stale": result.stale}),
    )


@router.get(
    "/players/{player_id}",
    response_model=ApiEnvelope[PlayerProfileData],
    responses=ITEM_RESPONSES,
)
def player_profile(
    request: Request,
    response: Response,
    service: ResearchServiceDependency,
    player_id: str = Path(min_length=1, max_length=20, pattern=r"^\d+$"),
    season: int | None = Query(default=None, ge=1876, le=2200),
    group: Literal["batting", "pitching"] = Query(default="batting"),
    limit: int = Query(default=20, ge=1, le=100),
) -> ApiEnvelope[PlayerProfileData] | Response:
    result = service.player_profile(player_id, season=season, group=group, limit=limit)
    if not result.player:
        raise ApiError(404, "player_not_found", "The requested player was not found")
    not_modified = conditional_response(request, response, result.data_version)
    if not_modified:
        return not_modified
    response.headers["x-cache-status"] = result.cache_outcome
    return ApiEnvelope(
        data=PlayerProfileData(
            player=PlayerData.model_validate(asdict(result.player)),
            batting=(
                BattingSummaryData.model_validate(asdict(result.batting))
                if result.batting
                else None
            ),
            pitching=(
                PitchingSummaryData.model_validate(asdict(result.pitching))
                if result.pitching
                else None
            ),
            game_logs=[PlayerGameLogData.model_validate(asdict(log)) for log in result.game_logs],
            selected_group=group,
        ),
        meta=request_meta(request, data_version=result.data_version).model_copy(
            update={"stale": result.stale}
        ),
    )


@router.get(
    "/matchups/batter-vs-pitcher",
    response_model=ApiEnvelope[BatterPitcherMatchupData],
    responses=ITEM_RESPONSES,
)
def batter_pitcher_matchup(
    request: Request,
    response: Response,
    service: ResearchServiceDependency,
    batter_id: str = Query(min_length=1, max_length=20, pattern=r"^\d+$"),
    pitcher_id: str = Query(min_length=1, max_length=20, pattern=r"^\d+$"),
    season: int | None = Query(default=None, ge=1876, le=2200),
    limit: int = Query(default=20, ge=1, le=100),
) -> ApiEnvelope[BatterPitcherMatchupData] | Response:
    result = service.batter_pitcher_matchup(
        batter_id=batter_id,
        pitcher_id=pitcher_id,
        season=season,
        limit=limit,
    )
    if not result.matchup:
        raise ApiError(
            404,
            "matchup_not_found",
            "No persisted matchup history was found for those players",
        )
    not_modified = conditional_response(request, response, result.data_version)
    if not_modified:
        return not_modified
    response.headers["x-cache-status"] = result.cache_outcome
    payload = asdict(result.matchup)
    payload["game_logs"] = [asdict(log) for log in result.game_logs]
    return ApiEnvelope(
        data=BatterPitcherMatchupData.model_validate(payload),
        meta=request_meta(request, data_version=result.data_version).model_copy(
            update={"stale": result.stale}
        ),
    )

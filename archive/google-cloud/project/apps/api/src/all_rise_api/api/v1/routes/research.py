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
    AdvancedMatchupData,
    BatterPitcherMatchupData,
    BattingSummaryData,
    BullpenProjectionData,
    PitcherOpponentData,
    PitchingSummaryData,
    PlayerData,
    PlayerGameLogData,
    PlayerLeaderboardData,
    PlayerProfileData,
    StreakData,
    TeamLeaderboardData,
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


@router.get(
    "/research/batter-vs-pitcher",
    response_model=ApiEnvelope[AdvancedMatchupData],
    responses=READ_RESPONSES,
)
def advanced_batter_pitcher_matchup(
    request: Request,
    response: Response,
    service: ResearchServiceDependency,
    batter_id: str = Query(min_length=1, max_length=20, pattern=r"^\d+$"),
    pitcher_id: str = Query(min_length=1, max_length=20, pattern=r"^\d+$"),
    season: int | None = Query(default=None, ge=1876, le=2200),
    limit: int = Query(default=25, ge=1, le=100),
) -> ApiEnvelope[AdvancedMatchupData] | Response:
    result = service.advanced_matchup(
        batter_id=batter_id, pitcher_id=pitcher_id, season=season, limit=limit
    )
    not_modified = conditional_response(request, response, result.data_version)
    if not_modified:
        return not_modified
    response.headers["x-cache-status"] = result.cache_outcome
    return ApiEnvelope(
        data=AdvancedMatchupData.model_validate(result.data),
        meta=request_meta(request, data_version=result.data_version).model_copy(
            update={"stale": result.stale}
        ),
    )


@router.get(
    "/matchups/pitcher-vs-opponent",
    response_model=ApiEnvelope[PitcherOpponentData],
    responses=READ_RESPONSES,
)
def pitcher_opponent_matchup(
    request: Request,
    response: Response,
    service: ResearchServiceDependency,
    pitcher_id: str = Query(min_length=1, max_length=20, pattern=r"^\d+$"),
    team: str | None = Query(default=None, min_length=2, max_length=80),
    season: int | None = Query(default=None, ge=1876, le=2200),
    limit: int = Query(default=25, ge=1, le=100),
) -> ApiEnvelope[PitcherOpponentData] | Response:
    result = service.pitcher_opponent(pitcher_id=pitcher_id, team=team, season=season, limit=limit)
    not_modified = conditional_response(request, response, result.data_version)
    if not_modified:
        return not_modified
    response.headers["x-cache-status"] = result.cache_outcome
    return ApiEnvelope(
        data=PitcherOpponentData.model_validate(result.data),
        meta=request_meta(request, data_version=result.data_version).model_copy(
            update={"stale": result.stale}
        ),
    )


@router.get(
    "/matchups/bullpen",
    response_model=ApiEnvelope[list[BullpenProjectionData]],
    responses=READ_RESPONSES,
)
def bullpen_projection(
    request: Request,
    response: Response,
    service: ResearchServiceDependency,
    game_id: str = Query(min_length=3, max_length=80),
    team: str | None = Query(default=None, min_length=2, max_length=16),
    batter_id: str | None = Query(default=None, min_length=1, max_length=20, pattern=r"^\d+$"),
) -> ApiEnvelope[list[BullpenProjectionData]] | Response:
    result = service.bullpen_projection(game_id=game_id, team=team, batter_id=batter_id)
    not_modified = conditional_response(request, response, result.data_version)
    if not_modified:
        return not_modified
    response.headers["x-cache-status"] = result.cache_outcome
    rows = result.data if isinstance(result.data, list) else []
    return ApiEnvelope(
        data=[BullpenProjectionData.model_validate(row) for row in rows],
        meta=request_meta(request, data_version=result.data_version).model_copy(
            update={"stale": result.stale}
        ),
    )


@router.get(
    "/streaks",
    response_model=ApiEnvelope[list[StreakData]],
    responses=READ_RESPONSES,
)
def streaks(
    request: Request,
    response: Response,
    service: ResearchServiceDependency,
    through_date: str | None = Query(default=None, alias="date", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    group: Literal["batter", "pitcher", "team"] = Query(default="batter"),
    metric: str = Query(default="hit", min_length=2, max_length=48, pattern=r"^[a-z0-9_]+$"),
    limit: int = Query(default=25, ge=1, le=100),
) -> ApiEnvelope[list[StreakData]] | Response:
    result = service.streaks(through_date=through_date, group=group, metric=metric, limit=limit)
    not_modified = conditional_response(request, response, result.data_version)
    if not_modified:
        return not_modified
    response.headers["x-cache-status"] = result.cache_outcome
    rows = result.data if isinstance(result.data, list) else []
    return ApiEnvelope(
        data=[StreakData.model_validate(row) for row in rows],
        meta=request_meta(request, data_version=result.data_version).model_copy(
            update={"stale": result.stale}
        ),
    )


@router.get(
    "/stats/players",
    response_model=ApiEnvelope[list[PlayerLeaderboardData]],
    responses=READ_RESPONSES,
)
def player_leaderboard(
    request: Request,
    response: Response,
    service: ResearchServiceDependency,
    season: int | None = Query(default=None, ge=1876, le=2200),
    group: Literal["batting", "pitching"] = Query(default="batting"),
    sort: str = Query(default="home_runs", min_length=2, max_length=32, pattern=r"^[a-z_]+$"),
    query: str | None = Query(default=None, min_length=1, max_length=80),
    limit: int = Query(default=50, ge=1, le=100),
) -> ApiEnvelope[list[PlayerLeaderboardData]] | Response:
    result = service.player_leaderboard(
        season=season, group=group, sort=sort, query=query, limit=limit
    )
    not_modified = conditional_response(request, response, result.data_version)
    if not_modified:
        return not_modified
    response.headers["x-cache-status"] = result.cache_outcome
    rows = result.data if isinstance(result.data, list) else []
    return ApiEnvelope(
        data=[PlayerLeaderboardData.model_validate(row) for row in rows],
        meta=request_meta(request, data_version=result.data_version).model_copy(
            update={"stale": result.stale}
        ),
    )


@router.get(
    "/stats/teams",
    response_model=ApiEnvelope[list[TeamLeaderboardData]],
    responses=READ_RESPONSES,
)
def team_leaderboard(
    request: Request,
    response: Response,
    service: ResearchServiceDependency,
    season: int | None = Query(default=None, ge=1876, le=2200),
    group: Literal["batting", "pitching"] = Query(default="batting"),
    sort: str = Query(default="runs", min_length=2, max_length=32, pattern=r"^[a-z_]+$"),
    limit: int = Query(default=30, ge=1, le=100),
) -> ApiEnvelope[list[TeamLeaderboardData]] | Response:
    result = service.team_leaderboard(season=season, group=group, sort=sort, limit=limit)
    not_modified = conditional_response(request, response, result.data_version)
    if not_modified:
        return not_modified
    response.headers["x-cache-status"] = result.cache_outcome
    rows = result.data if isinstance(result.data, list) else []
    return ApiEnvelope(
        data=[TeamLeaderboardData.model_validate(row) for row in rows],
        meta=request_meta(request, data_version=result.data_version).model_copy(
            update={"stale": result.stale}
        ),
    )

from __future__ import annotations

from datetime import date
from hashlib import sha256
from typing import Annotated, Any

from all_rise.application.slate import SlateService
from all_rise.repositories.protocols import GameRecord, GameWeatherRecord
from fastapi import APIRouter, Depends, Path, Query, Request, Response

from all_rise_api.api.v1.routes.operations import request_meta
from all_rise_api.dependencies import get_slate_service
from all_rise_api.errors import ApiError
from all_rise_api.schemas.common import ApiEnvelope, ErrorEnvelope, PaginationMeta
from all_rise_api.schemas.slate import (
    GameData,
    PitcherBrief,
    TeamBrief,
    VenueBrief,
    WeatherData,
)

router = APIRouter(prefix="/api/v1", tags=["slate"])
SlateServiceDependency = Annotated[SlateService, Depends(get_slate_service)]
READ_RESPONSES: dict[int | str, dict[str, Any]] = {
    304: {"description": "The persisted data version has not changed"},
    422: {"model": ErrorEnvelope},
    500: {"model": ErrorEnvelope},
}
ITEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorEnvelope},
    **READ_RESPONSES,
}


@router.get("/games", response_model=ApiEnvelope[list[GameData]], responses=READ_RESPONSES)
def games(
    request: Request,
    response: Response,
    service: SlateServiceDependency,
    game_date: date = Query(alias="date"),
    team: str | None = Query(
        default=None, min_length=2, max_length=5, pattern=r"^[A-Za-z0-9]+$"
    ),
    status: str | None = Query(default=None, min_length=1, max_length=64),
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None, min_length=1, max_length=80),
) -> ApiEnvelope[list[GameData]] | Response:
    result = service.games(
        game_date=game_date.isoformat(),
        team=team,
        status=status,
        limit=limit,
        cursor=cursor,
    )
    not_modified = conditional_response(request, response, result.data_version)
    if not_modified:
        return not_modified
    response.headers["x-cache-status"] = result.cache_outcome
    return ApiEnvelope(
        data=[game_data(record) for record in result.records],
        meta=request_meta(
            request,
            data_version=result.data_version,
            pagination=PaginationMeta(limit=limit, next_cursor=result.next_cursor),
        ).model_copy(update={"stale": result.stale}),
    )


@router.get("/games/{game_id}", response_model=ApiEnvelope[GameData], responses=ITEM_RESPONSES)
def game(
    request: Request,
    response: Response,
    service: SlateServiceDependency,
    game_id: str = Path(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$"),
) -> ApiEnvelope[GameData] | Response:
    result = service.game(game_id)
    if not result.record:
        raise ApiError(404, "game_not_found", "The requested game was not found")
    not_modified = conditional_response(request, response, result.data_version)
    if not_modified:
        return not_modified
    response.headers["x-cache-status"] = result.cache_outcome
    return ApiEnvelope(
        data=game_data(result.record),
        meta=request_meta(request, data_version=result.data_version).model_copy(
            update={"stale": result.stale}
        ),
    )


@router.get("/weather", response_model=ApiEnvelope[list[WeatherData]], responses=READ_RESPONSES)
def weather(
    request: Request,
    response: Response,
    service: SlateServiceDependency,
    game_date: date = Query(alias="date"),
    game_id: str | None = Query(default=None, min_length=3, max_length=80),
    limit: int = Query(default=20, ge=1, le=100),
) -> ApiEnvelope[list[WeatherData]] | Response:
    result = service.weather(game_date=game_date.isoformat(), game_id=game_id, limit=limit)
    not_modified = conditional_response(request, response, result.data_version)
    if not_modified:
        return not_modified
    response.headers["x-cache-status"] = result.cache_outcome
    return ApiEnvelope(
        data=[weather_data(record) for record in result.records],
        meta=request_meta(
            request,
            data_version=result.data_version,
            pagination=PaginationMeta(limit=limit, next_cursor=None),
        ).model_copy(update={"stale": result.stale}),
    )


@router.get(
    "/games/{game_id}/weather",
    response_model=ApiEnvelope[WeatherData],
    responses=ITEM_RESPONSES,
)
def game_weather(
    request: Request,
    response: Response,
    service: SlateServiceDependency,
    game_id: str = Path(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$"),
) -> ApiEnvelope[WeatherData] | Response:
    result = service.game_weather(game_id)
    if not result.record:
        raise ApiError(404, "game_not_found", "The requested game was not found")
    not_modified = conditional_response(request, response, result.data_version)
    if not_modified:
        return not_modified
    response.headers["x-cache-status"] = result.cache_outcome
    return ApiEnvelope(
        data=weather_data(result.record),
        meta=request_meta(request, data_version=result.data_version).model_copy(
            update={"stale": result.stale or result.record.stale}
        ),
    )


def conditional_response(
    request: Request, response: Response, data_version: str
) -> Response | None:
    fingerprint = sha256(
        f"{request.url.path}?{request.url.query}:{data_version}".encode()
    ).hexdigest()
    etag = f'"{fingerprint}"'
    response.headers["etag"] = etag
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"etag": etag})
    return None


def game_data(record: GameRecord) -> GameData:
    return GameData(
        game_id=record.game_id,
        game_date=record.game_date,
        season=record.season,
        game_time_utc=record.game_time_utc,
        status=record.status,
        away_team=TeamBrief(
            name=record.away_team,
            abbreviation=record.away_team_abbreviation,
            score=record.away_score,
        ),
        home_team=TeamBrief(
            name=record.home_team,
            abbreviation=record.home_team_abbreviation,
            score=record.home_score,
        ),
        away_probable_pitcher=(
            PitcherBrief(
                player_id=record.away_probable_pitcher_id,
                name=record.away_probable_pitcher,
            )
            if record.away_probable_pitcher_id
            else None
        ),
        home_probable_pitcher=(
            PitcherBrief(
                player_id=record.home_probable_pitcher_id,
                name=record.home_probable_pitcher,
            )
            if record.home_probable_pitcher_id
            else None
        ),
        venue=(
            VenueBrief(
                name=record.venue_name,
                city=record.venue_city,
                roof_type=record.roof_type,
            )
            if record.venue_name
            else None
        ),
        source_updated_at=record.source_updated_at,
    )


def weather_data(record: GameWeatherRecord) -> WeatherData:
    return WeatherData(
        game_id=record.game_id,
        game_date=record.game_date,
        game_time_utc=record.game_time_utc,
        status=record.status,
        away_team=TeamBrief(
            name=record.away_team, abbreviation=record.away_team_abbreviation
        ),
        home_team=TeamBrief(
            name=record.home_team, abbreviation=record.home_team_abbreviation
        ),
        venue=(
            VenueBrief(name=record.venue_name, roof_type=record.roof_type)
            if record.venue_name
            else None
        ),
        available=record.observed_at is not None,
        observed_at=record.observed_at,
        forecast_for=record.forecast_for,
        source=record.source,
        condition=record.condition,
        temperature_f=record.temperature_f,
        feels_like_f=record.feels_like_f,
        humidity_percent=record.humidity_percent,
        wind_speed_mph=record.wind_speed_mph,
        wind_direction_degrees=record.wind_direction_degrees,
        wind_out_mph=record.wind_out_mph,
        precipitation_probability=record.precipitation_probability,
        hitter_adjustment=record.hitter_adjustment,
        pitcher_adjustment=record.pitcher_adjustment,
        edge_label=record.edge_label,
    )

from __future__ import annotations

from hashlib import sha256
from typing import Annotated, Any

from all_rise.application.live import LiveService
from fastapi import APIRouter, Depends, Path, Query, Request, Response

from all_rise_api.api.v1.routes.operations import request_meta
from all_rise_api.dependencies import get_live_service
from all_rise_api.errors import ApiError
from all_rise_api.schemas.common import ApiEnvelope, ErrorEnvelope
from all_rise_api.schemas.live import LiveGameData

router = APIRouter(prefix="/api/v1", tags=["live"])
LiveServiceDependency = Annotated[LiveService, Depends(get_live_service)]
RESPONSES: dict[int | str, dict[str, Any]] = {
    304: {"description": "The persisted live version has not changed"},
    404: {"model": ErrorEnvelope},
    422: {"model": ErrorEnvelope},
}


@router.get(
    "/games/{game_id}/live",
    response_model=ApiEnvelope[LiveGameData],
    responses=RESPONSES,
)
def live_game(
    request: Request,
    response: Response,
    service: LiveServiceDependency,
    game_id: str = Path(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$"),
    since: str | None = Query(default=None, min_length=1, max_length=128),
) -> ApiEnvelope[LiveGameData] | Response:
    result = service.snapshot(game_id)
    if result.record is None:
        raise ApiError(404, "live_snapshot_not_found", "No persisted live snapshot is available")
    fingerprint = sha256(f"{game_id}:{result.record.version}".encode()).hexdigest()
    etag = f'"{fingerprint}"'
    if since == result.record.version or request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"etag": etag})
    response.headers.update(
        {
            "etag": etag,
            "x-cache-status": result.cache_outcome,
            "x-live-age": str(result.age_seconds or 0),
        }
    )
    snapshot = dict(result.record.snapshot)
    snapshot["payload_size_bytes"] = result.record.payload_size_bytes
    return ApiEnvelope(
        data=LiveGameData.model_validate(snapshot),
        meta=request_meta(request, data_version=result.data_version).model_copy(
            update={"stale": result.stale}
        ),
    )

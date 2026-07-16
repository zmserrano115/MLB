from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Annotated, Any

from all_rise.application.operations import OperationsService
from all_rise.config import Settings
from fastapi import APIRouter, Depends, Query, Request, Response

from all_rise_api.dependencies import get_operations_service, get_settings
from all_rise_api.errors import ApiError
from all_rise_api.schemas.common import ApiEnvelope, ApiMeta, ErrorEnvelope, PaginationMeta
from all_rise_api.schemas.operations import (
    DataStatusData,
    HealthData,
    ReadinessData,
    VersionData,
)

router = APIRouter()
UNEXPECTED_ERROR_RESPONSE: dict[int | str, dict[str, Any]] = {500: {"model": ErrorEnvelope}}
VALIDATION_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    413: {"model": ErrorEnvelope},
    422: {"model": ErrorEnvelope},
    **UNEXPECTED_ERROR_RESPONSE,
}


def api_version() -> str:
    try:
        return version("all-rise-api")
    except PackageNotFoundError:
        return "0.1.0-dev"


OperationsServiceDependency = Annotated[OperationsService, Depends(get_operations_service)]
SettingsDependency = Annotated[Settings, Depends(get_settings)]


def request_meta(
    request: Request,
    *,
    data_version: str | None = None,
    pagination: PaginationMeta | None = None,
) -> ApiMeta:
    return ApiMeta(
        request_id=str(request.state.request_id),
        data_version=data_version,
        pagination=pagination,
    )


@router.get(
    "/health",
    response_model=ApiEnvelope[HealthData],
    responses=UNEXPECTED_ERROR_RESPONSE,
    tags=["operations"],
)
@router.get(
    "/healthz",
    response_model=ApiEnvelope[HealthData],
    tags=["operations"],
    include_in_schema=False,
)
def health(request: Request) -> ApiEnvelope[HealthData]:
    return ApiEnvelope(data=HealthData(), meta=request_meta(request))


@router.get(
    "/ready",
    response_model=ApiEnvelope[ReadinessData],
    responses={503: {"model": ErrorEnvelope}, **UNEXPECTED_ERROR_RESPONSE},
    tags=["operations"],
)
@router.get(
    "/readyz",
    response_model=ApiEnvelope[ReadinessData],
    tags=["operations"],
    include_in_schema=False,
)
def readiness(
    request: Request,
    service: OperationsServiceDependency,
    settings: SettingsDependency,
) -> ApiEnvelope[ReadinessData]:
    result = service.readiness()
    if not result.ready:
        raise ApiError(
            503,
            "not_ready",
            "The API is not ready to serve requests",
            details={
                "database_status": result.database_status,
                "cache_status": result.cache_status,
                "schema_revision": result.schema_revision,
            },
        )
    return ApiEnvelope(
        data=ReadinessData(
            status="ready",
            environment=settings.app_env,
            database_status=result.database_status,
            cache_status=result.cache_status,
            schema_revision=result.schema_revision,
        ),
        meta=request_meta(request, data_version=result.schema_revision),
    )


@router.get(
    "/version",
    response_model=ApiEnvelope[VersionData],
    responses=UNEXPECTED_ERROR_RESPONSE,
    tags=["operations"],
)
def build_version(
    request: Request,
    settings: SettingsDependency,
) -> ApiEnvelope[VersionData]:
    return ApiEnvelope(
        data=VersionData(
            api_version=api_version(),
            build_sha=settings.build_sha,
            schema_revision=settings.schema_revision,
        ),
        meta=request_meta(request, data_version=settings.schema_revision),
    )


@router.get(
    "/api/v1/data-status",
    response_model=ApiEnvelope[list[DataStatusData]],
    responses=VALIDATION_ERROR_RESPONSES,
    tags=["operations"],
)
def data_status(
    request: Request,
    response: Response,
    service: OperationsServiceDependency,
    limit: int = Query(default=20, ge=1, le=100),
) -> ApiEnvelope[list[DataStatusData]]:
    result = service.data_status_with_cache(limit=limit)
    response.headers["x-cache-status"] = result.cache_outcome
    return ApiEnvelope(
        data=[
            DataStatusData.model_validate(record, from_attributes=True) for record in result.records
        ],
        meta=request_meta(
            request,
            pagination=PaginationMeta(limit=limit, next_cursor=None),
        ),
    )

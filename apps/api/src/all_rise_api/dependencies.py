from __future__ import annotations

from typing import cast

from all_rise.application.operations import (
    OperationsService,
    build_operations_repository,
)
from all_rise.config import Settings
from fastapi import Request
from redis import Redis


class RedisCacheProbe:
    def __init__(self, redis_url: str) -> None:
        self._client: Redis = Redis.from_url(
            redis_url,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
            decode_responses=True,
        )

    def ping(self) -> bool:
        return bool(self._client.ping())

    def close(self) -> None:
        self._client.close()


def create_operations_service(settings: Settings) -> OperationsService:
    return OperationsService(
        build_operations_repository(settings),
        RedisCacheProbe(settings.redis_url),
        expected_schema_revision=settings.schema_revision,
    )


def get_operations_service(request: Request) -> OperationsService:
    return cast(OperationsService, request.app.state.operations_service)


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)

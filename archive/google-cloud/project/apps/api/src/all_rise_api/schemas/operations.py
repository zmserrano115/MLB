from __future__ import annotations

from typing import Literal

from all_rise_api.schemas.common import StrictModel


class HealthData(StrictModel):
    status: Literal["ok"] = "ok"
    service: Literal["api"] = "api"


class ReadinessData(StrictModel):
    status: Literal["ready", "not-ready"]
    environment: str
    database_status: str
    cache_status: str
    schema_revision: str | None


class VersionData(StrictModel):
    service: Literal["api"] = "api"
    api_version: str
    build_sha: str
    schema_revision: str


class DataStatusData(StrictModel):
    source: str
    watermark: str | None
    freshness_status: str
    last_success_at: str | None = None
    last_failure_at: str | None = None
    detail: str | None = None

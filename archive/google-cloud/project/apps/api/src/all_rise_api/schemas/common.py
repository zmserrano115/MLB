from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PaginationMeta(StrictModel):
    limit: int = Field(ge=1, le=100)
    next_cursor: str | None = None


class ApiMeta(StrictModel):
    request_id: str
    data_version: str | None = None
    source_time: datetime | None = None
    stale: bool = False
    pagination: PaginationMeta | None = None


class ApiEnvelope[DataT](StrictModel):
    data: DataT
    meta: ApiMeta


class ErrorBody(StrictModel):
    code: str
    message: str
    request_id: str
    details: dict[str, Any] | None = None


class ErrorEnvelope(StrictModel):
    error: ErrorBody

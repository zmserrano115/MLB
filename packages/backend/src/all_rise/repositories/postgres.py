"""PostgreSQL operational reads used by the FastAPI production shell."""

from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from all_rise.repositories.protocols import (
    DataSourceStatusRecord,
    RepositoryReadiness,
)


class PostgresOperationsRepository:
    def __init__(
        self,
        database_url: str,
        *,
        pool_size: int = 5,
        max_overflow: int = 5,
    ) -> None:
        self._engine: Engine = create_engine(
            database_url,
            pool_pre_ping=True,
            pool_size=pool_size,
            max_overflow=max_overflow,
        )

    def check_readiness(self) -> RepositoryReadiness:
        try:
            with self._engine.connect() as connection:
                connection.execute(text("SELECT 1"))
                revision = connection.execute(
                    text("SELECT version_num FROM alembic_version LIMIT 1")
                ).scalar_one_or_none()
            return RepositoryReadiness(True, str(revision) if revision else None)
        except Exception as exc:
            return RepositoryReadiness(False, None, type(exc).__name__)

    def get_data_status(self, *, limit: int) -> list[DataSourceStatusRecord]:
        if not inspect(self._engine).has_table("data_source_status"):
            return []
        statement = text(
            """
            SELECT source, watermark, freshness_status,
                   last_success_at, last_failure_at, detail
            FROM data_source_status
            ORDER BY source
            LIMIT :limit
            """
        )
        with self._engine.connect() as connection:
            rows = connection.execute(statement, {"limit": limit}).mappings()
            return [
                DataSourceStatusRecord(
                    source=str(row["source"]),
                    watermark=str(row["watermark"]) if row["watermark"] else None,
                    freshness_status=str(row["freshness_status"]),
                    last_success_at=(
                        str(row["last_success_at"]) if row["last_success_at"] else None
                    ),
                    last_failure_at=(
                        str(row["last_failure_at"]) if row["last_failure_at"] else None
                    ),
                    detail=str(row["detail"]) if row["detail"] else None,
                )
                for row in rows
            ]

    def get_data_version(self) -> str:
        if not inspect(self._engine).has_table("data_source_status"):
            return "empty"
        statement = text(
            """
            SELECT COALESCE(
                string_agg(source || ':' || COALESCE(watermark, ''), ',' ORDER BY source),
                'empty'
            )
            FROM data_source_status
            """
        )
        with self._engine.connect() as connection:
            return str(connection.execute(statement).scalar_one())

    def close(self) -> None:
        self._engine.dispose()

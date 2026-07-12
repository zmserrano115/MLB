"""Development-only, read-only adapter for the legacy SQLite database."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import unquote, urlparse

from all_rise.repositories.protocols import (
    DataSourceStatusRecord,
    RepositoryReadiness,
)


class SQLiteOperationsRepository:
    def __init__(self, database_url: str) -> None:
        parsed = urlparse(database_url)
        if parsed.scheme != "sqlite":
            raise ValueError("SQLite adapter requires a sqlite:// URL")
        raw_path = unquote(parsed.path)
        if raw_path.startswith("/") and len(raw_path) > 2 and raw_path[2] == ":":
            raw_path = raw_path[1:]
        self._path = Path(raw_path).resolve()

    def _connect(self) -> sqlite3.Connection:
        if not self._path.is_file():
            raise FileNotFoundError(self._path)
        connection = sqlite3.connect(f"file:{self._path.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    def check_readiness(self) -> RepositoryReadiness:
        try:
            with self._connect() as connection:
                revision = connection.execute("PRAGMA user_version").fetchone()[0]
                connection.execute("SELECT 1").fetchone()
            return RepositoryReadiness(True, f"sqlite-user-version-{revision}")
        except Exception as exc:
            return RepositoryReadiness(False, None, type(exc).__name__)

    def get_data_status(self, *, limit: int) -> list[DataSourceStatusRecord]:
        del limit
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='refresh_log'"
            ).fetchone()
            if not exists:
                return []
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(refresh_log)").fetchall()
            }
            timestamp_column = next(
                (
                    name
                    for name in (
                        "completed_at",
                        "finished_at",
                        "created_at",
                        "started_at",
                        "refresh_date",
                        "timestamp",
                    )
                    if name in columns
                ),
                None,
            )
            watermark = None
            if timestamp_column:
                watermark = connection.execute(
                    f'SELECT MAX("{timestamp_column}") FROM refresh_log'
                ).fetchone()[0]
        return [
            DataSourceStatusRecord(
                source="legacy-sqlite",
                watermark=str(watermark) if watermark else None,
                freshness_status="unknown",
                detail="Development-only compatibility adapter",
            )
        ]

    def close(self) -> None:
        return None

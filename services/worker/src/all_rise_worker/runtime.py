from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from all_rise.jobs.artifacts import ArtifactStore, GcsArtifactStore, LocalArtifactStore
from all_rise.jobs.executor import JobExecutor
from all_rise.jobs.postgres import PostgresJobStore

from all_rise_worker.adapters import build_adapters
from all_rise_worker.catalog import build_registry


def _positive_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


@lru_cache(maxsize=1)
def get_executor() -> JobExecutor:
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://all_rise:all_rise@localhost:5432/all_rise",
    )
    kind = os.getenv("ARTIFACT_STORE", "local").strip().lower()
    artifacts: ArtifactStore
    if kind == "gcs":
        artifacts = GcsArtifactStore.from_bucket_name(os.getenv("GCS_BUCKET", ""))
    elif kind == "local":
        artifacts = LocalArtifactStore(
            Path(os.getenv("ARTIFACT_LOCAL_ROOT", ".artifacts")).expanduser()
        )
    else:
        raise ValueError("ARTIFACT_STORE must be local or gcs")
    return JobExecutor(
        PostgresJobStore(database_url),
        artifacts,
        build_registry(build_adapters(database_url)),
        stale_after_seconds=_positive_int("JOB_STALE_AFTER_SECONDS", 300),
    )

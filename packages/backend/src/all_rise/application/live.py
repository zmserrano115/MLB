"""Persisted live-game delivery; this boundary never calls MLB providers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from all_rise.application.operations import CacheProbe
from all_rise.cache.versioned import versioned_key
from all_rise.repositories.protocols import LiveSnapshotRecord, SlateRepository


@dataclass(frozen=True, slots=True)
class LiveResult:
    record: LiveSnapshotRecord | None
    data_version: str
    cache_outcome: str
    stale: bool
    age_seconds: int | None


class LiveService:
    def __init__(
        self, repository: SlateRepository, cache: CacheProbe, *, ttl_seconds: int = 5
    ) -> None:
        self._repository = repository
        self._cache = cache
        self._ttl_seconds = ttl_seconds

    def snapshot(self, game_id: str) -> LiveResult:
        result = self._cache.get_or_load(
            versioned_key("live", [game_id], "current"),
            lambda: (
                asdict(record) if (record := self._repository.get_live_snapshot(game_id)) else None
            ),
            ttl_seconds=self._ttl_seconds,
            negative_ttl_seconds=5,
        )
        record = LiveSnapshotRecord(**result.value) if isinstance(result.value, dict) else None
        age = _age_seconds(record.observed_at) if record else None
        stale = result.stale or bool(
            record and not record.is_final and age is not None and age > 20
        )
        return LiveResult(
            record, record.version if record else "missing", result.outcome.value, stale, age
        )


def _age_seconds(value: str) -> int:
    observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    return max(0, int((datetime.now(UTC) - observed.astimezone(UTC)).total_seconds()))

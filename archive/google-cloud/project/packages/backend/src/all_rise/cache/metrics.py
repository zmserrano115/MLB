from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from threading import Lock
from typing import Protocol


class CacheMetrics(Protocol):
    def record(self, event: str) -> None: ...

    def observe_age(self, age_seconds: float) -> None: ...


@dataclass(slots=True)
class InMemoryCacheMetrics:
    """Process-local counters ready to be bridged to Cloud Monitoring later."""

    _events: Counter[str] = field(default_factory=Counter)
    _ages: list[float] = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock)

    def record(self, event: str) -> None:
        with self._lock:
            self._events[event] += 1

    def observe_age(self, age_seconds: float) -> None:
        with self._lock:
            self._ages.append(age_seconds)

    def snapshot(self) -> dict[str, int | float]:
        with self._lock:
            values: dict[str, int | float] = dict(self._events)
            values["age_observations"] = len(self._ages)
            values["max_age_seconds"] = max(self._ages, default=0.0)
            return values


class NullCacheMetrics:
    def record(self, event: str) -> None:
        del event

    def observe_age(self, age_seconds: float) -> None:
        del age_seconds

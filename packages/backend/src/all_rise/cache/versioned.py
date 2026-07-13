from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol
from uuid import uuid4

from all_rise.cache.metrics import CacheMetrics, NullCacheMetrics

SAFE_KEY_PART = re.compile(r"^[A-Za-z0-9_.:@-]{1,160}$")
SCHEMA_VERSION = 1
NEGATIVE_SENTINEL = object()


class RedisCommands(Protocol):
    def get(self, name: str) -> Any: ...

    def set(
        self,
        name: str,
        value: str,
        *,
        ex: int | None = None,
        px: int | None = None,
        nx: bool = False,
    ) -> Any: ...

    def eval(self, script: str, numkeys: int, *keys_and_args: str) -> Any: ...

    def ping(self) -> Any: ...

    def close(self) -> None: ...


class CacheOutcome(StrEnum):
    HIT = "hit"
    MISS = "miss"
    NEGATIVE_HIT = "negative_hit"
    DEGRADED = "degraded"
    SERIALIZATION_ERROR = "serialization_error"


@dataclass(frozen=True, slots=True)
class CacheLookup:
    outcome: CacheOutcome
    value: Any = None
    age_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class CacheLoadResult:
    value: Any
    outcome: CacheOutcome
    stale: bool = False


def versioned_key(namespace: str, parts: Sequence[str | int], version: str) -> str:
    all_parts = (namespace, *(str(part) for part in parts), f"v{version}")
    if not all(SAFE_KEY_PART.fullmatch(part) for part in all_parts):
        raise ValueError("Cache key parts contain unsupported characters")
    return ":".join(all_parts)


class VersionedJsonCache:
    def __init__(
        self,
        client: RedisCommands,
        *,
        metrics: CacheMetrics | None = None,
        lease_ttl_ms: int = 5_000,
        wait_attempts: int = 10,
        wait_interval_seconds: float = 0.02,
        clock: Callable[[], float] = time.time,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._metrics = metrics or NullCacheMetrics()
        self._lease_ttl_ms = lease_ttl_ms
        self._wait_attempts = wait_attempts
        self._wait_interval_seconds = wait_interval_seconds
        self._clock = clock
        self._sleeper = sleeper

    def ping(self) -> bool:
        return bool(self._client.ping())

    def get(self, key: str) -> CacheLookup:
        try:
            raw = self._client.get(key)
        except Exception:
            self._metrics.record("degraded_fallback")
            return CacheLookup(CacheOutcome.DEGRADED)
        if raw is None:
            self._metrics.record("miss")
            return CacheLookup(CacheOutcome.MISS)
        try:
            payload = json.loads(raw)
            if not isinstance(payload, Mapping) or payload.get("schema") != SCHEMA_VERSION:
                raise ValueError("Unsupported cache envelope")
            stored_at = float(payload["stored_at"])
            age = max(0.0, self._clock() - stored_at)
            self._metrics.observe_age(age)
            if payload.get("negative") is True:
                self._metrics.record("negative_hit")
                return CacheLookup(CacheOutcome.NEGATIVE_HIT, NEGATIVE_SENTINEL, age)
            self._metrics.record("hit")
            return CacheLookup(CacheOutcome.HIT, payload["data"], age)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            self._metrics.record("serialization_failure")
            return CacheLookup(CacheOutcome.SERIALIZATION_ERROR)

    def set(self, key: str, value: Any, *, ttl_seconds: int, negative: bool = False) -> bool:
        try:
            payload = json.dumps(
                {
                    "schema": SCHEMA_VERSION,
                    "stored_at": self._clock(),
                    "negative": negative,
                    "data": None if negative else value,
                },
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (TypeError, ValueError, OverflowError):
            self._metrics.record("serialization_failure")
            return False
        try:
            self._client.set(key, payload, ex=ttl_seconds)
            self._metrics.record("write")
            return True
        except Exception:
            self._metrics.record("degraded_fallback")
            return False

    def get_or_load(
        self,
        key: str,
        loader: Callable[[], Any],
        *,
        ttl_seconds: int,
        negative_ttl_seconds: int,
    ) -> CacheLoadResult:
        lookup = self.get(key)
        if lookup.outcome is CacheOutcome.HIT:
            return CacheLoadResult(lookup.value, lookup.outcome)
        if lookup.outcome is CacheOutcome.NEGATIVE_HIT:
            return CacheLoadResult(None, lookup.outcome)
        if lookup.outcome is CacheOutcome.DEGRADED:
            return CacheLoadResult(loader(), CacheOutcome.DEGRADED, stale=True)
        lease_key = f"{key}:lease"
        token = uuid4().hex
        try:
            acquired = bool(self._client.set(lease_key, token, nx=True, px=self._lease_ttl_ms))
        except Exception:
            self._metrics.record("degraded_fallback")
            return CacheLoadResult(loader(), CacheOutcome.DEGRADED, stale=True)
        if acquired:
            try:
                value = loader()
                self.set(
                    key,
                    value,
                    ttl_seconds=(negative_ttl_seconds if value is None else ttl_seconds),
                    negative=value is None,
                )
                return CacheLoadResult(value, lookup.outcome)
            finally:
                self._release_lease(lease_key, token)
        self._metrics.record("lock_wait")
        for _ in range(self._wait_attempts):
            self._sleeper(self._wait_interval_seconds)
            waited = self.get(key)
            if waited.outcome is CacheOutcome.HIT:
                return CacheLoadResult(waited.value, waited.outcome)
            if waited.outcome is CacheOutcome.NEGATIVE_HIT:
                return CacheLoadResult(None, waited.outcome)
            if waited.outcome is CacheOutcome.DEGRADED:
                break
        self._metrics.record("lock_wait_timeout")
        return CacheLoadResult(loader(), CacheOutcome.DEGRADED, stale=True)

    def _release_lease(self, lease_key: str, token: str) -> None:
        script = """
            if redis.call('get', KEYS[1]) == ARGV[1] then
                return redis.call('del', KEYS[1])
            end
            return 0
        """
        try:
            self._client.eval(script, 1, lease_key, token)
        except Exception:
            self._metrics.record("lease_release_failure")

    def close(self) -> None:
        self._client.close()


class PassThroughCache:
    def ping(self) -> bool:
        return False

    def get_or_load(
        self,
        key: str,
        loader: Callable[[], Any],
        *,
        ttl_seconds: int,
        negative_ttl_seconds: int,
    ) -> CacheLoadResult:
        del key, ttl_seconds, negative_ttl_seconds
        return CacheLoadResult(loader(), CacheOutcome.DEGRADED, stale=True)

    def close(self) -> None:
        return None

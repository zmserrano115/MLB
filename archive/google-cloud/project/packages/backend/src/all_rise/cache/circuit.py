from __future__ import annotations

import time
from collections.abc import Callable
from threading import Lock
from typing import Any


class RedisCircuitOpen(ConnectionError):
    """Raised immediately while the shared Redis outage circuit is open."""


class CircuitBreakingRedis:
    def __init__(
        self,
        client: Any,
        *,
        reset_seconds: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._reset_seconds = reset_seconds
        self._clock = clock
        self._open_until = 0.0
        self._lock = Lock()
        self._closed = False

    def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            if self._clock() < self._open_until:
                raise RedisCircuitOpen("Redis circuit is open")
        try:
            result = getattr(self._client, method)(*args, **kwargs)
        except Exception:
            with self._lock:
                self._open_until = self._clock() + self._reset_seconds
            raise
        with self._lock:
            self._open_until = 0.0
        return result

    def get(self, name: str) -> Any:
        return self._call("get", name)

    def set(self, name: str, value: str, **kwargs: Any) -> Any:
        return self._call("set", name, value, **kwargs)

    def eval(self, script: str, numkeys: int, *keys_and_args: str) -> Any:
        return self._call("eval", script, numkeys, *keys_and_args)

    def ping(self) -> Any:
        return self._call("ping")

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._client.close()

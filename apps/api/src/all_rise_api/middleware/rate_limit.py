from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    remaining: int | None = None
    retry_after_seconds: int | None = None


class RateLimiter(Protocol):
    def check(self, *, key: str, route: str) -> RateLimitDecision: ...


class AllowAllRateLimiter:
    """Phase 3 interface default; Redis enforcement is implemented in Phase 5."""

    def check(self, *, key: str, route: str) -> RateLimitDecision:
        del key, route
        return RateLimitDecision(allowed=True)

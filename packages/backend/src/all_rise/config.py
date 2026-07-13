from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse


class ConfigurationError(ValueError):
    """Raised when runtime configuration violates an environment boundary."""


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ConfigurationError(f"{name} must be positive")
    return value


def _positive_float(name: str, default: float) -> float:
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be numeric") from exc
    if value <= 0:
        raise ConfigurationError(f"{name} must be positive")
    return value


def _boolean(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    if raw not in {"true", "false"}:
        raise ConfigurationError(f"{name} must be true or false")
    return raw == "true"


@dataclass(frozen=True, slots=True)
class Settings:
    app_env: str
    log_level: str
    database_url: str
    redis_url: str
    cors_allowed_origins: tuple[str, ...]
    build_sha: str
    schema_revision: str
    max_body_bytes: int
    slow_request_ms: float
    db_pool_size: int
    db_max_overflow: int
    redis_cache_url: str = ""
    cache_enabled: bool = True
    cache_default_ttl_seconds: int = 30
    cache_negative_ttl_seconds: int = 5
    cache_lease_ttl_ms: int = 5_000
    redis_timeout_ms: int = 250
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 120
    rate_limit_window_seconds: int = 60

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def database_scheme(self) -> str:
        return urlparse(self.database_url).scheme.lower()

    @property
    def resolved_cache_url(self) -> str:
        return self.redis_cache_url or self.redis_url

    def validate(self) -> Settings:
        allowed_environments = {"development", "test", "staging", "production"}
        if self.app_env not in allowed_environments:
            raise ConfigurationError(f"APP_ENV must be one of {sorted(allowed_environments)}")
        if self.is_production and not self.database_scheme.startswith("postgresql"):
            raise ConfigurationError("Production DATABASE_URL must use PostgreSQL")
        if self.is_production and (
            not self.cors_allowed_origins or "*" in self.cors_allowed_origins
        ):
            raise ConfigurationError(
                "Production CORS_ALLOWED_ORIGINS must be an explicit allowlist"
            )
        return self

    @classmethod
    def from_env(cls) -> Settings:
        origins = tuple(
            origin.strip()
            for origin in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000").split(",")
            if origin.strip()
        )
        return cls(
            app_env=os.getenv("APP_ENV", "development").strip().lower(),
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
            database_url=os.getenv(
                "DATABASE_URL",
                "postgresql+psycopg://all_rise:all_rise@localhost:5432/all_rise",
            ).strip(),
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0").strip(),
            cors_allowed_origins=origins,
            build_sha=os.getenv("BUILD_SHA", "development").strip(),
            schema_revision=os.getenv("SCHEMA_REVISION", "0002_normalized_shadow_schema").strip(),
            max_body_bytes=_positive_int("MAX_REQUEST_BODY_BYTES", 1_048_576),
            slow_request_ms=_positive_float("SLOW_REQUEST_MS", 500.0),
            db_pool_size=_positive_int("DB_POOL_SIZE", 5),
            db_max_overflow=_positive_int("DB_MAX_OVERFLOW", 5),
            redis_cache_url=os.getenv(
                "REDIS_CACHE_URL", os.getenv("REDIS_URL", "redis://localhost:6379/0")
            ).strip(),
            cache_enabled=_boolean("CACHE_ENABLED", True),
            cache_default_ttl_seconds=_positive_int("CACHE_DEFAULT_TTL_SECONDS", 30),
            cache_negative_ttl_seconds=_positive_int("CACHE_NEGATIVE_TTL_SECONDS", 5),
            cache_lease_ttl_ms=_positive_int("CACHE_LEASE_TTL_MS", 5_000),
            redis_timeout_ms=_positive_int("REDIS_TIMEOUT_MS", 250),
            rate_limit_enabled=_boolean("RATE_LIMIT_ENABLED", True),
            rate_limit_requests=_positive_int("RATE_LIMIT_REQUESTS", 120),
            rate_limit_window_seconds=_positive_int("RATE_LIMIT_WINDOW_SECONDS", 60),
        ).validate()

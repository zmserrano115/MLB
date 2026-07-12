from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    app_env: str
    log_level: str
    database_url: str
    redis_url: str

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            app_env=os.getenv("APP_ENV", "development"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            database_url=os.getenv(
                "DATABASE_URL",
                "postgresql+psycopg://all_rise:all_rise@localhost:5432/all_rise",
            ),
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        )


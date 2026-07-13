"""Export the canonical FastAPI OpenAPI document for TypeScript generation."""

from __future__ import annotations

import json
from pathlib import Path

from all_rise.config import Settings
from all_rise_api.main import create_app

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "packages" / "shared-types" / "openapi.json"


def main() -> None:
    settings = Settings(
        app_env="test",
        log_level="WARNING",
        database_url="postgresql+psycopg://contract:contract@localhost/contract",
        redis_url="redis://localhost:6379/15",
        cors_allowed_origins=("http://localhost:3000",),
        build_sha="contract",
        schema_revision="0003_durable_job_execution",
        max_body_bytes=1_048_576,
        slow_request_ms=500,
        db_pool_size=1,
        db_max_overflow=1,
        cache_enabled=False,
        rate_limit_enabled=False,
    )
    document = create_app(settings).openapi()
    TARGET.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {TARGET.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

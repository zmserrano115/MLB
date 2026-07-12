from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version

from all_rise.config import Settings
from fastapi import FastAPI


def _version() -> str:
    try:
        return version("all-rise-api")
    except PackageNotFoundError:
        return "0.1.0-dev"


settings = Settings.from_env()
app = FastAPI(title="All Rise Analytics API", version=_version())


@app.get("/healthz", tags=["operations"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "api"}


@app.get("/readyz", tags=["operations"])
def readiness() -> dict[str, str]:
    return {"status": "ready", "environment": settings.app_env}


@app.get("/version", tags=["operations"])
def build_version() -> dict[str, str]:
    return {
        "service": "api",
        "version": _version(),
        "checked_at": datetime.now(UTC).isoformat(),
    }

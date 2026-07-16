from all_rise.config import Settings
from all_rise_api.main import create_app


def test_settings_have_safe_local_defaults(monkeypatch) -> None:
    for name in ("APP_ENV", "LOG_LEVEL", "DATABASE_URL", "REDIS_URL"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings.from_env()

    assert settings.app_env == "development"
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.redis_url.startswith("redis://")


def test_api_operations_shell() -> None:
    paths = create_app().openapi()["paths"]
    assert "/health" in paths
    assert "/ready" in paths
    assert "/version" in paths
    assert "/api/v1/data-status" in paths

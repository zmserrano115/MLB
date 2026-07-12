from all_rise.config import Settings
from all_rise_api.main import health, readiness


def test_settings_have_safe_local_defaults(monkeypatch) -> None:
    for name in ("APP_ENV", "LOG_LEVEL", "DATABASE_URL", "REDIS_URL"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings.from_env()

    assert settings.app_env == "development"
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.redis_url.startswith("redis://")


def test_api_operations_shell() -> None:
    assert health() == {"status": "ok", "service": "api"}
    assert readiness()["status"] == "ready"


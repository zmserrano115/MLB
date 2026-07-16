from pathlib import Path

import pytest
from all_rise.config import Settings
from all_rise.models.base import Base
from all_rise.models.core import (  # noqa: F401
    BatterPitchTypeSummary,
    BatterSeasonSummary,
    PitchEvent,
    PlateAppearanceSequence,
    StreakSummary,
    TeamSeasonSummary,
)


def test_phase7_read_models_are_registered_and_indexed() -> None:
    expected = {
        "pitch_events",
        "plate_appearance_sequences",
        "batter_pitch_type_summaries",
        "batter_season_summaries",
        "team_season_summaries",
        "streak_summaries",
    }
    assert expected <= set(Base.metadata.tables)
    assert any(
        index.name == "ix_pitch_events_matchup_date" for index in PitchEvent.__table__.indexes
    )
    assert any(index.name == "ix_streak_leaderboard" for index in StreakSummary.__table__.indexes)


def test_phase7_migration_bootstraps_summaries_from_authoritative_facts() -> None:
    source = Path("packages/backend/alembic/versions/0005_phase7_analytics.py").read_text(
        encoding="utf-8"
    )
    assert 'revision: str = "0005_phase7_analytics"' in source
    assert 'down_revision: str | None = "0004_slate_weather_read_models"' in source
    assert "FROM batter_pitcher_game_logs" in source
    assert "FROM pitcher_game_logs" in source
    assert "FROM games WHERE home_score IS NOT NULL" in source


def test_production_default_requires_phase7_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SCHEMA_REVISION", raising=False)
    settings = Settings.from_env()
    assert settings.schema_revision == "0006_phase8_live_game"

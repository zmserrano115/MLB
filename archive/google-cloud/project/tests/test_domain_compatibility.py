import ast
import json
from pathlib import Path

import pytest
from all_rise.domain import live as domain_live
from all_rise.domain import matchup_grading as domain_grading
from all_rise.domain import pitch_analysis as domain_pitch
from all_rise.domain import recent_form as domain_recent
from all_rise.domain import scoring as domain_scoring
from all_rise.domain import stats as domain_stats
from all_rise.domain import streaks as domain_streaks
from all_rise.domain import weather as domain_weather

from src import live_game, matchup_grading, pitch_analysis, recent_form, scoring, stat_data, weather

FIXTURE = Path(__file__).with_name("fixtures") / "domain_golden.json"


@pytest.fixture(scope="module")
def golden():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_legacy_modules_export_shared_domain_functions():
    assert matchup_grading.grade_hitter_matchup is domain_grading.grade_hitter_matchup
    assert pitch_analysis.calculate_batting_rates is domain_pitch.calculate_batting_rates
    assert scoring.parse_baseball_ip is domain_scoring.parse_baseball_ip
    assert recent_form.recent_game_values is domain_recent.recent_game_values
    assert stat_data.safe_divide is domain_stats.safe_divide
    assert weather.calculate_weather_adjustments is domain_weather.calculate_weather_adjustments
    assert live_game.parse_pitch_event is domain_live.parse_pitch_event
    assert live_game.calculate_live_streak is domain_streaks.calculate_live_streak


def test_golden_matchup_grades(golden):
    for case in golden["matchup_cases"]:
        assert (
            domain_grading.grade_hitter_matchup(case["at_bats"], case["average"]) == case["grade"]
        )


def test_golden_pitch_rates(golden):
    raw = golden["batting_input"]
    assert domain_pitch.calculate_batting_rates(raw) == golden["batting_rates"]
    assert domain_pitch.approximate_woba(raw) == pytest.approx(golden["approximate_woba"])


def test_golden_weather_and_live_parsing(golden):
    weather_case = golden["weather"]
    assert (
        list(
            domain_weather.calculate_weather_adjustments(
                weather_case["wind_out_mph"],
                weather_case["air_density"],
                weather_case["roof_type"],
            )
        )
        == weather_case["adjustments"]
    )
    assert (
        domain_weather.cardinal_direction(weather_case["direction_degrees"])
        == weather_case["cardinal"]
    )
    assert (
        domain_live.classify_play_result(golden["live_play"]["result"])
        == golden["live_play"]["classification"]
    )


def test_golden_baseball_innings(golden):
    case = golden["baseball_ip"]
    assert domain_scoring.parse_baseball_ip(case["input"]) == pytest.approx(case["innings"])


def test_domain_modules_do_not_import_ui_or_io_adapters():
    domain_dir = Path("packages/backend/src/all_rise/domain")
    banned_roots = {"alembic", "requests", "sqlalchemy", "src", "streamlit"}
    violations = []
    for path in domain_dir.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".", 1)[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots = {node.module.split(".", 1)[0]}
            else:
                continue
            if roots & banned_roots:
                violations.append((path.name, sorted(roots & banned_roots)))
    assert violations == []

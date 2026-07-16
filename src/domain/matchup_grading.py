"""Pure hitter-versus-pitcher matchup grading."""

import math
from typing import Any


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(number) else number


def grade_hitter_matchup(at_bats: Any, batting_average: Any) -> str:
    """Grade hitter history using only at-bats and hits-derived average."""
    at_bats = int(_number(at_bats))
    batting_average = _number(batting_average)

    if at_bats <= 0:
        return "No History"
    if batting_average < 0.200:
        return "Avoid"
    if (at_bats >= 8 and batting_average > 0.400) or (at_bats > 25 and batting_average >= 0.300):
        return "Strong Matchup"
    if at_bats < 8:
        return "Small Sample"
    if batting_average >= 0.300 or (at_bats > 25 and batting_average >= 0.250):
        return "Good Matchup"
    return "Neutral"

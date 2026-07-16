"""Player ranking calculations used by Streamlit views."""

from __future__ import annotations

import pandas as pd

MIN_RANKING_PA = 80
WOBA_SCALE = 1.15
WOBA_WEIGHTS = {
    "BB": 0.69,
    "HBP": 0.72,
    "1B": 0.88,
    "2B": 1.247,
    "3B": 1.578,
    "HR": 2.031,
}


def add_wrc_plus(frame: pd.DataFrame, min_pa: int = MIN_RANKING_PA) -> pd.DataFrame:
    """Add park-neutral wRC+ using the supplied player pool as the league baseline.

    Players below the established leaderboard sample floor retain a missing value,
    which keeps them below qualified players without inventing a ranking value.
    """
    result = pd.DataFrame(frame).copy()
    if result.empty:
        result["wRC+"] = pd.Series(dtype="Float64")
        return result

    def numbers(column: str) -> pd.Series:
        if column not in result.columns:
            return pd.Series(0.0, index=result.index)
        return pd.to_numeric(result[column], errors="coerce").fillna(0.0)

    pa = numbers("PA")
    ab = numbers("AB")
    hits = numbers("H")
    doubles = numbers("2B") if "2B" in result.columns else numbers("doubles")
    triples = numbers("3B") if "3B" in result.columns else numbers("triples")
    homers = numbers("HR")
    walks = numbers("BB")
    hbp = numbers("HBP")
    sacrifice_flies = numbers("SF")
    singles = (hits - doubles - triples - homers).clip(lower=0)
    denominator = ab + walks + hbp + sacrifice_flies
    numerator = (
        WOBA_WEIGHTS["BB"] * walks
        + WOBA_WEIGHTS["HBP"] * hbp
        + WOBA_WEIGHTS["1B"] * singles
        + WOBA_WEIGHTS["2B"] * doubles
        + WOBA_WEIGHTS["3B"] * triples
        + WOBA_WEIGHTS["HR"] * homers
    )
    league_denominator = float(denominator.sum())
    league_pa = float(pa.sum())
    league_runs = float(numbers("R").sum())
    if league_denominator <= 0 or league_pa <= 0 or league_runs <= 0:
        result["wRC+"] = pd.Series(pd.NA, index=result.index, dtype="Float64")
        return result

    woba = numerator.div(denominator.where(denominator > 0))
    league_woba = float(numerator.sum()) / league_denominator
    league_runs_per_pa = league_runs / league_pa
    runs_above_average_per_pa = (woba - league_woba) / WOBA_SCALE
    wrc_plus = (
        (runs_above_average_per_pa + league_runs_per_pa)
        / league_runs_per_pa
        * 100.0
    )
    qualified = pa.ge(int(min_pa)) & denominator.gt(0)
    result["wRC+"] = wrc_plus.where(qualified).round(0).astype("Float64")
    return result


def rank_hitters_by_wrc_plus(
    frame: pd.DataFrame,
    min_pa: int = MIN_RANKING_PA,
) -> pd.DataFrame:
    """Return deterministic wRC+ order with missing values after valid values."""
    ranked = add_wrc_plus(frame, min_pa=min_pa)
    if ranked.empty:
        return ranked
    if "Player" not in ranked.columns and "Name" in ranked.columns:
        ranked = ranked.rename(columns={"Name": "Player"})
    ranked["_wrc_missing"] = ranked["wRC+"].isna()
    ranked["_pa_sort"] = pd.to_numeric(ranked.get("PA"), errors="coerce").fillna(0)
    ranked = ranked.sort_values(
        ["_wrc_missing", "wRC+", "_pa_sort", "Player"],
        ascending=[True, False, False, True],
        na_position="last",
        kind="mergesort",
    )
    return ranked.drop(columns=["_wrc_missing", "_pa_sort"]).reset_index(drop=True)

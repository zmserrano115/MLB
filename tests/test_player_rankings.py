import pandas as pd

from src.player_rankings import add_wrc_plus, rank_hitters_by_wrc_plus


def hitter(name, pa, ab, hits, doubles, triples, home_runs, walks, hbp, sf, runs):
    return {
        "Name": name,
        "PA": pa,
        "AB": ab,
        "H": hits,
        "2B": doubles,
        "3B": triples,
        "HR": home_runs,
        "BB": walks,
        "HBP": hbp,
        "SF": sf,
        "R": runs,
    }


def test_wrc_plus_ranks_valid_samples_and_leaves_small_samples_missing():
    frame = pd.DataFrame(
        [
            hitter("Strong", 220, 190, 70, 15, 2, 18, 24, 3, 3, 50),
            hitter("Average", 240, 215, 55, 10, 1, 8, 20, 2, 3, 30),
            hitter("Tiny Sample", 12, 10, 8, 2, 0, 4, 2, 0, 0, 7),
        ]
    )
    ranked = rank_hitters_by_wrc_plus(frame)
    assert ranked["Player"].tolist() == ["Strong", "Average", "Tiny Sample"]
    assert ranked.loc[0, "wRC+"] > ranked.loc[1, "wRC+"]
    assert pd.isna(ranked.loc[2, "wRC+"])


def test_wrc_plus_is_missing_when_league_run_baseline_is_unavailable():
    result = add_wrc_plus(pd.DataFrame([hitter("No Runs", 100, 90, 30, 5, 1, 4, 8, 1, 1, 0)]))
    assert result["wRC+"].isna().all()

import pandas as pd

from src.stat_data import (
    get_batter_pitch_type_stats_batch,
    get_pitcher_pitch_type_stats_batch,
)


def clean_player_ids(player_ids):
    clean_ids = []
    for player_id in player_ids:
        numeric_id = pd.to_numeric(player_id, errors="coerce")
        if pd.notna(numeric_id):
            clean_ids.append(int(numeric_id))
    return tuple(dict.fromkeys(clean_ids))


def _group_frames(rows, key_column, requested_ids):
    grouped = {int(player_id): pd.DataFrame() for player_id in requested_ids}
    if not rows:
        return grouped

    frame = pd.DataFrame(rows)
    if frame.empty or key_column not in frame.columns:
        return grouped

    for player_id, group in frame.groupby(key_column, sort=False):
        numeric_id = pd.to_numeric(player_id, errors="coerce")
        if pd.isna(numeric_id):
            continue
        grouped[int(numeric_id)] = group.reset_index(drop=True)
    return grouped


def batch_pitcher_pitch_type_profiles(pitcher_ids, season):
    clean_ids = clean_player_ids(pitcher_ids)
    rows = get_pitcher_pitch_type_stats_batch(clean_ids, int(season))
    return _group_frames(rows, "pitcher_id", clean_ids)


def batch_batter_pitch_type_profiles(batter_ids, season, pitcher_hand):
    clean_ids = clean_player_ids(batter_ids)
    rows = get_batter_pitch_type_stats_batch(
        clean_ids,
        int(season),
        pitcher_hand=pitcher_hand,
    )
    grouped = _group_frames(rows, "batter_id", clean_ids)
    for batter_id, frame in list(grouped.items()):
        if frame.empty:
            continue
        if "AB" in frame.columns and "PITCH" in frame.columns:
            grouped[batter_id] = (
                frame.assign(_sort_ab=pd.to_numeric(frame["AB"], errors="coerce"))
                .sort_values(
                    ["_sort_ab", "PITCH"],
                    ascending=[False, True],
                    na_position="last",
                )
                .drop(columns="_sort_ab")
                .reset_index(drop=True)
            )
    return grouped

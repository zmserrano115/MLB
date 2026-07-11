"""Data orchestration for the Advanced HVP research page."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping

import pandas as pd

from src import database
from src.bullpen_projection import (
    build_projected_bullpen,
    composite_bullpen_matchup,
    matchup_projection_for_reliever,
)
from src.pitch_analysis import (
    calculate_pitch_type_summaries,
    direct_bvp_summary,
    normalize_pitch_code,
    ordered_pitch_sequence,
    pitch_name_for_code,
    plate_appearance_logs_from_pitches,
    safe_divide,
    safe_float,
    safe_int,
)


NO_HISTORY_GRADES = {"no history", "no pitcher id", "no data"}


def clean_player_id(value):
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return None
    return int(number)


def player_lookup(df):
    frame = pd.DataFrame(df)
    if frame.empty or "player_id" not in frame.columns:
        return {}
    rows = {}
    for _, row in frame.iterrows():
        player_id = clean_player_id(row.get("player_id"))
        if player_id is not None:
            rows[player_id] = row.to_dict()
    return rows


def player_search_options(df):
    frame = pd.DataFrame(df)
    if frame.empty or "player_id" not in frame.columns:
        return {}
    options = {}
    for _, row in frame.iterrows():
        player_id = clean_player_id(row.get("player_id"))
        name = row.get("Name") or row.get("Player")
        if player_id is None or not name:
            continue
        team = row.get("Team") or row.get("team_name") or ""
        label = f"{name} - {team} ({player_id})"
        options[label] = player_id
    return dict(sorted(options.items(), key=lambda item: item[0].casefold()))


def game_options(schedule_df):
    frame = pd.DataFrame(schedule_df)
    if frame.empty:
        return {}
    options = {}
    for _, row in frame.iterrows():
        game_pk = clean_player_id(row.get("game_pk"))
        if game_pk is None:
            continue
        label = row.get("game") or f"{row.get('away_team')} @ {row.get('home_team')}"
        status = row.get("game_status") or row.get("status") or ""
        options[f"{label} - {status} ({game_pk})"] = game_pk
    return options


def game_context(schedule_df, game_pk=None):
    frame = pd.DataFrame(schedule_df)
    if frame.empty:
        return {}
    if game_pk is not None and "game_pk" in frame.columns:
        matches = frame[pd.to_numeric(frame["game_pk"], errors="coerce").eq(int(game_pk))]
        if not matches.empty:
            return matches.iloc[0].to_dict()
    return {}


def opponent_context_for_batter(game_row: Mapping, batter_row: Mapping | None = None):
    if not game_row or not batter_row:
        return {}
    batter_team_id = clean_player_id(batter_row.get("team_id"))
    away_team_id = clean_player_id(game_row.get("away_team_id"))
    home_team_id = clean_player_id(game_row.get("home_team_id"))
    if batter_team_id == home_team_id:
        return {
            "opponent_team_id": away_team_id,
            "opponent_team": game_row.get("away_team"),
            "opponent_abbr": game_row.get("away_team_abbr") or game_row.get("away_abbr"),
            "probable_pitcher_id": clean_player_id(game_row.get("away_probable_pitcher_id")),
            "probable_pitcher": game_row.get("away_probable_pitcher"),
            "probable_pitcher_hand": game_row.get("away_pitcher_hand"),
            "batter_team_side": "home",
        }
    if batter_team_id == away_team_id:
        return {
            "opponent_team_id": home_team_id,
            "opponent_team": game_row.get("home_team"),
            "opponent_abbr": game_row.get("home_team_abbr") or game_row.get("home_abbr"),
            "probable_pitcher_id": clean_player_id(game_row.get("home_probable_pitcher_id")),
            "probable_pitcher": game_row.get("home_probable_pitcher"),
            "probable_pitcher_hand": game_row.get("home_pitcher_hand"),
            "batter_team_side": "away",
        }
    return {}


def team_record_from_game_context(game_row: Mapping, team_id):
    team_id = clean_player_id(team_id)
    if not game_row or team_id is None:
        return None
    for side in ("away", "home"):
        if clean_player_id(game_row.get(f"{side}_team_id")) == team_id:
            return (
                team_id,
                game_row.get(f"{side}_team"),
                game_row.get(f"{side}_team_abbr")
                or game_row.get(f"{side}_abbr")
                or game_row.get(f"{side}_team"),
            )
    return None


def direct_stats_for_pair(batter_id, pitcher_id):
    stats = database.get_batter_vs_pitcher_stats_from_db(batter_id, pitcher_id)
    if str(stats.get("matchup_grade", "")).strip().casefold() in NO_HISTORY_GRADES:
        return {**stats, "_has_direct_history": False}
    return {**stats, "_has_direct_history": True}


def _call_database_list(function_name, *args, **kwargs):
    loader = getattr(database, function_name, None)
    if loader is None:
        return []
    return loader(*args, **kwargs)


def specific_pitcher_research(batter_id, pitcher_id, season):
    batter_id = clean_player_id(batter_id)
    pitcher_id = clean_player_id(pitcher_id)
    if batter_id is None or pitcher_id is None:
        return {
            "summary": {},
            "game_logs": [],
            "pitch_events": [],
            "plate_appearances": [],
            "pitch_type_rows": [],
            "comparison_rows": [],
        }

    direct_stats = direct_stats_for_pair(batter_id, pitcher_id)
    game_logs = database.get_batter_vs_pitcher_game_logs_from_db(batter_id, pitcher_id)
    pitch_events = _call_database_list(
        "get_pitch_level_events_for_matchup",
        batter_id,
        pitcher_id,
    )
    stored_pa = _call_database_list(
        "get_plate_appearance_sequences_for_matchup",
        batter_id,
        pitcher_id,
    )
    if stored_pa:
        plate_appearances = stored_pa
    else:
        plate_appearances = plate_appearance_logs_from_pitches(pitch_events)
    direct_pitch_types = database.get_bvp_pitch_type_stats_from_db(
        batter_id,
        pitcher_id,
        season,
    )
    if not direct_pitch_types and pitch_events:
        direct_pitch_types = calculate_pitch_type_summaries(pitch_events)
    pitcher_pitch_mix = database.get_pitcher_pitch_type_stats_from_db(
        pitcher_id,
        season,
    )
    summary = direct_bvp_summary(direct_stats, game_logs)
    if not direct_stats.get("_has_direct_history"):
        summary["data_date_range"] = None
        summary["last_matchup_date"] = None
    return {
        "summary": summary,
        "game_logs": game_logs,
        "pitch_events": ordered_pitch_sequence(pitch_events),
        "plate_appearances": plate_appearances,
        "pitch_type_rows": direct_pitch_types,
        "comparison_rows": exact_pitch_comparison_rows(
            direct_pitch_types,
            pitcher_pitch_mix,
        ),
    }


def exact_pitch_comparison_rows(direct_pitch_types, pitcher_pitch_mix, batter_pitch_types=None):
    direct_by_code = {
        normalize_pitch_code(row.get("pitch_type") or row.get("pitch_code")): dict(row)
        for row in (direct_pitch_types or [])
    }
    pitcher_by_code = {
        normalize_pitch_code(row.get("pitch_code") or row.get("pitch_type")): dict(row)
        for row in (pitcher_pitch_mix or [])
    }
    batter_by_code = {
        normalize_pitch_code(row.get("pitch_code") or row.get("pitch_type")): dict(row)
        for row in (batter_pitch_types or [])
    }
    codes = sorted(set(direct_by_code) | set(pitcher_by_code) | set(batter_by_code))
    rows = []
    for code in codes:
        direct = direct_by_code.get(code, {})
        pitcher = pitcher_by_code.get(code, {})
        batter = batter_by_code.get(code, {})
        rows.append(
            {
                "Pitch": pitch_name_for_code(code),
                "Code": code,
                "Pitcher Usage": pitcher.get("PERCENTAGE") or direct.get("usage_pct"),
                "Pitcher Count": pitcher.get("COUNT") or direct.get("pitch_count"),
                "Avg Velo": pitcher.get("AVG SPEED") or direct.get("avg_velocity"),
                "Direct Count": direct.get("pitch_count"),
                "Whiff%": direct.get("whiff_pct"),
                "CSW%": direct.get("csw_pct"),
                "Contact%": direct.get("contact_pct"),
                "Hard-hit%": direct.get("hard_hit_pct"),
                "Barrel%": direct.get("barrel_pct"),
                "Direct AVG": direct.get("AVG"),
                "Direct SLG": direct.get("SLG"),
                "Direct wOBA": direct.get("wOBA"),
                "Direct xwOBA": direct.get("xwOBA"),
                "Batter Pitch AVG": batter.get("AVG"),
                "Batter Pitch SLG": batter.get("SLG"),
                "Batter Pitch K%": batter.get("K%"),
                "Sample": direct.get("sample_size"),
            }
        )
    return rows


def _pitch_type_projection_for_reliever(pitch_mix, batter_pitch_types):
    mix_rows = list(pitch_mix or [])
    batter_rows = {
        normalize_pitch_code(row.get("pitch_code") or row.get("pitch_type")): dict(row)
        for row in (batter_pitch_types or [])
    }
    if not mix_rows or not batter_rows:
        return {}
    weighted_slg = []
    weighted_k = []
    weighted_avg = []
    total_usage = 0.0
    total_pa = 0
    for row in mix_rows:
        code = normalize_pitch_code(row.get("pitch_code") or row.get("pitch_type"))
        batter = batter_rows.get(code)
        if not batter:
            continue
        usage = safe_float(row.get("PERCENTAGE")) or safe_float(row.get("percentage")) or 0.0
        if usage <= 0:
            usage = safe_float(row.get("COUNT")) or 0.0
        total_usage += usage
        total_pa += safe_int(batter.get("PA"))
        if safe_float(batter.get("SLG")) is not None:
            weighted_slg.append((safe_float(batter.get("SLG")), usage))
        if safe_float(batter.get("AVG")) is not None:
            weighted_avg.append((safe_float(batter.get("AVG")), usage))
        if safe_float(batter.get("K%")) is not None:
            weighted_k.append((safe_float(batter.get("K%")), usage))

    def weighted(values):
        if not values or total_usage <= 0:
            return None
        weight_sum = sum(weight for _, weight in values)
        if weight_sum <= 0:
            return None
        return sum(value * weight for value, weight in values) / weight_sum

    avg = weighted(weighted_avg)
    slg = weighted(weighted_slg)
    ops = None
    if avg is not None and slg is not None:
        ops = avg + slg
    woba = None
    if avg is not None and slg is not None:
        woba = (avg * 0.55) + (slg * 0.35)
    return {
        "PA": total_pa,
        "AVG": avg,
        "SLG": slg,
        "OPS": ops,
        "wOBA": woba,
        "K%": weighted(weighted_k),
    }


def _primary_pitches(pitch_mix, limit=3):
    rows = list(pitch_mix or [])
    if not rows:
        return ""
    rows.sort(
        key=lambda row: safe_float(row.get("PERCENTAGE") or row.get("percentage") or row.get("COUNT")) or 0,
        reverse=True,
    )
    labels = []
    for row in rows[:limit]:
        code = normalize_pitch_code(row.get("pitch_code") or row.get("pitch_type"))
        usage = safe_float(row.get("PERCENTAGE") or row.get("percentage"))
        if usage is None:
            labels.append(pitch_name_for_code(code))
        else:
            labels.append(f"{pitch_name_for_code(code)} {usage:.1f}%")
    return ", ".join(labels)


def projected_bullpen_research(
    batter_id,
    roster_df,
    pitcher_stats_df,
    season,
    game_date,
    game_pk=None,
    opponent_team_id=None,
    probable_starter_id=None,
    pitcher_hand=None,
    doubleheader=False,
    already_used_pitcher_ids=None,
):
    batter_id = clean_player_id(batter_id)
    roster = pd.DataFrame(roster_df)
    if batter_id is None or roster.empty:
        return {"relievers": [], "composite": composite_bullpen_matchup([])}

    pitcher_ids = [
        clean_player_id(value)
        for value in roster.get("player_id", pd.Series(dtype=float)).tolist()
    ]
    pitcher_ids = [value for value in pitcher_ids if value is not None]
    pitcher_logs = database.get_pitcher_game_logs_batch_from_db(
        pitcher_ids,
        season=season,
        through_date=game_date,
    )
    projected = build_projected_bullpen(
        roster,
        pitcher_stats_df,
        pitcher_logs_df=pitcher_logs,
        probable_starter_id=probable_starter_id,
        game_date=game_date,
        team_id=opponent_team_id,
        doubleheader=doubleheader,
        already_used_pitcher_ids=already_used_pitcher_ids,
        projection_timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    reliever_ids = [
        row["player_id"]
        for row in projected
        if row.get("player_id") is not None
    ]
    direct_batch = database.get_batter_vs_pitcher_stats_batch_from_db(
        [(batter_id, pitcher_id) for pitcher_id in reliever_ids]
    )
    pitcher_mix_rows = database.get_pitcher_pitch_type_stats_batch_from_db(
        reliever_ids,
        season,
    )
    pitch_mix_by_pitcher = {}
    for row in pitcher_mix_rows:
        pitch_mix_by_pitcher.setdefault(row.get("pitcher_id"), []).append(row)

    batter_pitch_types_by_hand = {}
    for hand in ("L", "R", pitcher_hand):
        if not hand:
            continue
        hand = str(hand).upper()[:1]
        if hand not in batter_pitch_types_by_hand:
            batter_pitch_types_by_hand[hand] = database.get_batter_pitch_type_stats_from_db(
                batter_id,
                season,
                hand,
            )

    enriched = []
    for row in projected:
        pitcher_id = row.get("player_id")
        direct_stats = direct_batch.get(
            (batter_id, pitcher_id),
            database.empty_bvp_result("No History"),
        )
        pitcher_mix = pitch_mix_by_pitcher.get(pitcher_id, [])
        hand = str(row.get("Throws") or pitcher_hand or "").upper()[:1]
        batter_pitch_types = batter_pitch_types_by_hand.get(hand, [])
        pitch_type_projection = _pitch_type_projection_for_reliever(
            pitcher_mix,
            batter_pitch_types,
        )
        matchup = matchup_projection_for_reliever(
            row,
            direct_stats=direct_stats,
            pitch_type_projection=pitch_type_projection,
            baseline={"wOBA": 0.315, "OPS": 0.720, "K%": 22.0, "BB%": 8.0},
        )
        enriched_row = {
            **row,
            **matchup,
            "primary_pitches": _primary_pitches(pitcher_mix),
            "exact_pitch_rows": exact_pitch_comparison_rows(
                database.get_bvp_pitch_type_stats_from_db(
                    batter_id,
                    pitcher_id,
                    season,
                ),
                pitcher_mix,
                batter_pitch_types,
            ),
        }
        enriched.append(enriched_row)
    composite = composite_bullpen_matchup(enriched)
    if game_pk is not None and opponent_team_id is not None:
        _cache_bullpen_projection(game_pk, game_date, opponent_team_id, enriched)
    return {"relievers": enriched, "composite": composite}


def _cache_bullpen_projection(game_pk, game_date, team_id, relievers):
    rows = []
    for row in relievers:
        pitcher_id = clean_player_id(row.get("player_id"))
        if pitcher_id is None:
            continue
        rows.append(
            {
                "game_date": str(game_date),
                "game_pk": int(game_pk),
                "team_id": int(team_id),
                "pitcher_id": pitcher_id,
                "projected_role": row.get("projected_role"),
                "availability_score": row.get("availability_score"),
                "availability_label": row.get("availability_label"),
                "appearance_probability": row.get("appearance_probability"),
                "expected_batters_faced_range": row.get("expected_batters_faced_range"),
                "recent_workload": (
                    f"{safe_int(row.get('pitches_yesterday'))} pitches yesterday; "
                    f"{safe_int(row.get('pitches_last_three_days'))} in last 3 days"
                ),
                "projection_reason": row.get("availability_reason"),
                "projection_timestamp": row.get("projection_timestamp"),
            }
        )
    database.save_daily_bullpen_projections(rows)

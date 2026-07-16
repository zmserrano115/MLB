"""Pure projected-bullpen availability and matchup weighting."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta

import pandas as pd

from src.domain.pitch_analysis import (
    direct_bvp_summary,
    evidence_blend,
    grade_from_score,
    parse_date,
    safe_divide,
    safe_float,
    safe_int,
    sample_size_label,
    score_from_projection,
)


@dataclass(frozen=True)
class AvailabilityConfig:
    base_score: float = 100.0
    appeared_earlier_penalty: float = 50.0
    unavailable_status_penalty: float = 100.0
    injured_status_penalty: float = 100.0
    optioned_status_penalty: float = 100.0
    suspended_status_penalty: float = 100.0
    pitches_yesterday_light_penalty: float = 10.0
    pitches_yesterday_medium_penalty: float = 25.0
    pitches_yesterday_heavy_penalty: float = 38.0
    pitches_two_days_penalty: float = 18.0
    pitches_three_days_penalty: float = 12.0
    consecutive_days_penalty: float = 18.0
    third_day_penalty: float = 24.0
    long_recent_ip_penalty: float = 12.0
    doubleheader_reserve_penalty: float = 8.0
    high_leverage_reserve_penalty: float = 5.0
    starter_role_penalty: float = 60.0
    likely_threshold: float = 78.0
    possible_threshold: float = 55.0
    limited_threshold: float = 30.0


AVAILABILITY_CONFIG = AvailabilityConfig()

ROLE_BASE_PROBABILITY = {
    "Closer": 0.24,
    "Setup": 0.21,
    "Middle Relief": 0.17,
    "Left-Handed Specialist": 0.14,
    "Multi-Inning Relief": 0.13,
    "Long Relief": 0.10,
    "Swing Relief": 0.08,
    "Emergency Relief": 0.04,
}

ROLE_EXPECTED_BF = {
    "Closer": (3, 4),
    "Setup": (3, 5),
    "Middle Relief": (3, 5),
    "Left-Handed Specialist": (1, 3),
    "Multi-Inning Relief": (5, 9),
    "Long Relief": (6, 12),
    "Swing Relief": (4, 8),
    "Emergency Relief": (2, 6),
}

INACTIVE_STATUS_KEYWORDS = {
    "injured": "injured",
    "injury": "injured",
    "il": "injured",
    "inactive": "inactive",
    "option": "optioned",
    "suspend": "suspended",
    "restricted": "inactive",
    "bereavement": "inactive",
    "paternity": "inactive",
}


def active_status_reason(status):
    text = str(status or "").strip().casefold()
    if not text:
        return None
    for needle, reason in INACTIVE_STATUS_KEYWORDS.items():
        if needle in text:
            return reason
    return None


def _clean_id(value):
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return None
    return int(number)


def _player_name(row):
    for column in ("Player", "Name", "pitcher_name", "player_name"):
        value = row.get(column)
        if value is not None and str(value).strip():
            return str(value).strip()
    return "Pitcher"


def _pitcher_hand(row):
    for column in ("Throws", "throwing_hand", "pitcher_hand", "hand"):
        value = row.get(column)
        if value is not None and str(value).strip():
            return str(value).strip().upper()[:1]
    return ""


def pitcher_stats_lookup(pitcher_stats):
    if pitcher_stats is None:
        return {}
    frame = pd.DataFrame(pitcher_stats)
    if frame.empty or "player_id" not in frame.columns:
        return {}
    rows = {}
    for _, row in frame.iterrows():
        player_id = _clean_id(row.get("player_id"))
        if player_id is not None:
            rows[player_id] = row.to_dict()
    return rows


def logs_by_pitcher(pitcher_logs):
    frame = pd.DataFrame(pitcher_logs)
    if frame.empty:
        return {}
    id_column = "pitcher_id" if "pitcher_id" in frame.columns else "player_id"
    if id_column not in frame.columns:
        return {}
    result = {}
    for player_id, rows in frame.groupby(frame[id_column].apply(_clean_id)):
        if player_id is not None:
            result[int(player_id)] = rows.to_dict("records")
    return result


def classify_pitcher_role(stats_row=None, log_rows: Sequence[Mapping] | None = None, throws=""):
    stats_row = dict(stats_row or {})
    log_rows = list(log_rows or [])
    games = safe_int(stats_row.get("G", stats_row.get("games")))
    starts = safe_int(stats_row.get("GS", stats_row.get("starts")))
    saves = safe_int(stats_row.get("SV", stats_row.get("saves")))
    holds = safe_int(stats_row.get("HLD", stats_row.get("holds")))
    ip = safe_float(stats_row.get("IP"))
    bf = safe_int(stats_row.get("BF"))
    start_ratio = safe_divide(starts, games) or 0.0
    relief_games = max(0, games - starts)
    avg_bf = safe_divide(bf, games) or 0.0
    recent_starts = sum(1 for row in log_rows[:6] if safe_int(row.get("is_starter")) == 1)

    if games and start_ratio >= 0.55 and recent_starts >= 2:
        return "Starter"
    if saves >= 8:
        return "Closer"
    if saves >= 3 or holds >= 6:
        return "Setup"
    if starts and 0.15 <= start_ratio < 0.55:
        return "Swing Relief"
    if avg_bf >= 7 or (ip is not None and games and ip / max(1, games) >= 1.5):
        return "Long Relief"
    if throws == "L" and relief_games >= 5:
        return "Left-Handed Specialist"
    if relief_games >= 20:
        return "Middle Relief"
    if relief_games >= 5:
        return "Multi-Inning Relief"
    return "Emergency Relief"


def workload_summary(log_rows: Sequence[Mapping], game_date, appeared_earlier=False):
    target_date = parse_date(game_date)
    logs = []
    for row in log_rows or []:
        log_date = parse_date(row.get("game_date"))
        if log_date is None:
            continue
        if target_date is not None and log_date > target_date:
            continue
        logs.append((log_date, dict(row)))
    logs.sort(key=lambda item: (item[0], safe_int(item[1].get("game_pk"))), reverse=True)

    pitches_yesterday = 0
    pitches_last_two = 0
    pitches_last_three = 0
    appearances_last_three = 0
    innings_last_three = 0.0
    dates_used = set()

    if target_date is not None:
        for log_date, row in logs:
            days_back = (target_date - log_date).days
            if days_back < 0:
                continue
            pitch_count = safe_int(row.get("pitch_count", row.get("Pitch Count")))
            innings_outs = safe_int(row.get("IP_outs"), default=None)
            ip = safe_float(row.get("IP"))
            ip_value = innings_outs / 3.0 if innings_outs is not None else ip or 0.0
            if days_back == 0:
                dates_used.add(log_date)
            if days_back == 1:
                pitches_yesterday += pitch_count
            if 1 <= days_back <= 2:
                pitches_last_two += pitch_count
            if 1 <= days_back <= 3:
                pitches_last_three += pitch_count
                appearances_last_three += 1
                innings_last_three += ip_value
                dates_used.add(log_date)

    consecutive_days = 0
    if target_date is not None:
        used_dates = {log_date for log_date, _ in logs}
        check = target_date - timedelta(days=1)
        while check in used_dates:
            consecutive_days += 1
            check -= timedelta(days=1)

    last_appearance_date = logs[0][0].isoformat() if logs else None
    return {
        "last_appearance_date": last_appearance_date,
        "pitches_yesterday": pitches_yesterday,
        "pitches_last_two_days": pitches_last_two,
        "pitches_last_three_days": pitches_last_three,
        "consecutive_days_used": consecutive_days,
        "appearances_last_three_games": appearances_last_three,
        "recent_innings_pitched": round(innings_last_three, 1),
        "appeared_earlier_today": bool(appeared_earlier),
    }


def availability_from_workload(
    workload,
    projected_role,
    status=None,
    doubleheader=False,
    config: AvailabilityConfig = AVAILABILITY_CONFIG,
):
    score = config.base_score
    reasons = []
    inactive_reason = active_status_reason(status)
    if inactive_reason == "injured":
        score -= config.injured_status_penalty
        reasons.append("injury or IL status")
    elif inactive_reason == "optioned":
        score -= config.optioned_status_penalty
        reasons.append("optioned or not active")
    elif inactive_reason == "suspended":
        score -= config.suspended_status_penalty
        reasons.append("suspended or restricted")
    elif inactive_reason:
        score -= config.unavailable_status_penalty
        reasons.append("inactive status")

    if workload.get("appeared_earlier_today"):
        score -= config.appeared_earlier_penalty
        reasons.append("already appeared earlier today")

    pitches_yesterday = safe_int(workload.get("pitches_yesterday"))
    if pitches_yesterday >= 31:
        score -= config.pitches_yesterday_heavy_penalty
        reasons.append(f"{pitches_yesterday} pitches yesterday")
    elif pitches_yesterday >= 20:
        score -= config.pitches_yesterday_medium_penalty
        reasons.append(f"{pitches_yesterday} pitches yesterday")
    elif pitches_yesterday > 0:
        score -= config.pitches_yesterday_light_penalty
        reasons.append(f"{pitches_yesterday} pitches yesterday")

    if safe_int(workload.get("pitches_last_two_days")) >= 45:
        score -= config.pitches_two_days_penalty
        reasons.append("heavy two-day workload")
    if safe_int(workload.get("pitches_last_three_days")) >= 65:
        score -= config.pitches_three_days_penalty
        reasons.append("heavy three-day workload")
    consecutive = safe_int(workload.get("consecutive_days_used"))
    if consecutive >= 2:
        score -= config.third_day_penalty
        reasons.append("used on consecutive days")
    elif consecutive == 1:
        score -= config.consecutive_days_penalty
        reasons.append("pitched yesterday")
    if (
        safe_float(workload.get("recent_innings_pitched"))
        and safe_float(workload.get("recent_innings_pitched")) >= 3
    ):
        score -= config.long_recent_ip_penalty
        reasons.append("multi-inning recent workload")
    if doubleheader:
        score -= config.doubleheader_reserve_penalty
        reasons.append("doubleheader reserve factor")
    if projected_role in {"Closer", "Setup"}:
        score -= config.high_leverage_reserve_penalty
        reasons.append("likely reserved for leverage")
    if projected_role == "Starter":
        score -= config.starter_role_penalty
        reasons.append("normal rotation starter")

    score = max(0.0, min(100.0, score))
    if score <= 0:
        label = "Unavailable"
    elif score < config.limited_threshold:
        label = "Limited"
    elif score < config.possible_threshold:
        label = "Possible"
    elif score < config.likely_threshold:
        label = "Likely"
    else:
        label = "Available"
    if not reasons:
        reasons.append("fresh recent workload")
    return {
        "availability_score": round(score, 1),
        "availability_label": label,
        "availability_reason": "; ".join(reasons),
    }


def _normalization_weight(role, availability_score):
    base = ROLE_BASE_PROBABILITY.get(role, 0.05)
    if availability_score <= 0:
        return 0.0
    return base * (availability_score / 100.0)


def normalize_appearance_probabilities(relievers):
    weighted = [dict(row) for row in relievers]
    total = sum(
        _normalization_weight(row["projected_role"], row["availability_score"]) for row in weighted
    )
    if total <= 0:
        for row in weighted:
            row["appearance_probability"] = 0.0
        return weighted
    for row in weighted:
        raw = _normalization_weight(row["projected_role"], row["availability_score"])
        row["appearance_probability"] = round(raw / total, 3)
    return weighted


def is_reliever_candidate(row, stats_row=None, log_rows=None, probable_starter_id=None):
    player_id = _clean_id(row.get("player_id"))
    if player_id is None:
        return False, "missing MLB player ID"
    if probable_starter_id is not None and player_id == int(probable_starter_id):
        return False, "selected probable starter"
    if active_status_reason(row.get("status")):
        return False, "inactive roster status"
    throws = _pitcher_hand(row) or _pitcher_hand(stats_row or {})
    role = classify_pitcher_role(stats_row, log_rows, throws=throws)
    if role == "Starter":
        return False, "normal rotation starter"
    return True, role


def build_projected_bullpen(
    roster_df,
    pitcher_stats_df,
    pitcher_logs_df=None,
    probable_starter_id=None,
    game_date=None,
    team_id=None,
    doubleheader=False,
    already_used_pitcher_ids: Iterable[int] | None = None,
    projection_timestamp=None,
):
    roster = pd.DataFrame(roster_df)
    if roster.empty:
        return []
    if "group" in roster.columns:
        roster = roster[roster["group"].astype(str).str.lower().eq("pitching")].copy()
    elif "Position" in roster.columns:
        roster = roster[roster["Position"].astype(str).str.upper().eq("P")].copy()
    if team_id is not None and "team_id" in roster.columns:
        roster = roster[pd.to_numeric(roster["team_id"], errors="coerce").eq(int(team_id))].copy()

    stats_by_id = pitcher_stats_lookup(pitcher_stats_df)
    logs_by_id = logs_by_pitcher(pitcher_logs_df)
    already_used = {
        clean_value
        for clean_value in (_clean_id(value) for value in (already_used_pitcher_ids or []))
        if clean_value is not None
    }
    rows = []
    for _, roster_row in roster.iterrows():
        player_id = _clean_id(roster_row.get("player_id"))
        if player_id is None:
            continue
        stats_row = stats_by_id.get(player_id, {})
        log_rows = logs_by_id.get(player_id, [])
        candidate, role_or_reason = is_reliever_candidate(
            roster_row,
            stats_row=stats_row,
            log_rows=log_rows,
            probable_starter_id=probable_starter_id,
        )
        if not candidate:
            if role_or_reason == "inactive roster status":
                workload = workload_summary(log_rows, game_date)
                availability = availability_from_workload(
                    workload,
                    "Emergency Relief",
                    status=roster_row.get("status"),
                    doubleheader=doubleheader,
                )
                rows.append(
                    _projection_row(
                        roster_row,
                        stats_row,
                        workload,
                        availability,
                        "Emergency Relief",
                        projection_timestamp,
                        excluded=True,
                        exclusion_reason=role_or_reason,
                    )
                )
            continue
        role = role_or_reason
        workload = workload_summary(
            log_rows,
            game_date,
            appeared_earlier=player_id in already_used,
        )
        availability = availability_from_workload(
            workload,
            role,
            status=roster_row.get("status"),
            doubleheader=doubleheader,
        )
        rows.append(
            _projection_row(
                roster_row,
                stats_row,
                workload,
                availability,
                role,
                projection_timestamp,
            )
        )
    rows = normalize_appearance_probabilities(rows)
    rows.sort(key=_reliever_sort_key)
    return rows


def _reliever_sort_key(row):
    probability = safe_float(row.get("appearance_probability")) or 0.0
    return (-probability, row.get("projected_role", ""), row.get("Player", ""))


def _projection_row(
    roster_row,
    stats_row,
    workload,
    availability,
    role,
    projection_timestamp,
    excluded=False,
    exclusion_reason=None,
):
    player_id = _clean_id(roster_row.get("player_id"))
    expected_bf = ROLE_EXPECTED_BF.get(role, (2, 5))
    throws = _pitcher_hand(roster_row) or _pitcher_hand(stats_row)
    return {
        "player_id": player_id,
        "Player": _player_name(roster_row)
        if _player_name(roster_row) != "Pitcher"
        else _player_name(stats_row),
        "Team": roster_row.get("Team") or roster_row.get("team_name") or stats_row.get("Team"),
        "team_id": roster_row.get("team_id") or stats_row.get("team_id"),
        "Throws": throws,
        "projected_role": role,
        "expected_batters_faced_range": f"{expected_bf[0]}-{expected_bf[1]}",
        "expected_batters_faced_midpoint": sum(expected_bf) / 2.0,
        "projection_timestamp": projection_timestamp,
        "excluded_from_composite": bool(excluded),
        "exclusion_reason": exclusion_reason,
        **workload,
        **availability,
    }


def matchup_projection_for_reliever(
    reliever,
    direct_stats=None,
    hand_split=None,
    pitch_type_projection=None,
    pitcher_allowed=None,
    baseline=None,
):
    direct = direct_bvp_summary(direct_stats or {})
    direct_pa = safe_int(direct.get("PA"))
    direct_woba = direct.get("wOBA")
    hand_woba = None
    if hand_split:
        hand_summary = direct_bvp_summary(hand_split)
        hand_woba = hand_summary.get("wOBA")
        hand_pa = safe_int(hand_split.get("PA"))
    else:
        hand_pa = 0
    pitch_type_woba = None
    pitch_type_pa = 0
    if pitch_type_projection:
        pitch_type_woba = pitch_type_projection.get("wOBA")
        pitch_type_pa = safe_int(pitch_type_projection.get("PA"))
    pitcher_allowed_woba = None
    pitcher_allowed_pa = 0
    if pitcher_allowed:
        pitcher_allowed_woba = pitcher_allowed.get("wOBA")
        pitcher_allowed_pa = safe_int(pitcher_allowed.get("PA"))
    baseline_woba = baseline.get("wOBA") if baseline else 0.315
    projected_woba = evidence_blend(
        direct=direct_woba,
        direct_pa=direct_pa,
        hand_split=hand_woba,
        hand_pa=hand_pa,
        pitch_type=pitch_type_woba,
        pitch_type_pa=pitch_type_pa,
        pitcher_allowed=pitcher_allowed_woba,
        pitcher_pa=pitcher_allowed_pa,
        baseline=baseline_woba,
    )
    projected_ops = evidence_blend(
        direct=direct.get("OPS"),
        direct_pa=direct_pa,
        hand_split=hand_split.get("OPS") if hand_split else None,
        hand_pa=hand_pa,
        pitch_type=pitch_type_projection.get("OPS") if pitch_type_projection else None,
        pitch_type_pa=pitch_type_pa,
        baseline=baseline.get("OPS") if baseline else 0.720,
    )
    projected_k = evidence_blend(
        direct=direct.get("K%"),
        direct_pa=direct_pa,
        hand_split=hand_split.get("K%") if hand_split else None,
        hand_pa=hand_pa,
        pitch_type=pitch_type_projection.get("K%") if pitch_type_projection else None,
        pitch_type_pa=pitch_type_pa,
        baseline=baseline.get("K%") if baseline else 22.0,
    )
    projected_bb = evidence_blend(
        direct=direct.get("BB%"),
        direct_pa=direct_pa,
        hand_split=hand_split.get("BB%") if hand_split else None,
        hand_pa=hand_pa,
        baseline=baseline.get("BB%") if baseline else 8.0,
    )
    score = score_from_projection(
        woba=projected_woba,
        ops=projected_ops,
        k_pct=projected_k,
        bb_pct=projected_bb,
    )
    reason = _matchup_reason(direct, projected_woba, projected_k, reliever)
    return {
        "Direct PA": direct_pa,
        "Direct AVG": direct.get("AVG"),
        "Direct OBP": direct.get("OBP"),
        "Direct SLG": direct.get("SLG"),
        "Direct OPS": direct.get("OPS"),
        "Direct wOBA": direct.get("wOBA"),
        "projected_wOBA": projected_woba,
        "projected_OPS": projected_ops,
        "projected_K%": projected_k,
        "projected_BB%": projected_bb,
        "matchup_score": round(score, 1),
        "matchup_grade": grade_from_score(score),
        "sample_confidence": sample_size_label(direct_pa),
        "matchup_reason": reason,
    }


def _matchup_reason(direct, projected_woba, projected_k, reliever):
    direct_pa = safe_int(direct.get("PA"))
    parts = []
    if direct_pa:
        parts.append(f"{direct_pa} direct PA")
    else:
        parts.append("no direct BvP sample")
    if projected_woba is not None:
        if projected_woba >= 0.350:
            parts.append("adjusted quality leans batter")
        elif projected_woba <= 0.290:
            parts.append("adjusted quality leans pitcher")
        else:
            parts.append("adjusted quality is near neutral")
    if projected_k is not None:
        if projected_k >= 27:
            parts.append("elevated strikeout risk")
        elif projected_k <= 18:
            parts.append("manageable strikeout profile")
    if reliever.get("availability_label") in {"Limited", "Unavailable"}:
        parts.append("availability discount applied")
    return "; ".join(parts)


def composite_bullpen_matchup(relievers: Sequence[Mapping]):
    included = [
        dict(row)
        for row in relievers
        if not row.get("excluded_from_composite")
        and row.get("availability_label") != "Unavailable"
        and safe_float(row.get("appearance_probability")) is not None
    ]
    active_count = len([row for row in relievers if not row.get("excluded_from_composite")])
    excluded_count = len(relievers) - len(included)
    if not included:
        return {
            "overall_score": None,
            "overall_grade": "No Data",
            "active_relievers_included": 0,
            "excluded_because_availability": excluded_count,
            "confidence": "Unavailable",
        }
    weights = []
    for row in included:
        probability = safe_float(row.get("appearance_probability")) or 0.0
        availability = (safe_float(row.get("availability_score")) or 0.0) / 100.0
        expected_bf = safe_float(row.get("expected_batters_faced_midpoint")) or 3.0
        role_weight = 1.1 if row.get("projected_role") in {"Closer", "Setup"} else 1.0
        weights.append(max(0.0, probability * availability * expected_bf * role_weight))
    total_weight = sum(weights)
    if total_weight <= 0:
        total_weight = len(included)
        weights = [1.0] * len(included)

    def weighted_metric(column):
        pairs = [
            (safe_float(row.get(column)), weight)
            for row, weight in zip(included, weights, strict=True)
            if safe_float(row.get(column)) is not None
        ]
        metric_weight = sum(weight for _, weight in pairs)
        if metric_weight <= 0:
            return None
        return sum(value * weight for value, weight in pairs) / metric_weight

    overall_score = weighted_metric("matchup_score")
    favorable = max(included, key=lambda row: safe_float(row.get("matchup_score")) or -1)
    difficult = min(included, key=lambda row: safe_float(row.get("matchup_score")) or 101)
    likely = max(included, key=lambda row: safe_float(row.get("appearance_probability")) or 0)
    confidence = _composite_confidence(included)
    return {
        "overall_score": round(overall_score, 1) if overall_score is not None else None,
        "overall_grade": grade_from_score(overall_score),
        "projected_K%": weighted_metric("projected_K%"),
        "projected_BB%": weighted_metric("projected_BB%"),
        "projected_AVG": weighted_metric("Direct AVG"),
        "projected_OBP": weighted_metric("Direct OBP"),
        "projected_SLG": weighted_metric("Direct SLG"),
        "projected_wOBA": weighted_metric("projected_wOBA"),
        "projected_hr_xbh_risk": _xbh_risk(weighted_metric("projected_wOBA")),
        "most_favorable": favorable.get("Player"),
        "most_difficult": difficult.get("Player"),
        "most_likely": likely.get("Player"),
        "active_relievers_included": active_count,
        "excluded_because_availability": excluded_count,
        "confidence": confidence,
    }


def _composite_confidence(rows):
    if not rows:
        return "Unavailable"
    direct_pa = sum(safe_int(row.get("Direct PA")) for row in rows)
    if direct_pa >= 40:
        return "Stronger sample"
    if direct_pa >= 16:
        return "Moderate"
    if direct_pa >= 5:
        return "Limited"
    return "Very limited"


def _xbh_risk(woba):
    value = safe_float(woba)
    if value is None:
        return "Unavailable"
    if value >= 0.365:
        return "Elevated"
    if value >= 0.325:
        return "Moderate"
    return "Lower"

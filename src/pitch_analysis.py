"""Pitch-level and matchup calculation helpers for Advanced HVP research."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Mapping, Sequence

import pandas as pd


UNAVAILABLE = "\u2014"

PITCH_CODE_MAP = {
    "FF": "Four-Seam Fastball",
    "SI": "Sinker",
    "FT": "Two-Seam Fastball",
    "FC": "Cutter",
    "SL": "Slider",
    "ST": "Sweeper",
    "SV": "Slurve",
    "CU": "Curveball",
    "KC": "Knuckle Curve",
    "CS": "Slow Curve",
    "CH": "Changeup",
    "FS": "Split-Finger",
    "FO": "Forkball",
    "KN": "Knuckleball",
    "SC": "Screwball",
    "EP": "Eephus",
    "FA": "Generic Fastball",
}

SWING_DESCRIPTIONS = {
    "swinging_strike",
    "swinging_strike_blocked",
    "foul",
    "foul_tip",
    "foul_bunt",
    "missed_bunt",
    "hit_into_play",
    "hit_into_play_no_out",
    "hit_into_play_score",
}

CONTACT_DESCRIPTIONS = {
    "foul",
    "foul_tip",
    "foul_bunt",
    "hit_into_play",
    "hit_into_play_no_out",
    "hit_into_play_score",
}

WHIFF_DESCRIPTIONS = {
    "swinging_strike",
    "swinging_strike_blocked",
    "missed_bunt",
}

CALLED_STRIKE_DESCRIPTIONS = {"called_strike"}
STRIKE_DESCRIPTIONS = CALLED_STRIKE_DESCRIPTIONS | WHIFF_DESCRIPTIONS
BIP_EVENTS = {
    "single",
    "double",
    "triple",
    "home_run",
    "field_out",
    "force_out",
    "grounded_into_double_play",
    "fielders_choice_out",
    "fielders_choice",
    "sac_fly",
    "sac_bunt",
    "double_play",
    "triple_play",
}
HIT_EVENTS = {"single", "double", "triple", "home_run"}


@dataclass(frozen=True)
class ShrinkageConfig:
    direct_bvp_weight: float = 24.0
    hand_split_weight: float = 80.0
    pitch_type_weight: float = 120.0
    baseline_weight: float = 180.0


def safe_float(value):
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return None
    return float(number)


def safe_int(value, default=0):
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return default
    return int(number)


def safe_divide(numerator, denominator, scale=1.0):
    numerator = safe_float(numerator)
    denominator = safe_float(denominator)
    if numerator is None or denominator in (None, 0):
        return None
    return numerator * scale / denominator


def fmt_metric(value, digits=3, percent=False):
    number = safe_float(value)
    if number is None:
        return UNAVAILABLE
    if percent:
        return f"{number:.1f}%"
    if digits == 0:
        return f"{number:.0f}"
    if 0 <= abs(number) < 2 and digits == 3:
        return f"{number:.3f}"
    return f"{number:.{digits}f}"


def normalize_pitch_code(code):
    text = "" if code is None else str(code).strip().upper()
    return text or "UNK"


def pitch_name_for_code(code):
    pitch_code = normalize_pitch_code(code)
    if pitch_code == "UNK":
        return "Unknown or Unclassified"
    return PITCH_CODE_MAP.get(pitch_code, f"Unknown or Unclassified ({pitch_code})")


def sample_size_label(pa):
    plate_appearances = safe_int(pa, default=0)
    if plate_appearances < 5:
        return "Very limited"
    if plate_appearances < 20:
        return "Limited"
    if plate_appearances < 50:
        return "Moderate"
    return "Stronger sample"


def calculate_batting_rates(raw: Mapping):
    ab = safe_int(raw.get("AB"))
    pa = safe_int(raw.get("PA"))
    hits = safe_int(raw.get("H"))
    doubles = safe_int(raw.get("2B", raw.get("doubles")))
    triples = safe_int(raw.get("3B", raw.get("triples")))
    hr = safe_int(raw.get("HR"))
    bb = safe_int(raw.get("BB"))
    hbp = safe_int(raw.get("HBP"))
    sf = safe_int(raw.get("SF"))
    so = safe_int(raw.get("SO", raw.get("K")))
    tb = raw.get("TB")
    if tb is None:
        singles = max(0, hits - doubles - triples - hr)
        tb = singles + doubles * 2 + triples * 3 + hr * 4
    tb = safe_int(tb)

    avg = safe_divide(hits, ab)
    obp = safe_divide(hits + bb + hbp, ab + bb + hbp + sf)
    slg = safe_divide(tb, ab)
    ops = None if obp is None or slg is None else obp + slg
    k_pct = safe_divide(so, pa, scale=100)
    bb_pct = safe_divide(bb, pa, scale=100)
    babip = safe_divide(hits - hr, ab - so - hr + sf)

    return {
        "AVG": avg,
        "OBP": obp,
        "SLG": slg,
        "OPS": ops,
        "K%": k_pct,
        "BB%": bb_pct,
        "BABIP": babip,
        "TB": tb,
    }


def approximate_woba(raw: Mapping):
    pa = safe_int(raw.get("PA"))
    ab = safe_int(raw.get("AB"))
    bb = safe_int(raw.get("BB"))
    hbp = safe_int(raw.get("HBP"))
    sf = safe_int(raw.get("SF"))
    hits = safe_int(raw.get("H"))
    doubles = safe_int(raw.get("2B", raw.get("doubles")))
    triples = safe_int(raw.get("3B", raw.get("triples")))
    hr = safe_int(raw.get("HR"))
    singles = max(0, hits - doubles - triples - hr)
    denominator = ab + bb + hbp + sf
    if pa <= 0 or denominator <= 0:
        return None
    weighted = (
        0.69 * bb
        + 0.72 * hbp
        + 0.88 * singles
        + 1.25 * doubles
        + 1.58 * triples
        + 2.03 * hr
    )
    return weighted / denominator


def direct_bvp_summary(stats: Mapping | None, game_logs: Sequence[Mapping] | None = None):
    stats = dict(stats or {})
    game_logs = list(game_logs or [])
    pa = safe_int(stats.get("PA"))
    ab = safe_int(stats.get("AB"))
    hits = safe_int(stats.get("H"))
    doubles = safe_int(stats.get("2B", stats.get("doubles")))
    triples = safe_int(stats.get("3B", stats.get("triples")))
    hr = safe_int(stats.get("HR"))
    singles = max(0, hits - doubles - triples - hr)
    summary = {
        "PA": pa,
        "AB": ab,
        "H": hits,
        "1B": singles,
        "2B": doubles,
        "3B": triples,
        "HR": hr,
        "BB": safe_int(stats.get("BB")),
        "SO": safe_int(stats.get("SO", stats.get("K"))),
        "RBI": safe_int(stats.get("RBI")),
        "HBP": safe_int(stats.get("HBP")),
        "SF": safe_int(stats.get("SF")),
        "sample_label": sample_size_label(pa),
        "last_matchup_date": stats.get("last_game_date"),
    }
    summary.update(calculate_batting_rates(summary))
    summary["wOBA"] = approximate_woba(summary)
    summary["Barrel%"] = safe_float(stats.get("Barrel%"))
    summary["Hard-hit%"] = safe_float(stats.get("Hard-hit%"))
    dates = [
        pd.to_datetime(row.get("game_date"), errors="coerce")
        for row in game_logs
        if row.get("game_date")
    ]
    dates = [value for value in dates if pd.notna(value)]
    if dates:
        summary["data_date_range"] = (
            f"{min(dates).date().isoformat()} to {max(dates).date().isoformat()}"
        )
        summary["last_matchup_date"] = max(dates).date().isoformat()
    else:
        summary["data_date_range"] = None
    return summary


def _event_value(event):
    event = str(event or "").strip().lower()
    if event == "single":
        return 1, 1
    if event == "double":
        return 1, 2
    if event == "triple":
        return 1, 3
    if event == "home_run":
        return 1, 4
    if event in BIP_EVENTS:
        return 0, 0
    return 0, 0


def _description(row):
    return str(row.get("pitch_description") or row.get("description") or "").strip().lower()


def _is_zone(row):
    zone = safe_int(row.get("zone"), default=None)
    if zone is not None:
        return 1 <= zone <= 9
    plate_x = safe_float(row.get("plate_x"))
    plate_z = safe_float(row.get("plate_z"))
    if plate_x is None or plate_z is None:
        return None
    return abs(plate_x) <= 0.83 and 1.5 <= plate_z <= 3.5


def _pitch_flags(row):
    description = _description(row)
    event = str(row.get("event") or "").strip().lower()
    swung = bool(row.get("swung")) if row.get("swung") is not None else description in SWING_DESCRIPTIONS
    contact = (
        bool(row.get("contact"))
        if row.get("contact") is not None
        else description in CONTACT_DESCRIPTIONS or event in BIP_EVENTS
    )
    whiff = bool(row.get("whiff")) if row.get("whiff") is not None else description in WHIFF_DESCRIPTIONS
    called = description in CALLED_STRIKE_DESCRIPTIONS
    return {
        "swung": swung,
        "contact": contact,
        "whiff": whiff,
        "called_strike": called,
        "csw": called or whiff,
    }


def pitch_sequence_sort_key(row):
    game_date = str(row.get("game_date") or "")
    game_pk = safe_int(row.get("game_pk"))
    at_bat = safe_int(row.get("at_bat_number"))
    pitch_number = safe_int(row.get("pitch_number"))
    return (game_date, game_pk, at_bat, pitch_number)


def ordered_pitch_sequence(rows: Iterable[Mapping]):
    return sorted((dict(row) for row in rows), key=pitch_sequence_sort_key)


def plate_appearance_logs_from_pitches(rows: Iterable[Mapping]):
    grouped = defaultdict(list)
    for row in ordered_pitch_sequence(rows):
        grouped[
            (
                row.get("game_pk"),
                row.get("game_date"),
                row.get("at_bat_number"),
                row.get("batter_id"),
                row.get("pitcher_id"),
            )
        ].append(row)

    plate_appearances = []
    for key, pitches in grouped.items():
        game_pk, game_date, at_bat_number, batter_id, pitcher_id = key
        final_pitch = pitches[-1]
        pitch_tokens = [
            normalize_pitch_code(pitch.get("pitch_type"))
            for pitch in pitches
        ]
        plate_appearances.append(
            {
                "game_pk": game_pk,
                "game_date": game_date,
                "at_bat_number": at_bat_number,
                "batter_id": batter_id,
                "pitcher_id": pitcher_id,
                "inning": final_pitch.get("inning"),
                "outs": final_pitch.get("outs"),
                "starting_count": _count_text(pitches[0]),
                "final_count": _count_text(final_pitch),
                "event": final_pitch.get("event"),
                "rbi": final_pitch.get("rbi"),
                "runs_produced": final_pitch.get("runs_produced"),
                "pitch_count": len(pitches),
                "pitch_sequence": " ".join(pitch_tokens),
                "launch_speed": final_pitch.get("launch_speed"),
                "launch_angle": final_pitch.get("launch_angle"),
                "estimated_distance": final_pitch.get("estimated_distance"),
                "barrel": final_pitch.get("barrel"),
                "hard_hit": final_pitch.get("hard_hit"),
                "pitches": pitches,
            }
        )
    return sorted(
        plate_appearances,
        key=lambda row: (str(row.get("game_date") or ""), safe_int(row.get("at_bat_number"))),
        reverse=True,
    )


def _count_text(row):
    balls = row.get("balls")
    strikes = row.get("strikes")
    if balls is None or strikes is None:
        return UNAVAILABLE
    return f"{safe_int(balls)}-{safe_int(strikes)}"


def calculate_pitch_type_summaries(rows: Iterable[Mapping]):
    rows = [dict(row) for row in rows]
    if not rows:
        return []
    total_pitches = len(rows)
    grouped = defaultdict(list)
    for row in rows:
        code = normalize_pitch_code(row.get("pitch_type"))
        grouped[code].append(row)

    summaries = []
    for code, pitch_rows in grouped.items():
        pitch_count = len(pitch_rows)
        flags = [_pitch_flags(row) for row in pitch_rows]
        zone_values = [_is_zone(row) for row in pitch_rows]
        known_zone = [value for value in zone_values if value is not None]
        outside_swings = [
            flag["swung"]
            for flag, in_zone in zip(flags, zone_values)
            if in_zone is False
        ]
        batted_rows = [
            row
            for row in pitch_rows
            if str(row.get("event") or "").strip().lower() in BIP_EVENTS
        ]
        balls_in_play = len(batted_rows)
        hits = 0
        tb = 0
        hr = 0
        strikeouts = 0
        walks = 0
        for row in pitch_rows:
            event = str(row.get("event") or "").strip().lower()
            hit, bases = _event_value(event)
            hits += hit
            tb += bases
            if event == "home_run":
                hr += 1
            if event == "strikeout":
                strikeouts += 1
            if event == "walk":
                walks += 1
        hard_hit = [
            row
            for row in batted_rows
            if bool(row.get("hard_hit"))
            or (safe_float(row.get("launch_speed")) is not None and safe_float(row.get("launch_speed")) >= 95)
        ]
        barrels = [row for row in batted_rows if bool(row.get("barrel"))]
        estimated_woba = [
            safe_float(row.get("estimated_woba"))
            for row in batted_rows
            if safe_float(row.get("estimated_woba")) is not None
        ]
        estimated_ba = [
            safe_float(row.get("estimated_ba"))
            for row in batted_rows
            if safe_float(row.get("estimated_ba")) is not None
        ]
        velocities = [safe_float(row.get("release_speed")) for row in pitch_rows]
        velocities = [value for value in velocities if value is not None]
        spin = [safe_float(row.get("release_spin_rate")) for row in pitch_rows]
        spin = [value for value in spin if value is not None]
        pfx_x = [safe_float(row.get("pfx_x")) for row in pitch_rows]
        pfx_x = [value for value in pfx_x if value is not None]
        pfx_z = [safe_float(row.get("pfx_z")) for row in pitch_rows]
        pfx_z = [value for value in pfx_z if value is not None]
        swings = sum(1 for flag in flags if flag["swung"])
        contacts = sum(1 for flag in flags if flag["contact"])
        whiffs = sum(1 for flag in flags if flag["whiff"])
        csw = sum(1 for flag in flags if flag["csw"])
        ab = balls_in_play + strikeouts
        summary = {
            "pitch_type": code,
            "pitch_name": pitch_name_for_code(code),
            "pitch_count": pitch_count,
            "usage_pct": safe_divide(pitch_count, total_pitches, scale=100),
            "avg_velocity": _avg(velocities),
            "max_velocity": max(velocities) if velocities else None,
            "avg_spin_rate": _avg(spin),
            "horizontal_movement": _avg(pfx_x),
            "vertical_movement": _avg(pfx_z),
            "zone_pct": safe_divide(sum(1 for value in known_zone if value), len(known_zone), scale=100),
            "chase_pct": safe_divide(sum(1 for value in outside_swings if value), len(outside_swings), scale=100),
            "whiff_pct": safe_divide(whiffs, swings, scale=100),
            "csw_pct": safe_divide(csw, pitch_count, scale=100),
            "contact_pct": safe_divide(contacts, swings, scale=100),
            "hard_hit_pct": safe_divide(len(hard_hit), balls_in_play, scale=100),
            "barrel_pct": safe_divide(len(barrels), balls_in_play, scale=100),
            "AVG": safe_divide(hits, ab),
            "SLG": safe_divide(tb, ab),
            "wOBA": _avg(estimated_woba),
            "xwOBA": _avg(estimated_woba),
            "xBA": _avg(estimated_ba),
            "K%": safe_divide(strikeouts, max(1, ab + walks), scale=100),
            "balls_in_play": balls_in_play,
            "sample_size": sample_size_label(pitch_count),
        }
        summaries.append(summary)
    return sorted(summaries, key=lambda row: (-safe_int(row["pitch_count"]), row["pitch_name"]))


def _avg(values):
    values = [safe_float(value) for value in values]
    values = [value for value in values if value is not None]
    if not values:
        return None
    return sum(values) / len(values)


def shrink_rate(observed, sample_size, fallback, fallback_weight):
    observed = safe_float(observed)
    fallback = safe_float(fallback)
    sample_size = safe_float(sample_size)
    fallback_weight = safe_float(fallback_weight)
    if observed is None and fallback is None:
        return None
    if observed is None:
        return fallback
    if fallback is None:
        return observed
    if sample_size is None or sample_size <= 0:
        return fallback
    if fallback_weight is None or fallback_weight <= 0:
        return observed
    return ((observed * sample_size) + (fallback * fallback_weight)) / (
        sample_size + fallback_weight
    )


def evidence_blend(
    direct=None,
    direct_pa=0,
    hand_split=None,
    hand_pa=0,
    pitch_type=None,
    pitch_type_pa=0,
    pitcher_allowed=None,
    pitcher_pa=0,
    baseline=None,
    config: ShrinkageConfig | None = None,
):
    config = config or ShrinkageConfig()
    baseline_value = safe_float(baseline)
    values = []
    if baseline_value is not None:
        values.append((baseline_value, config.baseline_weight))
    for value, sample, cap in (
        (pitcher_allowed, pitcher_pa, config.pitch_type_weight),
        (pitch_type, pitch_type_pa, config.pitch_type_weight),
        (hand_split, hand_pa, config.hand_split_weight),
        (direct, direct_pa, config.direct_bvp_weight),
    ):
        number = safe_float(value)
        sample = max(0.0, safe_float(sample) or 0.0)
        if number is not None and sample > 0:
            values.append((number, min(sample, cap)))
    if not values:
        return None
    total_weight = sum(weight for _, weight in values)
    if total_weight <= 0:
        return None
    return sum(value * weight for value, weight in values) / total_weight


def grade_from_score(score):
    score = safe_float(score)
    if score is None:
        return "No Data"
    if score >= 72:
        return "Strong Matchup"
    if score >= 58:
        return "Good Matchup"
    if score >= 44:
        return "Neutral"
    return "Difficult"


def score_from_projection(woba=None, ops=None, k_pct=None, bb_pct=None):
    score = 50.0
    woba = safe_float(woba)
    ops = safe_float(ops)
    k_pct = safe_float(k_pct)
    bb_pct = safe_float(bb_pct)
    if woba is not None:
        score += (woba - 0.315) * 140
    elif ops is not None:
        score += (ops - 0.720) * 55
    if k_pct is not None:
        score += (22.0 - k_pct) * 0.55
    if bb_pct is not None:
        score += (bb_pct - 8.0) * 0.45
    return max(0.0, min(100.0, score))


def parse_date(value):
    if isinstance(value, date):
        return value
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    if isinstance(parsed, datetime):
        return parsed.date()
    return parsed.to_pydatetime().date()

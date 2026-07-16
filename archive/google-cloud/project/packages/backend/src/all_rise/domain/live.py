"""Pure normalization helpers for MLB live-feed payloads."""

from __future__ import annotations

import json
from collections.abc import Mapping
from hashlib import sha256
from typing import Any

import pandas as pd

PLAY_RESULT_LABELS = {
    "strikeout": "Strikeout",
    "groundout": "Groundout",
    "flyout": "Flyout",
    "popout": "Popout",
    "lineout": "Lineout",
    "forceout": "Forceout",
    "double_play": "Double Play",
    "single": "Single",
    "double": "Double",
    "triple": "Triple",
    "home_run": "Home Run",
    "walk": "Walk",
    "hit_by_pitch": "Hit By Pitch",
    "error": "Error",
    "sac_fly": "Sac Fly",
    "stolen_base": "Stolen Base",
    "other": "Other",
}


def safe_int(value: object, default: int | None = 0) -> int | None:
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return default
    return int(number)


def safe_float(value: object, default: float | None = None) -> float | None:
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return default
    return float(number)


def classify_play_result(result: Mapping[str, object] | None) -> str:
    result = result or {}
    event = str(result.get("event") or "").strip().lower()
    event_type = str(result.get("eventType") or "").strip().lower()
    combined = f"{event} {event_type}".replace("_", " ")
    rules = (
        ("home_run", ("home run", "homer")),
        ("hit_by_pitch", ("hit by pitch",)),
        ("stolen_base", ("stolen base",)),
        ("sac_fly", ("sac fly", "sacrifice fly")),
        ("double_play", ("double play", "grounded into dp")),
        ("strikeout", ("strikeout", "strike out")),
        ("forceout", ("forceout", "force out")),
        ("groundout", ("groundout", "ground out")),
        ("flyout", ("flyout", "fly out")),
        ("popout", ("popout", "pop out")),
        ("lineout", ("lineout", "line out")),
        ("triple", ("triple",)),
        ("double", ("double",)),
        ("single", ("single",)),
        ("walk", ("intent walk", "intentional walk", "walk")),
        ("error", ("error", "field error")),
    )
    for result_type, terms in rules:
        if any(term in combined for term in terms):
            return result_type
    return "other"


def _pitch_count(event: Mapping[str, Any] | None) -> dict[str, int | None]:
    count = (event or {}).get("count") or {}
    return {
        "balls": safe_int(count.get("balls")),
        "strikes": safe_int(count.get("strikes")),
        "outs": safe_int(count.get("outs")),
    }


def parse_pitch_event(event: Mapping[str, Any] | None) -> dict[str, object]:
    event = event or {}
    details = event.get("details") or {}
    pitch_data = event.get("pitchData") or {}
    coordinates = pitch_data.get("coordinates") or {}
    pitch_type = details.get("type") or {}
    call = details.get("call") or {}
    return {
        "play_id": event.get("playId"),
        "event_index": event.get("index"),
        "description": details.get("description") or call.get("description") or "",
        "code": details.get("code") or call.get("code"),
        "call": call.get("description") or details.get("description") or "",
        "is_strike": bool(details.get("isStrike")),
        "is_ball": bool(details.get("isBall")),
        "is_in_play": bool(details.get("isInPlay")),
        "is_out": bool(details.get("isOut")),
        "count_after": _pitch_count(event),
        "zone": safe_int(details.get("zone"), default=None),
        "pitch_type": pitch_type.get("description") or pitch_type.get("code"),
        "pitch_code": pitch_type.get("code"),
        "start_speed": safe_float(pitch_data.get("startSpeed")),
        "p_x": safe_float(coordinates.get("pX")),
        "p_z": safe_float(coordinates.get("pZ")),
        "strike_zone_top": safe_float(pitch_data.get("strikeZoneTop")),
        "strike_zone_bottom": safe_float(pitch_data.get("strikeZoneBottom")),
    }


def annotate_pitch_counts(
    pitch_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    previous_count: dict[str, int | None] | None = None
    for pitch in pitch_events:
        count_after = _pitch_count({"count": pitch.get("count_after")})
        count_before = (
            dict(previous_count)
            if previous_count is not None
            else {"balls": 0, "strikes": 0, "outs": count_after["outs"]}
        )
        pitch["count_before"] = count_before
        pitch["count_after"] = count_after
        previous_count = count_after
    return pitch_events


def count_current_play_fouls(current_play: Mapping[str, Any]) -> int:
    return sum(
        1
        for event in (current_play.get("playEvents") or [])
        if event.get("isPitch")
        and "foul"
        in " ".join(
            [
                str((event.get("details") or {}).get("description") or ""),
                str(((event.get("details") or {}).get("call") or {}).get("description") or ""),
            ]
        ).lower()
    )


def parse_live_game_feed(feed: Mapping[str, Any], game_id: str) -> dict[str, Any]:
    """Reduce an MLB live feed to the bounded snapshot consumed by every viewer."""
    game_data = _mapping(feed.get("gameData"))
    live_data = _mapping(feed.get("liveData"))
    status = _mapping(game_data.get("status"))
    linescore = _mapping(live_data.get("linescore"))
    teams = _mapping(game_data.get("teams"))
    plays = _mapping(live_data.get("plays"))
    all_plays = [play for play in plays.get("allPlays", []) if isinstance(play, Mapping)]
    current_play = _mapping(plays.get("currentPlay"))
    if not current_play and all_plays:
        current_play = all_plays[-1]
    feed_timestamp = str(feed.get("metaData", {}).get("timeStamp") or "")
    abstract_state = str(status.get("abstractGameState") or "Preview")
    snapshot: dict[str, Any] = {
        "game_id": game_id,
        "feed_timestamp": feed_timestamp or None,
        "abstract_state": abstract_state,
        "detailed_state": str(status.get("detailedState") or abstract_state),
        "is_final": abstract_state.lower() == "final",
        "inning": safe_int(linescore.get("currentInning"), 0),
        "inning_ordinal": linescore.get("currentInningOrdinal"),
        "half_inning": linescore.get("inningHalf"),
        "count": {
            "balls": safe_int(linescore.get("balls"), 0),
            "strikes": safe_int(linescore.get("strikes"), 0),
            "outs": safe_int(linescore.get("outs"), 0),
            "fouls": count_current_play_fouls(current_play),
        },
        "teams": {
            "away": _team_snapshot(teams.get("away"), linescore, "away"),
            "home": _team_snapshot(teams.get("home"), linescore, "home"),
        },
        "bases": _bases(linescore),
        "matchup": _matchup(linescore, current_play),
        "pitches": _pitches(current_play)[-12:],
        "recent_plays": [_play(play) for play in all_plays[-8:]],
        "boxscore": _boxscore(live_data.get("boxscore")),
    }
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str)
    snapshot["version"] = feed_timestamp or sha256(canonical.encode()).hexdigest()[:20]
    return snapshot


def live_event_records(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Create stable, replay-safe event rows from a compact snapshot."""
    events: list[dict[str, Any]] = []
    for sequence, play in enumerate(snapshot.get("recent_plays", [])):
        if not isinstance(play, Mapping):
            continue
        key = str(play.get("play_id") or f"{snapshot.get('version')}:{sequence}")
        events.append(
            {
                "event_key": key,
                "sequence": safe_int(play.get("at_bat_index"), sequence),
                "inning": safe_int(play.get("inning"), 0),
                "half_inning": play.get("half_inning"),
                "event_type": play.get("result_type") or "other",
                "description": play.get("description") or "",
                "payload": dict(play),
                "source_updated_at": snapshot.get("feed_timestamp"),
            }
        )
    return events


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _team_snapshot(value: Any, linescore: Mapping[str, Any], side: str) -> dict[str, Any]:
    team = _mapping(value)
    totals = _mapping(_mapping(linescore.get("teams")).get(side))
    return {
        "id": safe_int(team.get("id"), None),
        "name": team.get("name") or side.title(),
        "abbreviation": team.get("abbreviation"),
        "runs": safe_int(totals.get("runs"), 0),
        "hits": safe_int(totals.get("hits"), 0),
        "errors": safe_int(totals.get("errors"), 0),
    }


def _person(value: Any) -> dict[str, Any] | None:
    person = _mapping(value)
    identifier = safe_int(person.get("id"), None)
    if identifier is None:
        return None
    return {
        "id": identifier,
        "name": person.get("fullName") or person.get("name") or "Unknown",
        "headshot_url": f"https://img.mlbstatic.com/mlb-photos/image/upload/w_180,q_auto:best/v1/people/{identifier}/headshot/67/current",
    }


def _bases(linescore: Mapping[str, Any]) -> dict[str, bool]:
    offense = _mapping(linescore.get("offense"))
    return {
        base: bool(_mapping(offense.get(base)).get("id")) for base in ("first", "second", "third")
    }


def _matchup(linescore: Mapping[str, Any], current_play: Mapping[str, Any]) -> dict[str, Any]:
    offense = _mapping(linescore.get("offense"))
    defense = _mapping(linescore.get("defense"))
    matchup = _mapping(current_play.get("matchup"))
    return {
        "batter": _person(matchup.get("batter") or offense.get("batter")),
        "pitcher": _person(matchup.get("pitcher") or defense.get("pitcher")),
        "on_deck": _person(offense.get("onDeck")),
        "bat_side": _mapping(matchup.get("batSide")).get("description"),
        "pitch_hand": _mapping(matchup.get("pitchHand")).get("description"),
    }


def _pitches(play: Mapping[str, Any]) -> list[dict[str, Any]]:
    parsed = [
        parse_pitch_event(event)
        for event in play.get("playEvents", [])
        if isinstance(event, Mapping) and event.get("isPitch")
    ]
    return annotate_pitch_counts(parsed)


def _play(play: Mapping[str, Any]) -> dict[str, Any]:
    about = _mapping(play.get("about"))
    result = _mapping(play.get("result"))
    matchup = _mapping(play.get("matchup"))
    hit = _mapping(play.get("hitData"))
    coordinates = _mapping(hit.get("coordinates"))
    return {
        "play_id": about.get("atBatIndex")
        if about.get("atBatIndex") is not None
        else play.get("playId"),
        "at_bat_index": safe_int(about.get("atBatIndex"), 0),
        "inning": safe_int(about.get("inning"), 0),
        "half_inning": about.get("halfInning"),
        "is_complete": bool(about.get("isComplete", True)),
        "result_type": classify_play_result(result),
        "event": result.get("event"),
        "description": result.get("description") or "",
        "rbi": safe_int(result.get("rbi"), 0),
        "away_score": safe_int(result.get("awayScore"), None),
        "home_score": safe_int(result.get("homeScore"), None),
        "batter": _person(matchup.get("batter")),
        "pitcher": _person(matchup.get("pitcher")),
        "contact": {
            "launch_speed": safe_float(hit.get("launchSpeed")),
            "launch_angle": safe_float(hit.get("launchAngle")),
            "total_distance": safe_float(hit.get("totalDistance")),
            "trajectory": hit.get("trajectory"),
            "x": safe_float(coordinates.get("coordX")),
            "y": safe_float(coordinates.get("coordY")),
        }
        if hit
        else None,
    }


def _boxscore(value: Any) -> dict[str, Any]:
    teams = _mapping(_mapping(value).get("teams"))
    return {side: _boxscore_team(teams.get(side)) for side in ("away", "home")}


def _boxscore_team(value: Any) -> dict[str, Any]:
    team = _mapping(value)
    players = _mapping(team.get("players"))
    raw_batting_order = team.get("battingOrder")
    batting_order = raw_batting_order if isinstance(raw_batting_order, list) else []
    batters = [
        _player_line(players.get(f"ID{identifier}"), "batting") for identifier in batting_order[:15]
    ]
    raw_pitcher_ids = team.get("pitchers")
    pitcher_ids = raw_pitcher_ids if isinstance(raw_pitcher_ids, list) else []
    pitchers = [
        _player_line(players.get(f"ID{identifier}"), "pitching") for identifier in pitcher_ids[:10]
    ]
    return {
        "batting": [row for row in batters if row],
        "pitching": [row for row in pitchers if row],
    }


def _player_line(value: Any, group: str) -> dict[str, Any] | None:
    player = _mapping(value)
    person = _person(player.get("person"))
    if person is None:
        return None
    stats = _mapping(_mapping(player.get("stats")).get(group))
    return {
        "player": person,
        "position": _mapping(player.get("position")).get("abbreviation"),
        "stats": dict(stats),
    }

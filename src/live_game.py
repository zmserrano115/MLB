from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import pandas as pd

from src.api_client import get_json

BOXSCORE_URL = "https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore"
LIVE_FEED_URL = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
PLAYER_STATS_URL = "https://statsapi.mlb.com/api/v1/people/{player_id}/stats"
PLAYER_URL = "https://statsapi.mlb.com/api/v1/people/{player_id}"
PEOPLE_URL = "https://statsapi.mlb.com/api/v1/people"
SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
ROSTER_URL = "https://statsapi.mlb.com/api/v1/teams/{team_id}/roster"


def safe_int(value, default=0):
    value = pd.to_numeric(value, errors="coerce")
    if pd.isna(value):
        return default
    return int(value)


def safe_float(value, default=None):
    value = pd.to_numeric(value, errors="coerce")
    if pd.isna(value):
        return default
    return float(value)


def player_headshot_url(player_id, width=80):
    if player_id is None:
        return ""

    player_id = pd.to_numeric(player_id, errors="coerce")
    if pd.isna(player_id):
        return ""

    return (
        "https://img.mlbstatic.com/mlb-photos/image/upload/"
        f"w_{int(width)},d_people:generic:headshot:silo:current.png,"
        f"q_auto:best,f_auto/v1/people/{int(player_id)}/headshot/67/current"
    )


def _player_record(players, player_id):
    return players.get(f"ID{int(player_id)}", {})


def _ordered_player_ids(team_data, list_name, stat_group):
    players = team_data.get("players", {})
    ordered_ids = team_data.get(list_name) or []
    if ordered_ids:
        return ordered_ids

    fallback = []
    for key, player in players.items():
        if not key.startswith("ID"):
            continue
        stats = player.get("stats", {}).get(stat_group, {})
        if stats:
            fallback.append(safe_int(key.replace("ID", ""), default=None))
    return [player_id for player_id in fallback if player_id is not None]


def _plate_appearances(stat):
    return sum(
        safe_int(stat.get(column))
        for column in (
            "atBats",
            "baseOnBalls",
            "hitByPitch",
            "sacFlies",
            "sacBunts",
        )
    )


def _lineup_number(value):
    text = str(value or "").strip()
    if not text or not text[0].isdigit():
        return None
    return int(text[0])


def parse_game_boxscore(data):
    batting_rows = []
    pitching_rows = []

    for side in ("away", "home"):
        team_data = data.get("teams", {}).get(side, {})
        team = team_data.get("team", {})
        team_name = team.get("name")
        team_abbr = team.get("abbreviation") or team_name
        players = team_data.get("players", {})

        for player_id in _ordered_player_ids(team_data, "batters", "batting"):
            player = _player_record(players, player_id)
            person = player.get("person", {})
            stat = player.get("stats", {}).get("batting", {})
            season_stat = player.get("seasonStats", {}).get("batting", {})
            batting_rows.append(
                {
                    "player_id": person.get("id") or player_id,
                    "Headshot": player_headshot_url(person.get("id") or player_id),
                    "Player": person.get("fullName"),
                    "Team": team_abbr,
                    "team_name": team_name,
                    "Side": side.title(),
                    "Lineup": _lineup_number(player.get("battingOrder")),
                    "Pos": player.get("position", {}).get("abbreviation"),
                    "PA": _plate_appearances(stat),
                    "AB": safe_int(stat.get("atBats")),
                    "R": safe_int(stat.get("runs")),
                    "H": safe_int(stat.get("hits")),
                    "RBI": safe_int(stat.get("rbi")),
                    "BB": safe_int(stat.get("baseOnBalls")),
                    "SO": safe_int(stat.get("strikeOuts")),
                    "HR": safe_int(stat.get("homeRuns")),
                    "SB": safe_int(stat.get("stolenBases")),
                    "AVG": season_stat.get("avg"),
                    "OPS": season_stat.get("ops"),
                }
            )

        for player_id in _ordered_player_ids(team_data, "pitchers", "pitching"):
            player = _player_record(players, player_id)
            person = player.get("person", {})
            stat = player.get("stats", {}).get("pitching", {})
            season_stat = player.get("seasonStats", {}).get("pitching", {})
            pitch_count = safe_int(stat.get("pitchesThrown"))
            strikes = safe_int(stat.get("strikes"))
            pitching_rows.append(
                {
                    "player_id": person.get("id") or player_id,
                    "Headshot": player_headshot_url(person.get("id") or player_id),
                    "Player": person.get("fullName"),
                    "Team": team_abbr,
                    "team_name": team_name,
                    "Side": side.title(),
                    "IP": stat.get("inningsPitched") or "0.0",
                    "H": safe_int(stat.get("hits")),
                    "R": safe_int(stat.get("runs")),
                    "ER": safe_int(stat.get("earnedRuns")),
                    "BB": safe_int(stat.get("baseOnBalls")),
                    "SO": safe_int(stat.get("strikeOuts")),
                    "HR": safe_int(stat.get("homeRuns")),
                    "PC-ST": f"{pitch_count}-{strikes}" if pitch_count else "",
                    "Pitch Count": pitch_count,
                    "ERA": season_stat.get("era"),
                    "WHIP": season_stat.get("whip"),
                }
            )

    batting = pd.DataFrame(batting_rows)
    if not batting.empty:
        batting = batting.sort_values(
            ["Side", "Lineup", "PA", "Player"],
            ascending=[True, True, False, True],
            na_position="last",
        ).reset_index(drop=True)

    pitching = pd.DataFrame(pitching_rows)

    return {
        "batting": batting,
        "pitching": pitching,
    }


def get_game_boxscore(game_pk):
    data = get_json(
        BOXSCORE_URL.format(game_pk=int(game_pk)),
        provider="MLB StatsAPI",
        timeout=20,
    )
    return parse_game_boxscore(data)


def _live_player(player):
    player = player or {}
    player_id = player.get("id")
    return {
        "player_id": player_id,
        "name": player.get("fullName") or player.get("lastName") or "",
        "headshot": player_headshot_url(player_id),
    }


def _boxscore_lineup_lookup(boxscore):
    lookup = {}
    for side in ("away", "home"):
        players = (
            (boxscore.get("teams") or {})
            .get(side, {})
            .get("players", {})
        )
        for key, player in players.items():
            player_id = (
                (player.get("person") or {}).get("id")
                or safe_int(str(key).replace("ID", ""), default=None)
            )
            lineup_number = _lineup_number(player.get("battingOrder"))
            if player_id is not None and lineup_number is not None:
                lookup[int(player_id)] = lineup_number
    return lookup


def _boxscore_team_batting_summary(boxscore):
    summaries = {}
    for side in ("away", "home"):
        team_data = ((boxscore.get("teams") or {}).get(side) or {})
        team_stats = (team_data.get("teamStats") or {}).get("batting") or {}
        summaries[side] = {
            "at_bats": safe_int(team_stats.get("atBats")),
            "hits": safe_int(team_stats.get("hits")),
            "avg": team_stats.get("avg"),
            "obp": team_stats.get("obp"),
            "ops": team_stats.get("ops"),
            "strikeouts": safe_int(team_stats.get("strikeOuts")),
            "walks": safe_int(team_stats.get("baseOnBalls")),
            "home_runs": safe_int(team_stats.get("homeRuns")),
            "stolen_bases": safe_int(team_stats.get("stolenBases")),
        }
    return summaries


def _live_player_with_lineup(player, lineup_lookup):
    result = _live_player(player)
    player_id = result.get("player_id")
    if player_id is not None and int(player_id) in lineup_lookup:
        result["lineup_number"] = lineup_lookup[int(player_id)]
    return result


def _live_pitcher(player, boxscore):
    result = _live_player(player)
    player_id = result.get("player_id")
    if player_id is None:
        return result

    player_record = {}
    for side in ("away", "home"):
        players = (
            (boxscore.get("teams") or {})
            .get(side, {})
            .get("players", {})
        )
        player_record = players.get(f"ID{player_id}", {})
        if player_record:
            break

    game_stats = player_record.get("stats", {}).get("pitching", {})
    season_stats = player_record.get("seasonStats", {}).get("pitching", {})
    result.update(
        {
            "pitch_count": safe_int(game_stats.get("pitchesThrown")),
            "strikeouts": safe_int(game_stats.get("strikeOuts")),
            "hits_allowed": safe_int(game_stats.get("hits")),
            "era": game_stats.get("era") or season_stats.get("era"),
        }
    )
    return result


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


def classify_play_result(result):
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


def _pitch_count(event):
    count = (event or {}).get("count") or {}
    return {
        "balls": safe_int(count.get("balls")),
        "strikes": safe_int(count.get("strikes")),
        "outs": safe_int(count.get("outs")),
    }


def parse_pitch_event(event):
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


def annotate_pitch_counts(pitch_events):
    previous_count = None
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


def _play_runs_scored(play):
    runners = play.get("runners") or []
    return sum(
        1
        for runner in runners
        if (runner.get("details") or {}).get("isScoringEvent")
    )


def parse_live_play(play):
    play = play or {}
    result = play.get("result") or {}
    about = play.get("about") or {}
    matchup = play.get("matchup") or {}
    play_events = play.get("playEvents") or []
    pitch_events = [
        event
        for event in play_events
        if event.get("isPitch")
    ]
    parsed_pitch_events = annotate_pitch_counts(
        [parse_pitch_event(event) for event in pitch_events]
    )
    hit_data = next(
        (
            event.get("hitData")
            for event in reversed(play_events)
            if event.get("hitData")
        ),
        None,
    )
    parsed_hit_data = None
    if hit_data:
        coordinates = hit_data.get("coordinates") or {}
        parsed_hit_data = {
            "x": safe_float(coordinates.get("coordX")),
            "y": safe_float(coordinates.get("coordY")),
            "launch_speed": safe_float(hit_data.get("launchSpeed")),
            "launch_angle": safe_float(hit_data.get("launchAngle")),
            "distance": safe_float(hit_data.get("totalDistance")),
            "trajectory": hit_data.get("trajectory"),
            "hardness": hit_data.get("hardness"),
            "location": safe_int(hit_data.get("location"), default=None),
        }
    count_after = _pitch_count(pitch_events[-1]) if pitch_events else _pitch_count(play)
    count_before = (
        _pitch_count(pitch_events[-2])
        if len(pitch_events) > 1
        else {"balls": 0, "strikes": 0, "outs": count_after["outs"]}
    )
    result_type = classify_play_result(result)

    return {
        "play_index": about.get("atBatIndex"),
        "completed": bool(about.get("isComplete")),
        "inning": about.get("inning"),
        "half_inning": about.get("halfInning"),
        "batter": _live_player(matchup.get("batter")),
        "pitcher": _live_player(matchup.get("pitcher")),
        "result_type": result_type,
        "result_label": PLAY_RESULT_LABELS[result_type],
        "description": result.get("description") or result.get("event") or "",
        "count_before": count_before,
        "count_after": count_after,
        "runs_scored": _play_runs_scored(play),
        "away_score": result.get("awayScore"),
        "home_score": result.get("homeScore"),
        "is_scoring_play": bool(about.get("isScoringPlay")),
        "hit_data": parsed_hit_data,
        "pitches": parsed_pitch_events,
    }


def count_current_play_fouls(current_play):
    return sum(
        1
        for event in (current_play.get("playEvents") or [])
        if event.get("isPitch")
        and "foul"
        in " ".join(
            [
                str((event.get("details") or {}).get("description") or ""),
                str(
                    ((event.get("details") or {}).get("call") or {}).get(
                        "description"
                    )
                    or ""
                ),
            ]
        ).lower()
    )


def parse_live_game_feed(data):
    game_data = data.get("gameData", {})
    live_data = data.get("liveData", {})
    linescore = live_data.get("linescore", {})
    plays = live_data.get("plays", {})
    current_play = plays.get("currentPlay") or {}
    matchup = current_play.get("matchup", {})
    count = current_play.get("count") or {}
    offense = linescore.get("offense") or {}
    defense = linescore.get("defense") or {}
    boxscore = live_data.get("boxscore") or {}
    lineup_lookup = _boxscore_lineup_lookup(boxscore)
    batting_summary = _boxscore_team_batting_summary(boxscore)
    status = game_data.get("status", {})
    teams = game_data.get("teams", {})
    venue = game_data.get("venue") or {}
    field_info = venue.get("fieldInfo") or {}
    abs_challenges = game_data.get("absChallenges") or {}
    current_pitch_events = annotate_pitch_counts(
        [
            parse_pitch_event(event)
            for event in (current_play.get("playEvents") or [])
            if event.get("isPitch")
        ]
    )

    current_batter = matchup.get("batter") or offense.get("batter") or {}
    current_pitcher = matchup.get("pitcher") or defense.get("pitcher") or {}
    current_pitcher_info = _live_pitcher(current_pitcher, boxscore)
    pitch_hand = matchup.get("pitchHand") or current_pitcher.get("pitchHand") or {}
    if pitch_hand:
        current_pitcher_info["throwing_hand"] = (
            pitch_hand.get("code")
            or pitch_hand.get("description")
            or pitch_hand.get("abbreviation")
        )
    on_deck = offense.get("onDeck") or {}
    bases = {}
    for base_key, label in (
        ("first", "first"),
        ("second", "second"),
        ("third", "third"),
    ):
        runner = offense.get(base_key) or {}
        bases[label] = _live_player(runner) if runner else None

    completed_plays = [
        parse_live_play(play)
        for play in (plays.get("allPlays") or [])
        if (play.get("about") or {}).get("isComplete")
    ]
    for play in completed_plays:
        side = (
            "away"
            if str(play.get("half_inning") or "").lower() == "top"
            else "home"
        )
        team_name = (
            (teams.get("away", {}).get("name"))
            if side == "away"
            else (teams.get("home", {}).get("name"))
        )
        play["batting_side"] = side
        play["batting_team"] = team_name
    recent_plays = completed_plays[-8:]
    contact_plays = [play for play in completed_plays if play.get("hit_data")]
    latest_batted_ball = contact_plays[-1] if contact_plays else None
    current_pitches = current_pitch_events

    challenge_teams = {}
    for side in ("away", "home"):
        challenge_data = abs_challenges.get(side) or {}
        challenge_teams[side] = {
            "remaining": safe_int(challenge_data.get("remaining")),
            "successful": safe_int(challenge_data.get("usedSuccessful")),
            "failed": safe_int(challenge_data.get("usedFailed")),
        }

    return {
        "game_pk": game_data.get("game", {}).get("pk"),
        "abstract_state": status.get("abstractGameState"),
        "detailed_state": status.get("detailedState"),
        "inning": linescore.get("currentInning"),
        "inning_ordinal": linescore.get("currentInningOrdinal"),
        "inning_state": linescore.get("inningState")
        or linescore.get("inningHalf"),
        "away_score": linescore.get("teams", {}).get("away", {}).get("runs"),
        "home_score": linescore.get("teams", {}).get("home", {}).get("runs"),
        "away_team": teams.get("away", {}).get("name"),
        "away_team_id": teams.get("away", {}).get("id"),
        "home_team": teams.get("home", {}).get("name"),
        "home_team_id": teams.get("home", {}).get("id"),
        "venue_name": venue.get("name"),
        "field_dimensions": {
            "left_line": safe_int(field_info.get("leftLine"), default=None),
            "left": safe_int(field_info.get("left"), default=None),
            "left_center": safe_int(
                field_info.get("leftCenter"),
                default=None,
            ),
            "center": safe_int(field_info.get("center"), default=None),
            "right_center": safe_int(
                field_info.get("rightCenter"),
                default=None,
            ),
            "right": safe_int(field_info.get("right"), default=None),
            "right_line": safe_int(
                field_info.get("rightLine"),
                default=None,
            ),
        },
        "abs_challenges": {
            "enabled": bool(abs_challenges.get("hasChallenges")),
            **challenge_teams,
        },
        "balls": safe_int(count.get("balls")),
        "strikes": safe_int(count.get("strikes")),
        "outs": safe_int(count.get("outs")),
        "fouls": count_current_play_fouls(current_play),
        "current_pitches": current_pitches[-12:],
        "latest_pitch": current_pitches[-1] if current_pitches else None,
        "current_batter": _live_player_with_lineup(current_batter, lineup_lookup),
        "current_pitcher": current_pitcher_info,
        "on_deck": _live_player_with_lineup(on_deck, lineup_lookup),
        "bases": bases,
        "completed_plays": completed_plays,
        "recent_plays": recent_plays,
        "contact_plays": contact_plays,
        "latest_completed_play": recent_plays[-1] if recent_plays else None,
        "latest_batted_ball": latest_batted_ball,
        "team_batting_summary": batting_summary,
        "feed_timestamp": (data.get("metaData") or {}).get("timeStamp"),
    }


def get_live_game_feed(game_pk):
    data = get_json(
        LIVE_FEED_URL.format(game_pk=int(game_pk)),
        provider="MLB StatsAPI",
        timeout=20,
    )
    return parse_live_game_feed(data)


def parse_player_profile(data):
    people = data.get("people", [])
    person = people[0] if people else {}
    current_team = person.get("currentTeam") or {}
    position = person.get("primaryPosition") or {}
    player_id = person.get("id")
    return {
        "player_id": player_id,
        "name": person.get("fullName"),
        "team_id": current_team.get("id"),
        "team": current_team.get("name"),
        "position": position.get("abbreviation") or position.get("name"),
        "position_name": position.get("name"),
        "headshot": player_headshot_url(player_id, width=180),
    }


def get_player_profile(player_id):
    data = get_json(
        PLAYER_URL.format(player_id=int(player_id)),
        params={"hydrate": "currentTeam"},
        provider="MLB StatsAPI",
        timeout=20,
    )
    return parse_player_profile(data)


def parse_player_game_log(data, group):
    rows = []
    for split in data.get("stats", [{}])[0].get("splits", []):
        stat = split.get("stat", {})
        row = {
            "game_pk": split.get("game", {}).get("gamePk"),
            "game_date": split.get("date"),
            "opponent": split.get("opponent", {}).get("name"),
            "opponent_id": split.get("opponent", {}).get("id"),
            "team": split.get("team", {}).get("abbreviation")
            or split.get("team", {}).get("name"),
            "home_away": "Home" if split.get("isHome") else "Away",
        }
        if group == "pitching":
            row.update(
                {
                    "IP": stat.get("inningsPitched"),
                    "GS": safe_int(stat.get("gamesStarted")),
                    "Pitch Count": safe_int(stat.get("numberOfPitches")),
                    "BF": safe_int(stat.get("battersFaced")),
                    "SO": safe_int(stat.get("strikeOuts")),
                    "H": safe_int(stat.get("hits")),
                    "R": safe_int(stat.get("runs")),
                    "ER": safe_int(stat.get("earnedRuns")),
                    "BB": safe_int(stat.get("baseOnBalls")),
                    "HBP": safe_int(stat.get("hitBatsmen")),
                    "HR": safe_int(stat.get("homeRuns")),
                }
            )
        else:
            pa = safe_int(stat.get("plateAppearances"))
            ab = safe_int(stat.get("atBats"))
            hits = safe_int(stat.get("hits"))
            walks = safe_int(stat.get("baseOnBalls"))
            hbp = safe_int(stat.get("hitByPitch"))
            sac_flies = safe_int(stat.get("sacFlies"))
            total_bases = safe_int(stat.get("totalBases"))
            denominator = ab + walks + hbp + sac_flies
            obp = (hits + walks + hbp) / denominator if denominator else None
            slg = total_bases / ab if ab else None
            row.update(
                {
                    "PA": pa,
                    "AB": ab,
                    "H": hits,
                    "TB": total_bases,
                    "BB": walks,
                    "HBP": hbp,
                    "HR": safe_int(stat.get("homeRuns")),
                    "RBI": safe_int(stat.get("rbi")),
                    "R": safe_int(stat.get("runs")),
                    "SB": safe_int(stat.get("stolenBases")),
                    "SO": safe_int(stat.get("strikeOuts")),
                    "AVG": round(hits / ab, 3) if ab else None,
                    "OBP": round(obp, 3) if obp is not None else None,
                    "SLG": round(slg, 3) if slg is not None else None,
                    "OPS": (
                        round(obp + slg, 3)
                        if obp is not None and slg is not None
                        else None
                    ),
                    "K%": (
                        round((safe_int(stat.get("strikeOuts")) / pa) * 100, 2)
                        if pa
                        else None
                    ),
                    "BB%": round((walks / pa) * 100, 2) if pa else None,
                }
            )
        rows.append(row)

    return pd.DataFrame(rows)


def get_player_game_log(player_id, group, season):
    data = get_json(
        PLAYER_STATS_URL.format(player_id=int(player_id)),
        params={
            "stats": "gameLog",
            "group": group,
            "season": int(season),
            "sportIds": 1,
        },
        provider="MLB StatsAPI",
        timeout=20,
    )
    return parse_player_game_log(data, group)


def get_people_game_logs(player_ids, group, season):
    clean_ids = []
    for player_id in player_ids:
        player_id = pd.to_numeric(player_id, errors="coerce")
        if pd.notna(player_id):
            clean_ids.append(int(player_id))

    clean_ids = list(dict.fromkeys(clean_ids))
    if not clean_ids:
        return pd.DataFrame()

    def load_chunk(chunk):
        data = get_json(
            PEOPLE_URL,
            params={
                "personIds": ",".join(str(player_id) for player_id in chunk),
                "hydrate": (
                    f"stats(group=[{group}],type=[gameLog],season={int(season)})"
                ),
                "sportIds": 1,
            },
            provider="MLB StatsAPI",
            timeout=60,
        )

        frames = []
        for person in data.get("people", []):
            frame = parse_player_game_log(
                {"stats": person.get("stats", [])},
                group,
            )
            if frame.empty:
                continue
            frame["player_id"] = person.get("id")
            frames.append(frame)
        return frames

    chunks = [
        clean_ids[offset : offset + 25]
        for offset in range(0, len(clean_ids), 25)
    ]
    frames = []
    with ThreadPoolExecutor(max_workers=min(8, len(chunks))) as executor:
        futures = [executor.submit(load_chunk, chunk) for chunk in chunks]
        for future in as_completed(futures):
            frames.extend(future.result())

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def get_people_career_game_logs(
    player_ids,
    group,
    through_date,
    start_date="2005-01-01",
):
    clean_ids = []
    for player_id in player_ids:
        player_id = pd.to_numeric(player_id, errors="coerce")
        if pd.notna(player_id):
            clean_ids.append(int(player_id))
    clean_ids = list(dict.fromkeys(clean_ids))
    if not clean_ids:
        return pd.DataFrame()

    def load_chunk(chunk):
        data = get_json(
            PEOPLE_URL,
            params={
                "personIds": ",".join(str(player_id) for player_id in chunk),
                "hydrate": (
                    f"stats(group=[{group}],type=[gameLog],"
                    f"startDate={start_date},endDate={through_date})"
                ),
                "sportIds": 1,
            },
            provider="MLB StatsAPI",
            timeout=90,
        )
        frames = []
        for person in data.get("people", []):
            frame = parse_player_game_log(
                {"stats": person.get("stats", [])},
                group,
            )
            if frame.empty:
                continue
            frame["player_id"] = person.get("id")
            frames.append(frame)
        return frames

    chunks = [
        clean_ids[offset : offset + 5]
        for offset in range(0, len(clean_ids), 5)
    ]
    frames = []
    with ThreadPoolExecutor(max_workers=min(6, len(chunks))) as executor:
        futures = [executor.submit(load_chunk, chunk) for chunk in chunks]
        for future in as_completed(futures):
            frames.extend(future.result())
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def parse_team_schedule_results(data):
    rows = []
    for day in data.get("dates", []):
        for game in day.get("games", []):
            status = game.get("status", {})
            if not is_final_state(
                status.get("abstractGameState"),
                status.get("detailedState"),
            ):
                continue
            teams = game.get("teams", {})
            away = teams.get("away", {})
            home = teams.get("home", {})
            away_team = away.get("team", {})
            home_team = home.get("team", {})
            away_score = safe_int(away.get("score"), default=None)
            home_score = safe_int(home.get("score"), default=None)
            if away_score is None or home_score is None or away_score == home_score:
                continue
            rows.append(
                {
                    "game_pk": game.get("gamePk"),
                    "game_date": game.get("gameDate") or day.get("date"),
                    "away_team_id": away_team.get("id"),
                    "away_team": away_team.get("name"),
                    "away_team_abbr": away_team.get("abbreviation"),
                    "away_score": away_score,
                    "home_team_id": home_team.get("id"),
                    "home_team": home_team.get("name"),
                    "home_team_abbr": home_team.get("abbreviation"),
                    "home_score": home_score,
                    "winner_team_id": (
                        away_team.get("id")
                        if away_score > home_score
                        else home_team.get("id")
                    ),
                }
            )
    return pd.DataFrame(rows)


def get_season_team_results(season, through_date):
    data = get_json(
        SCHEDULE_URL,
        params={
            "sportId": 1,
            "gameType": "R",
            "startDate": f"{int(season)}-03-01",
            "endDate": str(through_date),
            "hydrate": "team",
        },
        provider="MLB StatsAPI",
        timeout=30,
    )
    return parse_team_schedule_results(data)


def get_game_results(game_pks):
    clean_game_pks = []
    for game_pk in game_pks:
        game_pk = pd.to_numeric(game_pk, errors="coerce")
        if pd.notna(game_pk):
            clean_game_pks.append(int(game_pk))
    clean_game_pks = list(dict.fromkeys(clean_game_pks))
    if not clean_game_pks:
        return pd.DataFrame()

    frames = []
    for offset in range(0, len(clean_game_pks), 100):
        chunk = clean_game_pks[offset : offset + 100]
        data = get_json(
            SCHEDULE_URL,
            params={
                "sportId": 1,
                "gamePks": ",".join(str(game_pk) for game_pk in chunk),
                "hydrate": "team",
            },
            provider="MLB StatsAPI",
            timeout=45,
        )
        frame = parse_team_schedule_results(data)
        if not frame.empty:
            frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def parse_team_roster(data, team_id=None, team_name=None, team_abbr=None):
    rows = []
    for entry in data.get("roster", []):
        person = entry.get("person") or {}
        position = entry.get("position") or {}
        player_id = person.get("id")
        position_abbr = position.get("abbreviation")
        rows.append(
            {
                "player_id": player_id,
                "Player": person.get("fullName"),
                "team_id": team_id,
                "team_name": team_name,
                "Team": team_abbr or team_name,
                "Position": position_abbr or position.get("name"),
                "group": (
                    "pitching"
                    if position_abbr == "P" or position.get("type") == "Pitcher"
                    else "batting"
                ),
                "status": (entry.get("status") or {}).get("description"),
            }
        )
    return pd.DataFrame(rows)


def get_active_team_rosters(team_records, roster_date):
    records = [
        {
            "team_id": safe_int(record[0], default=None),
            "team_name": record[1],
            "team_abbr": record[2],
        }
        for record in team_records
        if record and safe_int(record[0], default=None) is not None
    ]
    if not records:
        return pd.DataFrame()

    def load_team(record):
        data = get_json(
            ROSTER_URL.format(team_id=record["team_id"]),
            params={
                "rosterType": "active",
                "date": str(roster_date),
                "hydrate": "person",
            },
            provider="MLB StatsAPI",
            timeout=30,
        )
        return parse_team_roster(
            data,
            team_id=record["team_id"],
            team_name=record["team_name"],
            team_abbr=record["team_abbr"],
        )

    frames = []
    with ThreadPoolExecutor(max_workers=min(8, len(records))) as executor:
        futures = [executor.submit(load_team, record) for record in records]
        for future in as_completed(futures):
            frame = future.result()
            if not frame.empty:
                frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def calculate_team_win_streak(results_df, team_id):
    if results_df is None or results_df.empty:
        return 0

    team_id = safe_int(team_id, default=None)
    if team_id is None:
        return 0
    games = results_df[
        (pd.to_numeric(results_df.get("away_team_id"), errors="coerce") == team_id)
        | (pd.to_numeric(results_df.get("home_team_id"), errors="coerce") == team_id)
    ].copy()
    if games.empty:
        return 0
    games["_date"] = pd.to_datetime(games.get("game_date"), errors="coerce")
    games = games.sort_values(
        ["_date", "game_pk"],
        ascending=[False, False],
        na_position="last",
    )

    streak = 0
    for winner_team_id in games.get("winner_team_id", pd.Series(dtype=float)):
        if safe_int(winner_team_id, default=None) != team_id:
            break
        streak += 1
    return streak


def _normalized_team_values(*values):
    return {
        str(value).strip().casefold()
        for value in values
        if value is not None and str(value).strip()
    }


def calculate_team_record_vs_pitcher(
    results_df,
    pitcher_logs,
    team_id,
    pitcher_id,
):
    if (
        results_df is None
        or results_df.empty
        or pitcher_logs is None
        or pitcher_logs.empty
    ):
        return {"wins": 0, "losses": 0, "games": 0}

    team_id = safe_int(team_id, default=None)
    pitcher_id = safe_int(pitcher_id, default=None)
    if team_id is None or pitcher_id is None:
        return {"wins": 0, "losses": 0, "games": 0}

    logs = pitcher_logs.copy()
    if "player_id" in logs.columns:
        logs = logs[
            pd.to_numeric(logs["player_id"], errors="coerce") == pitcher_id
        ]
    if logs.empty or "game_pk" not in logs.columns:
        return {"wins": 0, "losses": 0, "games": 0}

    results = results_df.copy()
    results["game_pk"] = pd.to_numeric(results["game_pk"], errors="coerce")
    results = results.dropna(subset=["game_pk"]).set_index("game_pk")
    wins = 0
    losses = 0

    for _, log in logs.iterrows():
        game_pk = pd.to_numeric(log.get("game_pk"), errors="coerce")
        if pd.isna(game_pk) or int(game_pk) not in results.index:
            continue
        game = results.loc[int(game_pk)]
        if isinstance(game, pd.DataFrame):
            game = game.iloc[0]

        if safe_int(game.get("away_team_id"), default=None) == team_id:
            target_values = _normalized_team_values(
                game.get("away_team"),
                game.get("away_team_abbr"),
            )
        elif safe_int(game.get("home_team_id"), default=None) == team_id:
            target_values = _normalized_team_values(
                game.get("home_team"),
                game.get("home_team_abbr"),
            )
        else:
            continue

        log_opponent_id = safe_int(log.get("opponent_id"), default=None)
        if log_opponent_id is not None:
            if log_opponent_id != team_id:
                continue
        else:
            log_opponent = str(log.get("opponent") or "").strip().casefold()
            if log_opponent and log_opponent not in target_values:
                continue
        games_started = pd.to_numeric(log.get("GS"), errors="coerce")
        if pd.notna(games_started) and games_started < 1:
            continue
        if safe_int(game.get("winner_team_id"), default=None) == team_id:
            wins += 1
        else:
            losses += 1

    return {"wins": wins, "losses": losses, "games": wins + losses}


def is_final_state(game_state, detailed_state=None):
    values = {str(game_state or "").lower(), str(detailed_state or "").lower()}
    return "final" in values or any("final" in value for value in values)


def count_historical_streak(game_log_df, stat_column, threshold, skip_date=None):
    if game_log_df is None or game_log_df.empty or stat_column not in game_log_df:
        return 0

    logs = game_log_df.copy()
    logs["parsed_date"] = pd.to_datetime(logs["game_date"], errors="coerce")
    logs = logs.dropna(subset=["parsed_date"])
    if skip_date is not None:
        skip_date = pd.to_datetime(skip_date).date()
        logs = logs[logs["parsed_date"].dt.date != skip_date]
    logs = logs.sort_values("parsed_date", ascending=False)

    streak = 0
    for _, row in logs.iterrows():
        value = pd.to_numeric(row.get(stat_column), errors="coerce")
        if pd.notna(value) and float(value) >= threshold:
            streak += 1
            continue
        break
    return streak


def calculate_live_streak(
    game_log_df,
    stat_column,
    threshold,
    current_value=None,
    current_game_state=None,
    detailed_state=None,
    selected_date=None,
    live_played=False,
):
    current_value = pd.to_numeric(current_value, errors="coerce")
    has_current_value = pd.notna(current_value)
    skip_date = selected_date if has_current_value or live_played else None
    base_streak = count_historical_streak(
        game_log_df,
        stat_column,
        threshold,
        skip_date=skip_date,
    )

    if has_current_value and float(current_value) >= threshold:
        return {
            "streak": base_streak + 1,
            "today_value": float(current_value),
            "status": (
                "Final +1"
                if is_final_state(current_game_state, detailed_state)
                else "Live +1"
            ),
        }

    if live_played and is_final_state(current_game_state, detailed_state):
        return {
            "streak": 0,
            "today_value": float(current_value) if has_current_value else 0,
            "status": "Ended",
        }

    if live_played:
        return {
            "streak": base_streak,
            "today_value": float(current_value) if has_current_value else 0,
            "status": "In progress",
        }

    if isinstance(selected_date, date):
        status = "Pre-game"
    else:
        status = "Pending"
    return {
        "streak": base_streak,
        "today_value": float(current_value) if has_current_value else None,
        "status": status,
    }

import argparse
from collections import defaultdict
import csv
import hashlib
import io
import os
from pathlib import Path
import tempfile
import time
import zipfile

import requests

from src import database
from src.team_mappings import retrosheet_team_name


RETROSHEET_ARCHIVE_URL = (
    "https://www.retrosheet.org/downloads/{season}/{season}csvs.zip"
)
CHADWICK_URL = (
    "https://raw.githubusercontent.com/chadwickbureau/register/"
    "master/data/people-{suffix}.csv"
)
CHADWICK_SUFFIXES = "0123456789abcdef"
SOURCE = "retrosheet"


def safe_int(value, default=0):
    try:
        if value is None or str(value).strip() == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def format_date(value):
    text = str(value or "").strip()
    if len(text) != 8:
        return text
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}"


def outs_to_baseball_ip(outs):
    outs = safe_int(outs)
    return (outs // 3) + (outs % 3) / 10.0


def synthetic_game_pk(retrosheet_game_id):
    digest = hashlib.blake2b(
        retrosheet_game_id.encode("ascii"),
        digest_size=8,
    ).digest()
    value = int.from_bytes(digest, "big") & 0x7FFFFFFFFFFFFFFF
    return -(value or 1)


def create_http_session():
    session = requests.Session()
    session.headers.update(
        {"User-Agent": "all-rise-analytics-retrosheet-import/1.0"}
    )
    return session


def iter_chadwick_rows(session=None, chadwick_dir=None):
    if chadwick_dir:
        base_dir = Path(chadwick_dir)
        for suffix in CHADWICK_SUFFIXES:
            file_path = base_dir / f"people-{suffix}.csv"
            with file_path.open("r", encoding="utf-8-sig", newline="") as handle:
                yield from csv.DictReader(handle)
        return

    session = session or create_http_session()
    for suffix in CHADWICK_SUFFIXES:
        response = session.get(CHADWICK_URL.format(suffix=suffix), timeout=60)
        response.raise_for_status()
        handle = io.StringIO(response.text)
        yield from csv.DictReader(handle)


def load_chadwick_mapping(session=None, chadwick_dir=None):
    mapping = {}
    for row in iter_chadwick_rows(session=session, chadwick_dir=chadwick_dir):
        retro_id = str(row.get("key_retro") or "").strip()
        mlbam_id = safe_int(row.get("key_mlbam"), default=None)
        if not retro_id or mlbam_id is None:
            continue

        name = " ".join(
            part
            for part in [
                str(row.get("name_first") or "").strip(),
                str(row.get("name_last") or "").strip(),
            ]
            if part
        )
        if not name:
            name = str(row.get("name_given") or "").strip()

        mapping[retro_id] = {
            "player_id": mlbam_id,
            "retro_id": retro_id,
            "player_name": name or None,
        }
    return mapping


def download_season_archive(season, destination, session=None):
    session = session or create_http_session()
    url = RETROSHEET_ARCHIVE_URL.format(season=season)
    with session.get(url, stream=True, timeout=120) as response:
        response.raise_for_status()
        with Path(destination).open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)


def _member_name(archive, season, file_type):
    expected = f"{season}{file_type}.csv".lower()
    for name in archive.namelist():
        if Path(name).name.lower() == expected:
            return name
    raise FileNotFoundError(f"{expected} was not found in the Retrosheet archive.")


def _csv_rows(archive, member_name):
    binary_handle = archive.open(member_name)
    text_handle = io.TextIOWrapper(binary_handle, encoding="utf-8-sig", newline="")
    try:
        yield from csv.DictReader(text_handle)
    finally:
        text_handle.close()


def parse_retrosheet_archive(archive_path, season, chadwick_mapping):
    games_by_gid = {}
    bvp_groups = defaultdict(
        lambda: {
            "PA": 0,
            "AB": 0,
            "H": 0,
            "doubles": 0,
            "triples": 0,
            "BB": 0,
            "HBP": 0,
            "SO": 0,
            "HR": 0,
            "RBI": 0,
            "SF": 0,
            "TB": 0,
        }
    )
    pitch_counts = defaultdict(int)
    pitch_count_seen = set()
    pa_by_game = defaultdict(int)
    pitcher_logs_by_game = defaultdict(int)
    used_player_ids = set()
    source_plate_appearances = 0
    skipped_unmapped_plate_appearances = 0
    skipped_unmapped_pitchers = 0

    with zipfile.ZipFile(archive_path) as archive:
        gameinfo_name = _member_name(archive, season, "gameinfo")
        plays_name = _member_name(archive, season, "plays")
        pitching_name = _member_name(archive, season, "pitching")

        for row in _csv_rows(archive, gameinfo_name):
            if str(row.get("gametype") or "").lower() != "regular":
                continue

            gid = row["gid"]
            game_pk = synthetic_game_pk(gid)
            games_by_gid[gid] = {
                "game_pk": game_pk,
                "game_id": f"retro:{gid}",
                "retrosheet_game_id": gid,
                "source": SOURCE,
                "game_date": format_date(row.get("date")),
                "season": season,
                "away_team": retrosheet_team_name(row.get("visteam")),
                "home_team": retrosheet_team_name(row.get("hometeam")),
                "away_team_id": None,
                "home_team_id": None,
                "away_probable_pitcher": None,
                "away_probable_pitcher_id": None,
                "home_probable_pitcher": None,
                "home_probable_pitcher_id": None,
                "game_status": "Final",
            }

        for row in _csv_rows(archive, plays_name):
            gid = row.get("gid")
            game = games_by_gid.get(gid)
            if game is None:
                continue

            pitcher = chadwick_mapping.get(str(row.get("pitcher") or "").strip())
            num_pitches = safe_int(row.get("nump"), default=None)
            if pitcher and num_pitches is not None:
                pitch_key = (gid, pitcher["player_id"])
                pitch_counts[pitch_key] += num_pitches
                pitch_count_seen.add(pitch_key)

            if safe_int(row.get("pa")) != 1:
                continue

            source_plate_appearances += 1
            batter = chadwick_mapping.get(str(row.get("batter") or "").strip())
            if batter is None or pitcher is None:
                skipped_unmapped_plate_appearances += 1
                continue

            batter_id = batter["player_id"]
            pitcher_id = pitcher["player_id"]
            batting_team = retrosheet_team_name(row.get("batteam"))
            pitching_team = retrosheet_team_name(row.get("pitteam"))
            key = (
                gid,
                batter_id,
                pitcher_id,
                batting_team,
                pitching_team,
            )
            group = bvp_groups[key]

            singles = safe_int(row.get("single"))
            doubles = safe_int(row.get("double"))
            triples = safe_int(row.get("triple"))
            home_runs = safe_int(row.get("hr"))

            group["PA"] += 1
            group["AB"] += safe_int(row.get("ab"))
            group["H"] += singles + doubles + triples + home_runs
            group["doubles"] += doubles
            group["triples"] += triples
            group["BB"] += safe_int(row.get("walk"))
            group["HBP"] += safe_int(row.get("hbp"))
            group["SO"] += safe_int(row.get("k"))
            group["HR"] += home_runs
            group["RBI"] += safe_int(row.get("rbi"))
            group["SF"] += safe_int(row.get("sf"))
            group["TB"] += singles + 2 * doubles + 3 * triples + 4 * home_runs

            pa_by_game[gid] += 1
            used_player_ids.update([batter_id, pitcher_id])

        pitcher_logs = []
        for row in _csv_rows(archive, pitching_name):
            if (
                str(row.get("gametype") or "").lower() != "regular"
                or str(row.get("stattype") or "").lower() != "value"
            ):
                continue

            gid = row.get("gid")
            game = games_by_gid.get(gid)
            if game is None:
                continue

            player = chadwick_mapping.get(str(row.get("id") or "").strip())
            if player is None:
                skipped_unmapped_pitchers += 1
                continue

            pitcher_id = player["player_id"]
            pitch_key = (gid, pitcher_id)
            ip_outs = safe_int(row.get("p_ipouts"))
            pitcher_logs.append(
                {
                    "game_pk": game["game_pk"],
                    "game_id": game["game_id"],
                    "source": SOURCE,
                    "game_date": game["game_date"],
                    "season": season,
                    "pitcher_id": pitcher_id,
                    "pitcher_name": player["player_name"],
                    "team": retrosheet_team_name(row.get("team")),
                    "opponent": retrosheet_team_name(row.get("opp")),
                    "is_starter": safe_int(row.get("p_gs")),
                    "IP_outs": ip_outs,
                    "IP": outs_to_baseball_ip(ip_outs),
                    "pitch_count": (
                        pitch_counts[pitch_key]
                        if pitch_key in pitch_count_seen
                        else None
                    ),
                    "BF": safe_int(row.get("p_bfp")),
                    "H": safe_int(row.get("p_h")),
                    "BB": safe_int(row.get("p_w")),
                    "HBP": safe_int(row.get("p_hbp")),
                    "SO": safe_int(row.get("p_k")),
                    "HR": safe_int(row.get("p_hr")),
                    "R": safe_int(row.get("p_r")),
                    "ER": safe_int(row.get("p_er")),
                }
            )
            pitcher_logs_by_game[gid] += 1
            used_player_ids.add(pitcher_id)

    batter_pitcher_logs = []
    for key, values in bvp_groups.items():
        gid, batter_id, pitcher_id, batting_team, pitching_team = key
        game = games_by_gid[gid]
        batter_pitcher_logs.append(
            {
                "game_pk": game["game_pk"],
                "game_id": game["game_id"],
                "source": SOURCE,
                "game_date": game["game_date"],
                "season": season,
                "batter_id": batter_id,
                "pitcher_id": pitcher_id,
                "batting_team": batting_team,
                "pitching_team": pitching_team,
                **values,
            }
        )

    players_by_id = {
        player["player_id"]: player for player in chadwick_mapping.values()
    }
    players = [
        players_by_id[player_id]
        for player_id in sorted(used_player_ids)
        if player_id in players_by_id
    ]
    processed_games = [
        {
            "game_pk": game["game_pk"],
            "game_id": game["game_id"],
            "game_date": game["game_date"],
            "plate_appearances_loaded": pa_by_game[gid],
            "pitcher_logs_loaded": pitcher_logs_by_game[gid],
        }
        for gid, game in games_by_gid.items()
    ]

    return {
        "games": list(games_by_gid.values()),
        "players": players,
        "batter_pitcher_logs": batter_pitcher_logs,
        "pitcher_logs": pitcher_logs,
        "processed_games": processed_games,
        "source_plate_appearances": source_plate_appearances,
        "skipped_unmapped_plate_appearances": skipped_unmapped_plate_appearances,
        "skipped_unmapped_pitchers": skipped_unmapped_pitchers,
    }


def import_season(season, chadwick_mapping, archive_path=None, session=None):
    session = session or create_http_session()
    temporary_directory = None

    if archive_path is None:
        temporary_directory = tempfile.TemporaryDirectory(
            prefix=f"retrosheet-{season}-"
        )
        archive_path = Path(temporary_directory.name) / f"{season}csvs.zip"
        print(f"Downloading Retrosheet {season}...")
        download_season_archive(season, archive_path, session=session)
    else:
        archive_path = Path(archive_path)

    try:
        print(f"Parsing Retrosheet {season}...")
        parsed = parse_retrosheet_archive(
            archive_path=archive_path,
            season=season,
            chadwick_mapping=chadwick_mapping,
        )

        database.replace_retrosheet_season(
            season=season,
            games=parsed["games"],
            players=parsed["players"],
            batter_pitcher_logs=parsed["batter_pitcher_logs"],
            pitcher_logs=parsed["pitcher_logs"],
            processed_games=parsed["processed_games"],
        )
        return parsed
    finally:
        if temporary_directory is not None:
            temporary_directory.cleanup()


def backfill_seasons(
    start_season,
    end_season,
    chadwick_dir=None,
    archive_dir=None,
    sleep_seconds=0.25,
):
    if start_season > end_season:
        raise ValueError("start_season must be less than or equal to end_season.")

    database.init_database()
    session = create_http_session()
    print("Loading Chadwick Retrosheet-to-MLBAM mapping...")
    chadwick_mapping = load_chadwick_mapping(
        session=session,
        chadwick_dir=chadwick_dir,
    )
    print(f"Mapped Retrosheet IDs: {len(chadwick_mapping):,}")

    totals = defaultdict(int)
    failures = []

    for season in range(start_season, end_season + 1):
        try:
            archive_path = None
            if archive_dir:
                archive_path = Path(archive_dir) / f"{season}csvs.zip"

            parsed = import_season(
                season=season,
                chadwick_mapping=chadwick_mapping,
                archive_path=archive_path,
                session=session,
            )

            for key in [
                "source_plate_appearances",
                "skipped_unmapped_plate_appearances",
                "skipped_unmapped_pitchers",
            ]:
                totals[key] += parsed[key]
            totals["games"] += len(parsed["games"])
            totals["batter_pitcher_logs"] += len(parsed["batter_pitcher_logs"])
            totals["pitcher_logs"] += len(parsed["pitcher_logs"])

            print(
                f"Imported {season}: {len(parsed['games']):,} games, "
                f"{len(parsed['batter_pitcher_logs']):,} BvP game rows, "
                f"{len(parsed['pitcher_logs']):,} pitcher game rows."
            )
            time.sleep(sleep_seconds)
        except Exception as error:
            failures.append((season, str(error)))
            print(f"ERROR importing {season}: {error}")

    print("Rebuilding career and season summaries...")
    database.rebuild_all_summary_stats()

    status = "success" if not failures else "completed_with_errors"
    message = (
        f"Seasons {start_season}-{end_season}; "
        f"games={totals['games']}; "
        f"bvp_game_logs={totals['batter_pitcher_logs']}; "
        f"pitcher_game_logs={totals['pitcher_logs']}; "
        f"unmapped_pa={totals['skipped_unmapped_plate_appearances']}; "
        f"failures={len(failures)}"
    )
    database.log_refresh(
        refresh_type="retrosheet_backfill",
        refresh_date=f"{start_season}-{end_season}",
        games_checked=totals["games"],
        games_processed=totals["games"],
        plate_appearances_loaded=totals["source_plate_appearances"],
        pitcher_logs_loaded=totals["pitcher_logs"],
        status=status,
        message=message,
    )
    print(message)
    if failures:
        print("Failed seasons:")
        for season, error in failures:
            print(f"  {season}: {error}")
    database.print_database_counts()

    return failures


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Backfill aggregate MLB history from Retrosheet yearly CSV archives "
            "using Chadwick Retrosheet-to-MLBAM player ID mapping."
        )
    )
    parser.add_argument("--start-season", type=int, default=2005)
    parser.add_argument("--end-season", type=int, default=2025)
    parser.add_argument(
        "--chadwick-dir",
        help="Optional directory containing people-0.csv through people-f.csv.",
    )
    parser.add_argument(
        "--archive-dir",
        help="Optional directory containing predownloaded YYYYcsvs.zip files.",
    )
    parser.add_argument(
        "--db",
        help="Optional SQLite path. Defaults to data/mlb.db.",
    )
    parser.add_argument("--sleep-seconds", type=float, default=0.25)
    args = parser.parse_args()

    # This command creates the release database, so it must not try to
    # bootstrap from that release before it exists.
    os.environ["MLB_DB_SKIP_BOOTSTRAP"] = "1"
    if args.db:
        database.DB_PATH = Path(args.db).expanduser().resolve()

    failures = backfill_seasons(
        start_season=args.start_season,
        end_season=args.end_season,
        chadwick_dir=args.chadwick_dir,
        archive_dir=args.archive_dir,
        sleep_seconds=args.sleep_seconds,
    )
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

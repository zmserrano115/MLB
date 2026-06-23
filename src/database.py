from contextlib import contextmanager
from datetime import datetime
import gzip
import os
from pathlib import Path
import sqlite3
from threading import Lock
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from src.matchup_grading import grade_hitter_matchup


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "mlb.db"
DEFAULT_DB_URL = (
    "https://github.com/zmserrano115/MLB/"
    "releases/download/mlb-data/mlb.db.gz"
)
FALLBACK_DB_URL = (
    "https://github.com/zmserrano115/MLB/"
    "releases/download/mlb-data/mlb.db"
)
DB_PATH = Path(os.environ.get("MLB_DB_PATH", DEFAULT_DB_PATH))
SCHEMA_VERSION = 2
_INITIALIZED_PATH = None
_BOOTSTRAP_LOCK = Lock()
_INITIALIZE_LOCK = Lock()


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _download_database(database_url, temporary_path):
    request = urllib.request.Request(
        database_url,
        headers={"User-Agent": "all-rise-analytics/1.0"},
    )
    with urllib.request.urlopen(request, timeout=600) as response:
        source = (
            gzip.GzipFile(fileobj=response)
            if urlparse(database_url).path.lower().endswith(".gz")
            else response
        )
        try:
            with temporary_path.open("wb") as handle:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
        finally:
            if source is not response:
                source.close()


def _bootstrap_database():
    """Download a published SQLite file when running in a clean cloud image."""
    if os.environ.get("MLB_DB_SKIP_BOOTSTRAP", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        return

    if DB_PATH.exists():
        return

    configured_url = os.environ.get("MLB_DB_URL")
    configured_urls = []
    if configured_url:
        if urlparse(configured_url).path.lower().endswith(".db"):
            configured_urls.append(f"{configured_url}.gz")
        configured_urls.append(configured_url)
    automatic_urls = (
        [DEFAULT_DB_URL, FALLBACK_DB_URL]
        if not configured_url and DB_PATH.resolve() == DEFAULT_DB_PATH.resolve()
        else []
    )
    database_urls = configured_urls or automatic_urls
    if not database_urls:
        return

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = DB_PATH.with_suffix(DB_PATH.suffix + ".download")
    attempts = 80 if automatic_urls else 1
    for attempt in range(attempts):
        for database_url in database_urls:
            try:
                _download_database(database_url, temporary_path)
                with temporary_path.open("rb") as handle:
                    if handle.read(16) != b"SQLite format 3\x00":
                        raise ValueError(
                            "MLB_DB_URL did not return a SQLite database."
                        )
                temporary_path.replace(DB_PATH)
                return
            except urllib.error.HTTPError as error:
                if error.code != 404:
                    raise
            finally:
                if temporary_path.exists():
                    temporary_path.unlink()

        if attempt == attempts - 1:
            break
        time.sleep(15)


def bootstrap_database():
    if os.environ.get("MLB_DB_SKIP_BOOTSTRAP", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        return
    if DB_PATH.exists():
        return

    with _BOOTSTRAP_LOCK:
        _bootstrap_database()


def get_connection():
    bootstrap_database()
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


@contextmanager
def transaction():
    conn = get_connection()
    try:
        conn.execute("BEGIN")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def read_connection():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def _table_columns(conn, table_name):
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})")}


def _ensure_column(conn, table_name, column_name, declaration):
    if column_name not in _table_columns(conn, table_name):
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {declaration}")


def init_database():
    global _INITIALIZED_PATH
    with transaction() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS games (
                game_pk INTEGER PRIMARY KEY,
                game_id TEXT,
                retrosheet_game_id TEXT,
                source TEXT,
                game_date TEXT NOT NULL,
                season INTEGER NOT NULL,
                away_team TEXT,
                home_team TEXT,
                away_team_id INTEGER,
                home_team_id INTEGER,
                away_probable_pitcher TEXT,
                away_probable_pitcher_id INTEGER,
                home_probable_pitcher TEXT,
                home_probable_pitcher_id INTEGER,
                game_status TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS players (
                player_id INTEGER PRIMARY KEY,
                retro_id TEXT,
                player_name TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS processed_games (
                game_pk INTEGER PRIMARY KEY,
                game_id TEXT,
                source TEXT,
                game_date TEXT,
                season INTEGER,
                plate_appearances_loaded INTEGER,
                pitcher_logs_loaded INTEGER,
                processed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS batter_pitcher_game_logs (
                game_pk INTEGER,
                game_id TEXT,
                source TEXT,
                game_date TEXT,
                season INTEGER,
                batter_id INTEGER,
                pitcher_id INTEGER,
                batting_team TEXT,
                pitching_team TEXT,
                PA INTEGER,
                AB INTEGER,
                H INTEGER,
                doubles INTEGER,
                triples INTEGER,
                BB INTEGER,
                HBP INTEGER,
                SO INTEGER,
                HR INTEGER,
                RBI INTEGER,
                SF INTEGER,
                TB INTEGER,
                PRIMARY KEY (game_pk, batter_id, pitcher_id)
            );

            CREATE TABLE IF NOT EXISTS batter_pitcher_stats (
                batter_id INTEGER,
                pitcher_id INTEGER,
                batter_name TEXT,
                pitcher_name TEXT,
                PA INTEGER,
                AB INTEGER,
                H INTEGER,
                doubles INTEGER,
                triples INTEGER,
                BB INTEGER,
                HBP INTEGER,
                SO INTEGER,
                HR INTEGER,
                RBI INTEGER,
                SF INTEGER,
                TB INTEGER,
                AVG REAL,
                OBP REAL,
                SLG REAL,
                OPS REAL,
                K_pct REAL,
                BB_pct REAL,
                last_game_date TEXT,
                last_updated TEXT,
                PRIMARY KEY (batter_id, pitcher_id)
            );

            CREATE TABLE IF NOT EXISTS pitcher_game_logs (
                game_pk INTEGER,
                game_id TEXT,
                source TEXT,
                game_date TEXT,
                season INTEGER,
                pitcher_id INTEGER,
                pitcher_name TEXT,
                team TEXT,
                opponent TEXT,
                is_starter INTEGER,
                IP_outs INTEGER,
                IP REAL,
                pitch_count INTEGER,
                BF INTEGER,
                H INTEGER,
                BB INTEGER,
                HBP INTEGER,
                SO INTEGER,
                HR INTEGER,
                R INTEGER,
                ER INTEGER,
                PRIMARY KEY (game_pk, pitcher_id)
            );

            CREATE TABLE IF NOT EXISTS pitcher_stats (
                season INTEGER,
                pitcher_id INTEGER,
                pitcher_name TEXT,
                games INTEGER,
                starts INTEGER,
                IP_outs INTEGER,
                IP REAL,
                avg_ip_per_start REAL,
                avg_pitch_count_per_start REAL,
                BF INTEGER,
                H INTEGER,
                BB INTEGER,
                HBP INTEGER,
                SO INTEGER,
                HR INTEGER,
                R INTEGER,
                ER INTEGER,
                ERA REAL,
                WHIP REAL,
                K_pct REAL,
                K9 REAL,
                projected_ip REAL,
                projected_pitch_count REAL,
                projected_ks REAL,
                last_game_date TEXT,
                last_updated TEXT,
                PRIMARY KEY (season, pitcher_id)
            );

            CREATE TABLE IF NOT EXISTS refresh_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                refresh_type TEXT,
                refresh_date TEXT,
                games_checked INTEGER,
                games_processed INTEGER,
                plate_appearances_loaded INTEGER,
                pitcher_logs_loaded INTEGER,
                status TEXT,
                message TEXT,
                created_at TEXT
            );
            """
        )

        # Upgrade the original schema in place so the user's existing local
        # StatsAPI backfill remains usable.
        for table_name, columns in {
            "games": {
                "game_id": "TEXT",
                "retrosheet_game_id": "TEXT",
                "source": "TEXT",
            },
            "players": {"retro_id": "TEXT"},
            "processed_games": {"game_id": "TEXT", "source": "TEXT"},
            "batter_pitcher_game_logs": {"game_id": "TEXT", "source": "TEXT"},
            "batter_pitcher_stats": {
                "doubles": "INTEGER DEFAULT 0",
                "triples": "INTEGER DEFAULT 0",
                "SF": "INTEGER DEFAULT 0",
                "TB": "INTEGER DEFAULT 0",
                "last_game_date": "TEXT",
            },
            "pitcher_game_logs": {"game_id": "TEXT", "source": "TEXT"},
            "refresh_log": {
                "games_processed": "INTEGER DEFAULT 0",
                "plate_appearances_loaded": "INTEGER DEFAULT 0",
                "pitcher_logs_loaded": "INTEGER DEFAULT 0",
            },
        }.items():
            for column_name, declaration in columns.items():
                _ensure_column(conn, table_name, column_name, declaration)

        conn.execute(
            """
            UPDATE games
            SET game_id = COALESCE(game_id, 'mlb:' || game_pk),
                source = COALESCE(source, 'mlb_statsapi')
            WHERE game_id IS NULL OR source IS NULL
            """
        )
        conn.execute(
            """
            UPDATE processed_games
            SET game_id = COALESCE(game_id, 'mlb:' || game_pk),
                source = COALESCE(source, 'mlb_statsapi')
            WHERE game_id IS NULL OR source IS NULL
            """
        )
        conn.execute(
            """
            UPDATE batter_pitcher_game_logs
            SET game_id = COALESCE(game_id, 'mlb:' || game_pk),
                source = COALESCE(source, 'mlb_statsapi')
            WHERE game_id IS NULL OR source IS NULL
            """
        )
        conn.execute(
            """
            UPDATE pitcher_game_logs
            SET game_id = COALESCE(game_id, 'mlb:' || game_pk),
                source = COALESCE(source, 'mlb_statsapi')
            WHERE game_id IS NULL OR source IS NULL
            """
        )

        conn.executescript(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_games_game_id
                ON games(game_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_games_retrosheet_id
                ON games(retrosheet_game_id)
                WHERE retrosheet_game_id IS NOT NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS idx_players_retro_id
                ON players(retro_id)
                WHERE retro_id IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_games_date
                ON games(game_date);
            CREATE INDEX IF NOT EXISTS idx_game_logs_batter_pitcher
                ON batter_pitcher_game_logs(batter_id, pitcher_id);
            CREATE INDEX IF NOT EXISTS idx_game_logs_game_date
                ON batter_pitcher_game_logs(game_date);
            CREATE INDEX IF NOT EXISTS idx_batter_streak_logs
                ON batter_pitcher_game_logs(season, batter_id, game_date, game_pk);
            CREATE INDEX IF NOT EXISTS idx_bvp_stats_batter_pitcher
                ON batter_pitcher_stats(batter_id, pitcher_id);
            CREATE INDEX IF NOT EXISTS idx_pitcher_logs_pitcher
                ON pitcher_game_logs(pitcher_id);
            CREATE INDEX IF NOT EXISTS idx_pitcher_logs_opponent
                ON pitcher_game_logs(opponent);
            CREATE INDEX IF NOT EXISTS idx_pitcher_streak_logs
                ON pitcher_game_logs(season, pitcher_id, game_date);
            CREATE INDEX IF NOT EXISTS idx_pitcher_stats_pitcher_season
                ON pitcher_stats(pitcher_id, season);
            DROP TABLE IF EXISTS plate_appearances;
            """
        )
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    _INITIALIZED_PATH = str(DB_PATH.resolve())


def ensure_database():
    if _INITIALIZED_PATH != str(DB_PATH.resolve()):
        with _INITIALIZE_LOCK:
            if _INITIALIZED_PATH != str(DB_PATH.resolve()):
                init_database()


def _game_identity(game):
    game_pk = int(game["game_pk"])
    game_id = game.get("game_id") or f"mlb:{game_pk}"
    source = game.get("source") or "mlb_statsapi"
    return game_pk, game_id, source


def _upsert_game(conn, game):
    game_pk, game_id, source = _game_identity(game)
    conn.execute(
        """
        INSERT INTO games (
            game_pk, game_id, retrosheet_game_id, source, game_date, season,
            away_team, home_team, away_team_id, home_team_id,
            away_probable_pitcher, away_probable_pitcher_id,
            home_probable_pitcher, home_probable_pitcher_id,
            game_status, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(game_pk) DO UPDATE SET
            game_id = excluded.game_id,
            retrosheet_game_id = excluded.retrosheet_game_id,
            source = excluded.source,
            game_date = excluded.game_date,
            season = excluded.season,
            away_team = excluded.away_team,
            home_team = excluded.home_team,
            away_team_id = excluded.away_team_id,
            home_team_id = excluded.home_team_id,
            away_probable_pitcher = excluded.away_probable_pitcher,
            away_probable_pitcher_id = excluded.away_probable_pitcher_id,
            home_probable_pitcher = excluded.home_probable_pitcher,
            home_probable_pitcher_id = excluded.home_probable_pitcher_id,
            game_status = excluded.game_status,
            updated_at = excluded.updated_at
        """,
        (
            game_pk,
            game_id,
            game.get("retrosheet_game_id"),
            source,
            game.get("game_date"),
            game.get("season"),
            game.get("away_team"),
            game.get("home_team"),
            game.get("away_team_id"),
            game.get("home_team_id"),
            game.get("away_probable_pitcher"),
            game.get("away_probable_pitcher_id"),
            game.get("home_probable_pitcher"),
            game.get("home_probable_pitcher_id"),
            game.get("game_status"),
            now_text(),
        ),
    )


def upsert_game(game):
    with transaction() as conn:
        _upsert_game(conn, game)


def _upsert_player(conn, player_id, player_name, retro_id=None):
    if player_id is None:
        return
    conn.execute(
        """
        INSERT INTO players (player_id, retro_id, player_name, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(player_id) DO UPDATE SET
            retro_id = COALESCE(excluded.retro_id, players.retro_id),
            player_name = COALESCE(excluded.player_name, players.player_name),
            updated_at = excluded.updated_at
        """,
        (int(player_id), retro_id, player_name, now_text()),
    )


def upsert_player(player_id, player_name, retro_id=None):
    with transaction() as conn:
        _upsert_player(conn, player_id, player_name, retro_id)


def is_game_processed(game_pk):
    ensure_database()
    with read_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM processed_games WHERE game_pk = ?",
            (int(game_pk),),
        ).fetchone()
    return row is not None


def _delete_game_logs(conn, game_pk):
    conn.execute("DELETE FROM batter_pitcher_game_logs WHERE game_pk = ?", (int(game_pk),))
    conn.execute("DELETE FROM pitcher_game_logs WHERE game_pk = ?", (int(game_pk),))
    conn.execute("DELETE FROM processed_games WHERE game_pk = ?", (int(game_pk),))


def delete_game_logs(game_pk):
    with transaction() as conn:
        _delete_game_logs(conn, game_pk)


def _upsert_batter_pitcher_game_log(conn, log_row):
    game_pk = int(log_row["game_pk"])
    game_id = log_row.get("game_id") or f"mlb:{game_pk}"
    source = log_row.get("source") or "mlb_statsapi"
    conn.execute(
        """
        INSERT INTO batter_pitcher_game_logs (
            game_pk, game_id, source, game_date, season, batter_id, pitcher_id,
            batting_team, pitching_team, PA, AB, H, doubles, triples, BB, HBP,
            SO, HR, RBI, SF, TB
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(game_pk, batter_id, pitcher_id) DO UPDATE SET
            game_id = excluded.game_id,
            source = excluded.source,
            game_date = excluded.game_date,
            season = excluded.season,
            batting_team = excluded.batting_team,
            pitching_team = excluded.pitching_team,
            PA = excluded.PA,
            AB = excluded.AB,
            H = excluded.H,
            doubles = excluded.doubles,
            triples = excluded.triples,
            BB = excluded.BB,
            HBP = excluded.HBP,
            SO = excluded.SO,
            HR = excluded.HR,
            RBI = excluded.RBI,
            SF = excluded.SF,
            TB = excluded.TB
        """,
        (
            game_pk,
            game_id,
            source,
            log_row.get("game_date"),
            log_row.get("season"),
            log_row.get("batter_id"),
            log_row.get("pitcher_id"),
            log_row.get("batting_team"),
            log_row.get("pitching_team"),
            log_row.get("PA", 0),
            log_row.get("AB", 0),
            log_row.get("H", 0),
            log_row.get("doubles", 0),
            log_row.get("triples", 0),
            log_row.get("BB", 0),
            log_row.get("HBP", 0),
            log_row.get("SO", 0),
            log_row.get("HR", 0),
            log_row.get("RBI", 0),
            log_row.get("SF", 0),
            log_row.get("TB", 0),
        ),
    )


def upsert_batter_pitcher_game_log(log_row):
    with transaction() as conn:
        _upsert_batter_pitcher_game_log(conn, log_row)


def _upsert_pitcher_game_log(conn, log_row):
    game_pk = int(log_row["game_pk"])
    game_id = log_row.get("game_id") or f"mlb:{game_pk}"
    source = log_row.get("source") or "mlb_statsapi"
    conn.execute(
        """
        INSERT INTO pitcher_game_logs (
            game_pk, game_id, source, game_date, season, pitcher_id,
            pitcher_name, team, opponent, is_starter, IP_outs, IP,
            pitch_count, BF, H, BB, HBP, SO, HR, R, ER
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(game_pk, pitcher_id) DO UPDATE SET
            game_id = excluded.game_id,
            source = excluded.source,
            game_date = excluded.game_date,
            season = excluded.season,
            pitcher_name = excluded.pitcher_name,
            team = excluded.team,
            opponent = excluded.opponent,
            is_starter = excluded.is_starter,
            IP_outs = excluded.IP_outs,
            IP = excluded.IP,
            pitch_count = excluded.pitch_count,
            BF = excluded.BF,
            H = excluded.H,
            BB = excluded.BB,
            HBP = excluded.HBP,
            SO = excluded.SO,
            HR = excluded.HR,
            R = excluded.R,
            ER = excluded.ER
        """,
        (
            game_pk,
            game_id,
            source,
            log_row.get("game_date"),
            log_row.get("season"),
            log_row.get("pitcher_id"),
            log_row.get("pitcher_name"),
            log_row.get("team"),
            log_row.get("opponent"),
            log_row.get("is_starter", 0),
            log_row.get("IP_outs", 0),
            log_row.get("IP", 0.0),
            log_row.get("pitch_count"),
            log_row.get("BF", 0),
            log_row.get("H", 0),
            log_row.get("BB", 0),
            log_row.get("HBP", 0),
            log_row.get("SO", 0),
            log_row.get("HR", 0),
            log_row.get("R", 0),
            log_row.get("ER", 0),
        ),
    )


def upsert_pitcher_game_log(log_row):
    with transaction() as conn:
        _upsert_pitcher_game_log(conn, log_row)


def _mark_game_processed(
    conn,
    game_pk,
    game_id,
    source,
    game_date,
    season,
    plate_appearances_loaded,
    pitcher_logs_loaded,
):
    conn.execute(
        """
        INSERT INTO processed_games (
            game_pk, game_id, source, game_date, season,
            plate_appearances_loaded, pitcher_logs_loaded, processed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(game_pk) DO UPDATE SET
            game_id = excluded.game_id,
            source = excluded.source,
            game_date = excluded.game_date,
            season = excluded.season,
            plate_appearances_loaded = excluded.plate_appearances_loaded,
            pitcher_logs_loaded = excluded.pitcher_logs_loaded,
            processed_at = excluded.processed_at
        """,
        (
            int(game_pk),
            game_id,
            source,
            game_date,
            season,
            plate_appearances_loaded,
            pitcher_logs_loaded,
            now_text(),
        ),
    )


def mark_game_processed(
    game_pk,
    game_date,
    season,
    plate_appearances_loaded,
    pitcher_logs_loaded,
    game_id=None,
    source="mlb_statsapi",
):
    game_id = game_id or f"mlb:{int(game_pk)}"
    with transaction() as conn:
        _mark_game_processed(
            conn,
            game_pk,
            game_id,
            source,
            game_date,
            season,
            plate_appearances_loaded,
            pitcher_logs_loaded,
        )


def save_completed_game(
    game,
    players,
    batter_pitcher_logs,
    pitcher_logs,
    plate_appearances_loaded,
    reprocess_existing=False,
):
    """Persist one completed StatsAPI game as a single atomic transaction."""
    game_pk, game_id, source = _game_identity(game)
    with transaction() as conn:
        if reprocess_existing:
            _delete_game_logs(conn, game_pk)
        _upsert_game(conn, game)
        for player_id, player_name in players.items():
            _upsert_player(conn, player_id, player_name)
        for row in batter_pitcher_logs:
            _upsert_batter_pitcher_game_log(conn, row)
        for row in pitcher_logs:
            _upsert_pitcher_game_log(conn, row)
        _mark_game_processed(
            conn,
            game_pk,
            game_id,
            source,
            game.get("game_date"),
            game.get("season"),
            plate_appearances_loaded,
            len(pitcher_logs),
        )


def replace_retrosheet_season(
    season,
    games,
    players,
    batter_pitcher_logs,
    pitcher_logs,
    processed_games,
):
    """Replace one historical season only after it has parsed successfully."""
    with transaction() as conn:
        conn.execute("DELETE FROM batter_pitcher_game_logs WHERE season = ?", (season,))
        conn.execute("DELETE FROM pitcher_game_logs WHERE season = ?", (season,))
        conn.execute("DELETE FROM processed_games WHERE season = ?", (season,))
        conn.execute("DELETE FROM games WHERE season = ?", (season,))

        for player in players:
            _upsert_player(
                conn,
                player.get("player_id"),
                player.get("player_name"),
                player.get("retro_id"),
            )
        for game in games:
            _upsert_game(conn, game)
        for row in batter_pitcher_logs:
            _upsert_batter_pitcher_game_log(conn, row)
        for row in pitcher_logs:
            _upsert_pitcher_game_log(conn, row)
        for row in processed_games:
            _mark_game_processed(
                conn,
                row["game_pk"],
                row["game_id"],
                "retrosheet",
                row["game_date"],
                season,
                row["plate_appearances_loaded"],
                row["pitcher_logs_loaded"],
            )


def rebuild_batter_pitcher_stats():
    with transaction() as conn:
        conn.execute("DELETE FROM batter_pitcher_stats")
        conn.execute(
            """
            INSERT INTO batter_pitcher_stats (
                batter_id, pitcher_id, batter_name, pitcher_name,
                PA, AB, H, doubles, triples, BB, HBP, SO, HR, RBI, SF, TB,
                AVG, OBP, SLG, OPS, K_pct, BB_pct, last_game_date, last_updated
            )
            SELECT
                gl.batter_id,
                gl.pitcher_id,
                MAX(bp.player_name),
                MAX(pp.player_name),
                SUM(gl.PA),
                SUM(gl.AB),
                SUM(gl.H),
                SUM(gl.doubles),
                SUM(gl.triples),
                SUM(gl.BB),
                SUM(gl.HBP),
                SUM(gl.SO),
                SUM(gl.HR),
                SUM(gl.RBI),
                SUM(gl.SF),
                SUM(gl.TB),
                CASE WHEN SUM(gl.AB) > 0
                    THEN ROUND(SUM(gl.H) * 1.0 / SUM(gl.AB), 3) ELSE 0 END,
                CASE WHEN SUM(gl.AB) + SUM(gl.BB) + SUM(gl.HBP) + SUM(gl.SF) > 0
                    THEN ROUND(
                        (SUM(gl.H) + SUM(gl.BB) + SUM(gl.HBP)) * 1.0 /
                        (SUM(gl.AB) + SUM(gl.BB) + SUM(gl.HBP) + SUM(gl.SF)),
                        3
                    ) ELSE 0 END,
                CASE WHEN SUM(gl.AB) > 0
                    THEN ROUND(SUM(gl.TB) * 1.0 / SUM(gl.AB), 3) ELSE 0 END,
                CASE WHEN SUM(gl.AB) > 0
                    AND SUM(gl.AB) + SUM(gl.BB) + SUM(gl.HBP) + SUM(gl.SF) > 0
                    THEN ROUND(
                        (SUM(gl.H) + SUM(gl.BB) + SUM(gl.HBP)) * 1.0 /
                        (SUM(gl.AB) + SUM(gl.BB) + SUM(gl.HBP) + SUM(gl.SF)) +
                        SUM(gl.TB) * 1.0 / SUM(gl.AB),
                        3
                    ) ELSE 0 END,
                CASE WHEN SUM(gl.PA) > 0
                    THEN ROUND(SUM(gl.SO) * 100.0 / SUM(gl.PA), 2) ELSE 0 END,
                CASE WHEN SUM(gl.PA) > 0
                    THEN ROUND(SUM(gl.BB) * 100.0 / SUM(gl.PA), 2) ELSE 0 END,
                MAX(gl.game_date),
                ?
            FROM batter_pitcher_game_logs gl
            LEFT JOIN players bp ON gl.batter_id = bp.player_id
            LEFT JOIN players pp ON gl.pitcher_id = pp.player_id
            GROUP BY gl.batter_id, gl.pitcher_id
            """,
            (now_text(),),
        )


def rebuild_pitcher_stats():
    with transaction() as conn:
        conn.execute("DELETE FROM pitcher_stats")
        conn.execute(
            """
            INSERT INTO pitcher_stats (
                season, pitcher_id, pitcher_name, games, starts, IP_outs, IP,
                avg_ip_per_start, avg_pitch_count_per_start,
                BF, H, BB, HBP, SO, HR, R, ER, ERA, WHIP, K_pct, K9,
                projected_ip, projected_pitch_count, projected_ks,
                last_game_date, last_updated
            )
            SELECT
                season,
                pitcher_id,
                MAX(pitcher_name),
                COUNT(*),
                SUM(is_starter),
                SUM(IP_outs),
                CAST(SUM(IP_outs) / 3 AS INTEGER) + (SUM(IP_outs) % 3) / 10.0,
                CASE WHEN SUM(is_starter) > 0
                    THEN ROUND(
                        SUM(CASE WHEN is_starter = 1 THEN IP_outs ELSE 0 END)
                        / 3.0 / SUM(is_starter),
                        2
                    )
                    ELSE ROUND(SUM(IP_outs) / 3.0 / COUNT(*), 2)
                END,
                ROUND(AVG(CASE WHEN is_starter = 1 THEN pitch_count END), 0),
                SUM(BF), SUM(H), SUM(BB), SUM(HBP), SUM(SO), SUM(HR), SUM(R), SUM(ER),
                CASE WHEN SUM(IP_outs) > 0
                    THEN ROUND(SUM(ER) * 27.0 / SUM(IP_outs), 2) ELSE 0 END,
                CASE WHEN SUM(IP_outs) > 0
                    THEN ROUND((SUM(BB) + SUM(H)) * 3.0 / SUM(IP_outs), 2) ELSE 0 END,
                CASE WHEN SUM(BF) > 0
                    THEN ROUND(SUM(SO) * 100.0 / SUM(BF), 2) ELSE 0 END,
                CASE WHEN SUM(IP_outs) > 0
                    THEN ROUND(SUM(SO) * 27.0 / SUM(IP_outs), 2) ELSE 0 END,
                CASE WHEN SUM(is_starter) > 0
                    THEN ROUND(
                        SUM(CASE WHEN is_starter = 1 THEN IP_outs ELSE 0 END)
                        / 3.0 / SUM(is_starter),
                        2
                    )
                    ELSE ROUND(SUM(IP_outs) / 3.0 / COUNT(*), 2)
                END,
                ROUND(AVG(CASE WHEN is_starter = 1 THEN pitch_count END), 0),
                CASE WHEN SUM(IP_outs) > 0
                    THEN ROUND(
                        (
                            CASE WHEN SUM(is_starter) > 0
                                THEN SUM(CASE WHEN is_starter = 1 THEN IP_outs ELSE 0 END)
                                    / 3.0 / SUM(is_starter)
                                ELSE SUM(IP_outs) / 3.0 / COUNT(*)
                            END
                        ) * (SUM(SO) * 3.0 / SUM(IP_outs)),
                        2
                    )
                    ELSE 0
                END,
                MAX(game_date),
                ?
            FROM pitcher_game_logs
            GROUP BY season, pitcher_id
            """,
            (now_text(),),
        )


def rebuild_all_summary_stats():
    rebuild_batter_pitcher_stats()
    rebuild_pitcher_stats()


def empty_bvp_result(grade):
    return {
        "PA": 0,
        "AB": 0,
        "H": 0,
        "2B": 0,
        "3B": 0,
        "BB": 0,
        "HBP": 0,
        "SO": 0,
        "HR": 0,
        "RBI": 0,
        "AVG": 0.000,
        "OBP": 0.000,
        "SLG": 0.000,
        "OPS": 0.000,
        "K%": 0.00,
        "BB%": 0.00,
        "matchup_grade": grade,
    }


def grade_bvp(at_bats, batting_average):
    return grade_hitter_matchup(at_bats, batting_average)


def get_batter_vs_pitcher_stats_from_db(batter_id, pitcher_id):
    if batter_id is None or pitcher_id is None:
        return empty_bvp_result("No Pitcher ID")
    ensure_database()
    with read_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM batter_pitcher_stats
            WHERE batter_id = ? AND pitcher_id = ?
            """,
            (int(batter_id), int(pitcher_id)),
        ).fetchone()
    if row is None:
        return empty_bvp_result("No History")
    return {
        "PA": row["PA"],
        "AB": row["AB"],
        "H": row["H"],
        "2B": row["doubles"],
        "3B": row["triples"],
        "BB": row["BB"],
        "HBP": row["HBP"],
        "SO": row["SO"],
        "HR": row["HR"],
        "RBI": row["RBI"],
        "AVG": row["AVG"],
        "OBP": row["OBP"],
        "SLG": row["SLG"],
        "OPS": row["OPS"],
        "K%": row["K_pct"],
        "BB%": row["BB_pct"],
        "matchup_grade": grade_bvp(row["AB"], row["AVG"]),
    }


def get_batter_vs_pitcher_stats_batch_from_db(matchup_pairs):
    ensure_database()
    clean_pairs = []
    for batter_id, pitcher_id in matchup_pairs:
        if batter_id is None or pitcher_id is None:
            continue
        try:
            pair = (int(batter_id), int(pitcher_id))
        except (TypeError, ValueError):
            continue
        if pair not in clean_pairs:
            clean_pairs.append(pair)

    results = {
        pair: empty_bvp_result("No History")
        for pair in clean_pairs
    }
    if not clean_pairs:
        return results

    with read_connection() as conn:
        for offset in range(0, len(clean_pairs), 400):
            chunk = clean_pairs[offset : offset + 400]
            placeholders = ",".join("(?, ?)" for _ in chunk)
            params = [
                value
                for pair in chunk
                for value in pair
            ]
            rows = conn.execute(
                f"""
                SELECT *
                FROM batter_pitcher_stats
                WHERE (batter_id, pitcher_id) IN ({placeholders})
                """,
                params,
            ).fetchall()
            for row in rows:
                results[(row["batter_id"], row["pitcher_id"])] = {
                    "PA": row["PA"],
                    "AB": row["AB"],
                    "H": row["H"],
                    "2B": row["doubles"],
                    "3B": row["triples"],
                    "BB": row["BB"],
                    "HBP": row["HBP"],
                    "SO": row["SO"],
                    "HR": row["HR"],
                    "RBI": row["RBI"],
                    "AVG": row["AVG"],
                    "OBP": row["OBP"],
                    "SLG": row["SLG"],
                    "OPS": row["OPS"],
                    "K%": row["K_pct"],
                    "BB%": row["BB_pct"],
                    "matchup_grade": grade_bvp(row["AB"], row["AVG"]),
                }
    return results


def get_batter_vs_pitcher_game_logs_from_db(batter_id, pitcher_id):
    ensure_database()
    with read_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                gl.game_date,
                gl.batting_team AS team,
                gl.pitching_team AS opponent,
                CASE
                    WHEN gl.batting_team = g.home_team THEN 'Home'
                    WHEN gl.batting_team = g.away_team THEN 'Away'
                    ELSE NULL
                END AS home_away,
                gl.PA, gl.AB, gl.H, gl.TB, gl.BB, gl.HBP, gl.SO, gl.HR, gl.RBI,
                CASE WHEN gl.AB > 0 THEN ROUND(gl.H * 1.0 / gl.AB, 3) END AS AVG,
                CASE WHEN gl.AB + gl.BB + gl.HBP + gl.SF > 0
                    THEN ROUND(
                        (gl.H + gl.BB + gl.HBP) * 1.0 /
                        (gl.AB + gl.BB + gl.HBP + gl.SF),
                        3
                    )
                END AS OBP,
                CASE WHEN gl.AB > 0 THEN ROUND(gl.TB * 1.0 / gl.AB, 3) END AS SLG,
                CASE WHEN gl.AB > 0 AND gl.AB + gl.BB + gl.HBP + gl.SF > 0
                    THEN ROUND(
                        (gl.H + gl.BB + gl.HBP) * 1.0 /
                        (gl.AB + gl.BB + gl.HBP + gl.SF) +
                        gl.TB * 1.0 / gl.AB,
                        3
                    )
                END AS OPS,
                CASE WHEN gl.PA > 0 THEN ROUND(gl.SO * 100.0 / gl.PA, 2) END AS "K%",
                CASE WHEN gl.PA > 0 THEN ROUND(gl.BB * 100.0 / gl.PA, 2) END AS "BB%"
            FROM batter_pitcher_game_logs gl
            LEFT JOIN games g ON gl.game_pk = g.game_pk
            WHERE gl.batter_id = ? AND gl.pitcher_id = ?
            ORDER BY gl.game_date DESC
            """,
            (int(batter_id), int(pitcher_id)),
        ).fetchall()
    return [dict(row) for row in rows]


def get_batter_season_game_logs_from_db(batter_id, season):
    ensure_database()
    with read_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                gl.game_pk,
                gl.game_date,
                gl.batting_team AS team,
                CASE
                    WHEN gl.batting_team = g.home_team THEN g.away_team
                    WHEN gl.batting_team = g.away_team THEN g.home_team
                    ELSE MAX(gl.pitching_team)
                END AS opponent,
                CASE
                    WHEN gl.batting_team = g.home_team THEN 'Home'
                    WHEN gl.batting_team = g.away_team THEN 'Away'
                    ELSE NULL
                END AS home_away,
                SUM(gl.PA) AS PA,
                SUM(gl.AB) AS AB,
                SUM(gl.H) AS H,
                SUM(gl.TB) AS TB,
                SUM(gl.BB) AS BB,
                SUM(gl.HBP) AS HBP,
                SUM(gl.SO) AS SO,
                SUM(gl.HR) AS HR,
                SUM(gl.RBI) AS RBI,
                CASE WHEN SUM(gl.AB) > 0
                    THEN ROUND(SUM(gl.H) * 1.0 / SUM(gl.AB), 3) END AS AVG,
                CASE WHEN SUM(gl.AB) + SUM(gl.BB) + SUM(gl.HBP) + SUM(gl.SF) > 0
                    THEN ROUND(
                        (SUM(gl.H) + SUM(gl.BB) + SUM(gl.HBP)) * 1.0 /
                        (SUM(gl.AB) + SUM(gl.BB) + SUM(gl.HBP) + SUM(gl.SF)),
                        3
                    )
                END AS OBP,
                CASE WHEN SUM(gl.AB) > 0
                    THEN ROUND(SUM(gl.TB) * 1.0 / SUM(gl.AB), 3) END AS SLG,
                CASE WHEN SUM(gl.AB) > 0
                    AND SUM(gl.AB) + SUM(gl.BB) + SUM(gl.HBP) + SUM(gl.SF) > 0
                    THEN ROUND(
                        (SUM(gl.H) + SUM(gl.BB) + SUM(gl.HBP)) * 1.0 /
                        (SUM(gl.AB) + SUM(gl.BB) + SUM(gl.HBP) + SUM(gl.SF)) +
                        SUM(gl.TB) * 1.0 / SUM(gl.AB),
                        3
                    )
                END AS OPS,
                CASE WHEN SUM(gl.PA) > 0
                    THEN ROUND(SUM(gl.SO) * 100.0 / SUM(gl.PA), 2) END AS "K%",
                CASE WHEN SUM(gl.PA) > 0
                    THEN ROUND(SUM(gl.BB) * 100.0 / SUM(gl.PA), 2) END AS "BB%"
            FROM batter_pitcher_game_logs gl
            LEFT JOIN games g ON gl.game_pk = g.game_pk
            WHERE gl.batter_id = ? AND gl.season = ?
            GROUP BY
                gl.game_pk,
                gl.game_date,
                gl.batting_team,
                g.home_team,
                g.away_team
            ORDER BY gl.game_date DESC, gl.game_pk DESC
            """,
            (int(batter_id), int(season)),
        ).fetchall()
    return [dict(row) for row in rows]


def get_pitcher_season_game_logs_from_db(pitcher_id, season):
    ensure_database()
    with read_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                gl.game_pk,
                gl.game_date,
                gl.team,
                gl.opponent,
                CASE
                    WHEN gl.team = g.home_team THEN 'Home'
                    WHEN gl.team = g.away_team THEN 'Away'
                    ELSE NULL
                END AS home_away,
                gl.IP,
                gl.pitch_count AS "Pitch Count",
                gl.BF,
                gl.H,
                gl.BB,
                gl.HBP,
                gl.SO,
                gl.HR,
                gl.R,
                gl.ER
            FROM pitcher_game_logs gl
            LEFT JOIN games g ON gl.game_pk = g.game_pk
            WHERE gl.pitcher_id = ? AND gl.season = ?
            ORDER BY gl.game_date DESC, gl.game_pk DESC
            """,
            (int(pitcher_id), int(season)),
        ).fetchall()
    return [dict(row) for row in rows]


def get_pitcher_stats_from_db(season, pitcher_id):
    if pitcher_id is None:
        return None
    ensure_database()
    with read_connection() as conn:
        row = conn.execute(
            "SELECT * FROM pitcher_stats WHERE season = ? AND pitcher_id = ?",
            (int(season), int(pitcher_id)),
        ).fetchone()
    return dict(row) if row else None


def get_batter_season_stats_from_db(season):
    ensure_database()
    with read_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                gl.batter_id AS player_id,
                MAX(bp.player_name) AS Name,
                MAX(gl.batting_team) AS team_name,
                MAX(gl.batting_team) AS Team,
                COUNT(DISTINCT gl.game_pk) AS G,
                SUM(gl.PA) AS PA,
                SUM(gl.AB) AS AB,
                SUM(gl.H) AS H,
                0 AS R,
                SUM(gl.BB) AS BB,
                SUM(gl.HBP) AS HBP,
                SUM(gl.SO) AS SO,
                SUM(gl.HR) AS HR,
                SUM(gl.RBI) AS RBI,
                0 AS SB,
                SUM(gl.TB) AS TB,
                SUM(gl.SF) AS SF,
                CASE WHEN SUM(gl.AB) > 0
                    THEN ROUND(SUM(gl.H) * 1.0 / SUM(gl.AB), 3) ELSE 0 END AS AVG,
                CASE WHEN SUM(gl.AB) + SUM(gl.BB) + SUM(gl.HBP) + SUM(gl.SF) > 0
                    THEN ROUND(
                        (SUM(gl.H) + SUM(gl.BB) + SUM(gl.HBP)) * 1.0 /
                        (SUM(gl.AB) + SUM(gl.BB) + SUM(gl.HBP) + SUM(gl.SF)),
                        3
                    ) ELSE 0 END AS OBP,
                CASE WHEN SUM(gl.AB) > 0
                    THEN ROUND(SUM(gl.TB) * 1.0 / SUM(gl.AB), 3) ELSE 0 END AS SLG,
                CASE WHEN SUM(gl.AB) > 0
                    AND SUM(gl.AB) + SUM(gl.BB) + SUM(gl.HBP) + SUM(gl.SF) > 0
                    THEN ROUND(
                        (SUM(gl.H) + SUM(gl.BB) + SUM(gl.HBP)) * 1.0 /
                        (SUM(gl.AB) + SUM(gl.BB) + SUM(gl.HBP) + SUM(gl.SF)) +
                        SUM(gl.TB) * 1.0 / SUM(gl.AB),
                        3
                    ) ELSE 0 END AS OPS,
                CASE WHEN SUM(gl.PA) > 0
                    THEN ROUND(SUM(gl.SO) * 100.0 / SUM(gl.PA), 2) ELSE 0 END AS "K%",
                CASE WHEN SUM(gl.PA) > 0
                    THEN ROUND(SUM(gl.BB) * 100.0 / SUM(gl.PA), 2) ELSE 0 END AS "BB%"
            FROM batter_pitcher_game_logs gl
            LEFT JOIN players bp ON gl.batter_id = bp.player_id
            WHERE gl.season = ?
            GROUP BY gl.batter_id
            HAVING Name IS NOT NULL
            """,
            (int(season),),
        ).fetchall()
    return [dict(row) for row in rows]


def get_pitcher_season_stats_from_db(season):
    ensure_database()
    with read_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                ps.pitcher_id AS player_id,
                ps.pitcher_name AS Name,
                COALESCE(latest.team, '') AS team_name,
                COALESCE(latest.team, '') AS Team,
                ps.games AS G,
                ps.starts AS GS,
                ps.IP,
                CASE
                    WHEN ps.avg_pitch_count_per_start IS NOT NULL
                        AND ps.starts IS NOT NULL
                    THEN ROUND(ps.avg_pitch_count_per_start * ps.starts, 0)
                    ELSE NULL
                END AS Pitches,
                ps.H,
                ps.ERA,
                ps.WHIP,
                ps.K9 AS "K/9",
                CASE WHEN ps.IP_outs > 0
                    THEN ROUND(ps.BB * 27.0 / ps.IP_outs, 2) ELSE 0 END AS "BB/9",
                ps.SO,
                ps.BB,
                ps.HR,
                ps.BF,
                ps.K_pct AS "K%",
                CASE WHEN ps.BF > 0
                    THEN ROUND(ps.BB * 100.0 / ps.BF, 2) ELSE 0 END AS "BB%",
                NULL AS "SwStr%"
            FROM pitcher_stats ps
            LEFT JOIN (
                SELECT pgl.pitcher_id, pgl.team
                FROM pitcher_game_logs pgl
                INNER JOIN (
                    SELECT pitcher_id, MAX(game_date) AS latest_game_date
                    FROM pitcher_game_logs
                    WHERE season = ?
                    GROUP BY pitcher_id
                ) recent
                    ON recent.pitcher_id = pgl.pitcher_id
                    AND recent.latest_game_date = pgl.game_date
                WHERE pgl.season = ?
                GROUP BY pgl.pitcher_id
            ) latest ON latest.pitcher_id = ps.pitcher_id
            WHERE ps.season = ?
            """,
            (int(season), int(season), int(season)),
        ).fetchall()
    return [dict(row) for row in rows]


def get_pitcher_vs_team_game_logs_from_db(pitcher_id, opponent):
    ensure_database()
    with read_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                gl.game_date,
                gl.team,
                gl.opponent,
                CASE
                    WHEN gl.team = g.home_team THEN 'Home'
                    WHEN gl.team = g.away_team THEN 'Away'
                    ELSE NULL
                END AS home_away,
                gl.IP,
                gl.pitch_count AS "Pitch Count",
                gl.BF, gl.H, gl.BB, gl.HBP, gl.SO, gl.HR, gl.R, gl.ER
            FROM pitcher_game_logs gl
            LEFT JOIN games g ON gl.game_pk = g.game_pk
            WHERE gl.pitcher_id = ? AND gl.opponent = ?
            ORDER BY gl.game_date DESC
            """,
            (int(pitcher_id), opponent),
        ).fetchall()
    return [dict(row) for row in rows]


def get_batter_streak_game_logs_from_db(batter_ids, season=None):
    ensure_database()
    batter_ids = [
        int(player_id)
        for player_id in batter_ids
        if player_id is not None
    ]
    if not batter_ids:
        return []

    placeholders = ",".join("?" for _ in batter_ids)
    params = list(batter_ids)
    season_filter = ""
    if season is not None:
        season_filter = " AND gl.season = ?"
        params.append(int(season))

    with read_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT
                gl.batter_id AS player_id,
                gl.game_pk,
                gl.game_date,
                gl.batting_team AS team,
                SUM(gl.H) AS H,
                SUM(gl.HR) AS HR,
                SUM(gl.RBI) AS RBI,
                SUM(gl.SO) AS SO
            FROM batter_pitcher_game_logs gl
            WHERE gl.batter_id IN ({placeholders}){season_filter}
            GROUP BY gl.batter_id, gl.game_pk, gl.game_date, gl.batting_team
            ORDER BY gl.game_date DESC
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def get_pitcher_streak_game_logs_from_db(pitcher_ids, season=None):
    ensure_database()
    pitcher_ids = [
        int(player_id)
        for player_id in pitcher_ids
        if player_id is not None
    ]
    if not pitcher_ids:
        return []

    placeholders = ",".join("?" for _ in pitcher_ids)
    params = list(pitcher_ids)
    season_filter = ""
    if season is not None:
        season_filter = " AND season = ?"
        params.append(int(season))

    with read_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT
                pitcher_id AS player_id,
                game_pk,
                game_date,
                team,
                SO
            FROM pitcher_game_logs
            WHERE pitcher_id IN ({placeholders}){season_filter}
            ORDER BY game_date DESC
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def log_refresh(
    refresh_type,
    refresh_date,
    games_checked,
    games_processed,
    plate_appearances_loaded,
    pitcher_logs_loaded,
    status,
    message,
):
    ensure_database()
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO refresh_log (
                refresh_type, refresh_date, games_checked, games_processed,
                plate_appearances_loaded, pitcher_logs_loaded,
                status, message, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                refresh_type,
                refresh_date,
                games_checked,
                games_processed,
                plate_appearances_loaded,
                pitcher_logs_loaded,
                status,
                message,
                now_text(),
            ),
        )


def database_counts():
    ensure_database()
    table_names = [
        "games",
        "processed_games",
        "batter_pitcher_game_logs",
        "batter_pitcher_stats",
        "pitcher_game_logs",
        "pitcher_stats",
    ]
    with read_connection() as conn:
        return {
            table_name: conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            for table_name in table_names
        }


def print_database_counts():
    counts = database_counts()
    print("----------------------------------------")
    print("DATABASE COUNTS")
    for table_name, count in counts.items():
        print(f"{table_name}: {count}")
    print("----------------------------------------")

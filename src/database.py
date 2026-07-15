import base64
import gzip
import hashlib
import json
import logging
import os
import sqlite3
import time
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse

import requests

from src.api_client import get as http_get
from src.matchup_grading import grade_hitter_matchup

LOGGER = logging.getLogger(__name__)
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
SCHEMA_VERSION = 5
_INITIALIZED_PATH = None
_BOOTSTRAP_LOCK = Lock()
_INITIALIZE_LOCK = Lock()
BVP_STAT_COLUMNS = (
    "batter_id",
    "pitcher_id",
    "PA",
    "AB",
    "H",
    "doubles",
    "triples",
    "BB",
    "HBP",
    "SO",
    "HR",
    "RBI",
    "SF",
    "TB",
    "AVG",
    "OBP",
    "SLG",
    "OPS",
    "K_pct",
    "BB_pct",
    "last_game_date",
)
PITCHER_STAT_COLUMNS = (
    "season",
    "pitcher_id",
    "pitcher_name",
    "games",
    "starts",
    "IP_outs",
    "IP",
    "avg_ip_per_start",
    "avg_pitch_count_per_start",
    "BF",
    "H",
    "BB",
    "HBP",
    "SO",
    "HR",
    "R",
    "ER",
    "ERA",
    "WHIP",
    "K_pct",
    "K9",
    "projected_ip",
    "projected_pitch_count",
    "projected_ks",
    "last_game_date",
    "last_updated",
)


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _truthy_environment_value(name, default=""):
    return os.environ.get(name, default).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _turso_database_url():
    return os.environ.get("TURSO_DATABASE_URL", "").strip()


def using_turso():
    """Return whether the process is configured for remote Turso reads."""
    return bool(_turso_database_url())


def database_writes_enabled():
    """Keep the remote serving connection read-only unless explicitly enabled."""
    if not using_turso():
        return True
    read_only = os.environ.get("TURSO_READ_ONLY", "").strip()
    if not read_only:
        return False
    return not _truthy_environment_value("TURSO_READ_ONLY")


def _database_identity():
    database_url = _turso_database_url()
    if not database_url:
        return str(DB_PATH.resolve())
    fingerprint = hashlib.sha256(database_url.encode("utf-8")).hexdigest()[:16]
    return f"turso:{fingerprint}"


class _RemoteRow(Mapping):
    """Provide sqlite3.Row-style name and position access for remote rows."""

    def __init__(self, column_names, values):
        self._column_names = tuple(column_names)
        self._values = tuple(values)
        self._positions = {
            str(column_name).lower(): index
            for index, column_name in enumerate(self._column_names)
        }

    def __getitem__(self, key):
        if isinstance(key, (int, slice)):
            return self._values[key]
        position = self._positions.get(str(key).lower())
        if position is None:
            raise KeyError(key)
        return self._values[position]

    def __iter__(self):
        return iter(self._column_names)

    def __len__(self):
        return len(self._values)

    def keys(self):
        return self._column_names


class _RemoteCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    def _column_names(self):
        description = self._cursor.description or ()
        return tuple(
            column[0] if isinstance(column, (tuple, list)) else str(column)
            for column in description
        )

    def _row(self, row):
        if row is None or isinstance(row, Mapping):
            return row
        return _RemoteRow(self._column_names(), row)

    def fetchone(self):
        return self._row(self._cursor.fetchone())

    def fetchall(self):
        return [self._row(row) for row in self._cursor.fetchall()]

    def __iter__(self):
        for row in self._cursor:
            yield self._row(row)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class _RemoteConnection:
    def __init__(self, connection):
        self._connection = connection

    def execute(self, sql, parameters=None):
        cursor = (
            self._connection.execute(sql)
            if parameters is None
            else self._connection.execute(sql, parameters)
        )
        return _RemoteCursor(cursor)

    def executemany(self, sql, parameters):
        return _RemoteCursor(self._connection.executemany(sql, parameters))

    def __getattr__(self, name):
        return getattr(self._connection, name)


class _HttpCursor:
    def __init__(self, result):
        columns = result.get("cols") or []
        self.description = tuple(
            (column.get("name", ""), None, None, None, None, None, None)
            for column in columns
        )
        self._rows = [
            tuple(_decode_http_value(value) for value in row)
            for row in (result.get("rows") or [])
        ]
        self._position = 0
        self.rowcount = int(result.get("affected_row_count") or 0)
        self.lastrowid = result.get("last_insert_rowid")

    def fetchone(self):
        if self._position >= len(self._rows):
            return None
        row = self._rows[self._position]
        self._position += 1
        return row

    def fetchall(self):
        rows = self._rows[self._position :]
        self._position = len(self._rows)
        return rows

    def __iter__(self):
        while self._position < len(self._rows):
            yield self.fetchone()


def _encode_http_value(value):
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": "1" if value else "0"}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": repr(value)}
    if isinstance(value, (bytes, bytearray, memoryview)):
        encoded = base64.b64encode(bytes(value)).decode("ascii")
        return {"type": "blob", "base64": encoded}
    return {"type": "text", "value": str(value)}


def _decode_http_value(value):
    value_type = value.get("type")
    if value_type == "null":
        return None
    if value_type == "integer":
        return int(value.get("value", "0"))
    if value_type == "float":
        return float(value.get("value", "0"))
    if value_type == "blob":
        return base64.b64decode(value.get("base64", ""))
    return value.get("value")


class _HttpConnection:
    """Small DB-API-style adapter for Turso's portable SQL-over-HTTP API."""

    def __init__(self, database_url, auth_token, timeout=30):
        http_url = database_url.strip()
        if http_url.startswith("libsql://"):
            http_url = "https://" + http_url[len("libsql://") :]
        self._base_url = http_url.rstrip("/")
        self._auth_token = auth_token
        self._timeout = timeout
        self._baton = None
        self._routed_base_url = None
        self._session = requests.Session()
        self._closed = False

    @staticmethod
    def _pipeline_url(base_url):
        base_url = base_url.rstrip("/")
        if base_url.endswith("/v2/pipeline"):
            return base_url
        return f"{base_url}/v2/pipeline"

    def _pipeline(self, requests_payload):
        if self._closed:
            raise RuntimeError("The Turso HTTP connection is closed.")
        payload = {"requests": requests_payload}
        if self._baton:
            payload["baton"] = self._baton
        target_base_url = self._routed_base_url or self._base_url
        response = self._session.post(
            self._pipeline_url(target_base_url),
            headers={
                "Authorization": f"Bearer {self._auth_token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self._timeout,
        )
        response.raise_for_status()
        body = response.json()
        self._baton = body.get("baton")
        self._routed_base_url = body.get("base_url") or self._routed_base_url
        results = body.get("results") or []
        if len(results) != len(requests_payload):
            raise RuntimeError("Turso returned an incomplete pipeline response.")
        return results

    @staticmethod
    def _result(result):
        if result.get("type") != "ok":
            error = result.get("error") or {}
            message = error.get("message") or "Unknown SQL-over-HTTP error"
            raise RuntimeError(f"Turso query failed: {message}")
        response = result.get("response") or {}
        if response.get("type") != "execute":
            return {}
        return response.get("result") or {}

    @staticmethod
    def _statement(sql, parameters=None):
        statement = {"sql": sql}
        if parameters is not None:
            statement["args"] = [_encode_http_value(value) for value in parameters]
        return {"type": "execute", "stmt": statement}

    def execute(self, sql, parameters=None):
        result = self._pipeline([self._statement(sql, parameters)])[0]
        return _HttpCursor(self._result(result))

    def executemany(self, sql, parameters):
        statements = [self._statement(sql, values) for values in parameters]
        if not statements:
            return _HttpCursor({})
        results = self._pipeline(statements)
        affected_rows = 0
        last_insert_rowid = None
        for result in results:
            statement_result = self._result(result)
            affected_rows += int(statement_result.get("affected_row_count") or 0)
            if statement_result.get("last_insert_rowid") is not None:
                last_insert_rowid = statement_result["last_insert_rowid"]
        return _HttpCursor(
            {
                "affected_row_count": affected_rows,
                "last_insert_rowid": last_insert_rowid,
            }
        )

    def close(self):
        if self._closed:
            return
        try:
            if self._baton:
                self._pipeline([{"type": "close"}])
        finally:
            self._closed = True
            self._baton = None
            self._session.close()


def _connect_turso(database_url, auth_token):
    return _HttpConnection(database_url, auth_token)


def _download_database(database_url, temporary_path, expected_sha256=None):
    response = http_get(
        database_url,
        provider="GitHub release database",
        timeout=90,
        attempts=2,
        stream=True,
    )
    response.raise_for_status()
    response.raw.decode_content = False
    source = (
        gzip.GzipFile(fileobj=response.raw)
        if urlparse(database_url).path.lower().endswith(".gz")
        else response.raw
    )
    digest = hashlib.sha256()
    try:
        with temporary_path.open("wb") as handle:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                handle.write(chunk)
    finally:
        if source is not response.raw:
            source.close()
        response.close()

    if expected_sha256:
        actual_sha256 = digest.hexdigest()
        if actual_sha256.lower() != str(expected_sha256).strip().lower():
            raise ValueError(
                "Downloaded MLB database SHA256 did not match MLB_DB_SHA256."
            )


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
    default_attempts = "2" if automatic_urls else "1"
    attempts = max(1, int(os.environ.get("MLB_DB_BOOTSTRAP_ATTEMPTS", default_attempts)))
    retry_delay = max(
        0.0,
        float(os.environ.get("MLB_DB_BOOTSTRAP_RETRY_DELAY_SECONDS", "2") or 2),
    )
    expected_sha256 = os.environ.get("MLB_DB_SHA256")
    for attempt in range(attempts):
        for database_url in database_urls:
            try:
                _download_database(
                    database_url,
                    temporary_path,
                    expected_sha256=expected_sha256,
                )
                with temporary_path.open("rb") as handle:
                    if handle.read(16) != b"SQLite format 3\x00":
                        raise ValueError(
                            "MLB_DB_URL did not return a SQLite database."
                        )
                temporary_path.replace(DB_PATH)
                return
            except Exception as error:
                LOGGER.warning(
                    "Database bootstrap download failed from %s: %s",
                    database_url,
                    error,
                )
            finally:
                if temporary_path.exists():
                    temporary_path.unlink()

        if attempt == attempts - 1:
            break
        time.sleep(retry_delay)
    LOGGER.warning(
        "Database bootstrap did not create %s; continuing with local schema.",
        DB_PATH,
    )


def bootstrap_database():
    if using_turso():
        return
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


def _configure_connection(conn):
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA temp_store = MEMORY")
    if os.environ.get("MLB_DB_DISABLE_WAL", "").strip().lower() not in {
        "1",
        "true",
        "yes",
    }:
        try:
            conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.DatabaseError as error:
            LOGGER.debug("SQLite WAL mode was not enabled: %s", error)
    return conn


def get_connection():
    database_url = _turso_database_url()
    if database_url:
        auth_token = os.environ.get("TURSO_AUTH_TOKEN", "").strip()
        if not auth_token:
            raise RuntimeError(
                "TURSO_AUTH_TOKEN must be set when TURSO_DATABASE_URL is configured."
            )
        return _RemoteConnection(_connect_turso(database_url, auth_token))

    bootstrap_database()
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    return _configure_connection(conn)


def db_cache_key():
    if using_turso():
        return (
            _database_identity(),
            os.environ.get("TURSO_DATA_VERSION", "remote").strip() or "remote",
            SCHEMA_VERSION,
        )

    path = DB_PATH.resolve()
    try:
        stat = path.stat()
    except OSError:
        return (str(path), None, None, SCHEMA_VERSION)

    user_version = None
    try:
        conn = sqlite3.connect(path)
        try:
            user_version = conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        user_version = SCHEMA_VERSION

    return (
        str(path),
        int(stat.st_mtime_ns),
        int(stat.st_size),
        int(user_version or 0),
        SCHEMA_VERSION,
    )


@contextmanager
def transaction():
    if not database_writes_enabled():
        raise RuntimeError(
            "Database writes are disabled because TURSO_READ_ONLY is enabled."
        )
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

            CREATE TABLE IF NOT EXISTS pitch_types (
                pitch_code TEXT PRIMARY KEY,
                pitch_name TEXT,
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

            CREATE TABLE IF NOT EXISTS batter_pitch_type_game_logs (
                game_pk INTEGER,
                game_id TEXT,
                source TEXT,
                game_date TEXT,
                season INTEGER,
                batter_id INTEGER,
                batting_team TEXT,
                pitcher_hand TEXT,
                pitch_code TEXT,
                PA INTEGER,
                AB INTEGER,
                H INTEGER,
                singles INTEGER,
                doubles INTEGER,
                triples INTEGER,
                BB INTEGER,
                HBP INTEGER,
                SO INTEGER,
                HR INTEGER,
                SF INTEGER,
                TB INTEGER,
                PRIMARY KEY (game_pk, batter_id, pitcher_hand, pitch_code)
            );

            CREATE TABLE IF NOT EXISTS batter_pitch_type_stats (
                season INTEGER,
                batter_id INTEGER,
                batter_name TEXT,
                pitcher_hand TEXT,
                pitch_code TEXT,
                pitch_name TEXT,
                PA INTEGER,
                AB INTEGER,
                H INTEGER,
                singles INTEGER,
                doubles INTEGER,
                triples INTEGER,
                BB INTEGER,
                HBP INTEGER,
                SO INTEGER,
                HR INTEGER,
                SF INTEGER,
                TB INTEGER,
                AVG REAL,
                SLG REAL,
                ISO REAL,
                K_pct REAL,
                last_game_date TEXT,
                last_updated TEXT,
                PRIMARY KEY (season, batter_id, pitcher_hand, pitch_code)
            );

            CREATE TABLE IF NOT EXISTS pitcher_pitch_type_game_logs (
                game_pk INTEGER,
                game_id TEXT,
                source TEXT,
                game_date TEXT,
                season INTEGER,
                pitcher_id INTEGER,
                team TEXT,
                opponent TEXT,
                pitch_code TEXT,
                pitch_count INTEGER,
                total_speed REAL,
                measured_pitches INTEGER,
                PRIMARY KEY (game_pk, pitcher_id, pitch_code)
            );

            CREATE TABLE IF NOT EXISTS pitcher_pitch_type_stats (
                season INTEGER,
                pitcher_id INTEGER,
                pitcher_name TEXT,
                pitch_code TEXT,
                pitch_name TEXT,
                pitch_count INTEGER,
                percentage REAL,
                avg_speed REAL,
                last_game_date TEXT,
                last_updated TEXT,
                PRIMARY KEY (season, pitcher_id, pitch_code)
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

            CREATE TABLE IF NOT EXISTS live_game_contacts (
                game_pk INTEGER NOT NULL,
                play_key TEXT NOT NULL,
                play_index INTEGER,
                inning INTEGER,
                half_inning TEXT,
                batting_side TEXT,
                batting_team TEXT,
                batter_id INTEGER,
                batter_name TEXT,
                pitcher_id INTEGER,
                pitcher_name TEXT,
                result_type TEXT,
                result_label TEXT,
                description TEXT,
                runs_scored INTEGER,
                away_score INTEGER,
                home_score INTEGER,
                hit_x REAL,
                hit_y REAL,
                launch_speed REAL,
                launch_angle REAL,
                distance REAL,
                trajectory TEXT,
                hardness TEXT,
                location INTEGER,
                payload_json TEXT,
                updated_at TEXT,
                PRIMARY KEY (game_pk, play_key)
            );

            CREATE TABLE IF NOT EXISTS pitch_level_events (
                game_pk INTEGER NOT NULL,
                game_date TEXT,
                season INTEGER,
                at_bat_number INTEGER NOT NULL,
                pitch_number INTEGER NOT NULL,
                batter_id INTEGER,
                pitcher_id INTEGER,
                batter_side TEXT,
                pitcher_hand TEXT,
                pitch_type TEXT,
                pitch_name TEXT,
                release_speed REAL,
                release_spin_rate REAL,
                pfx_x REAL,
                pfx_z REAL,
                plate_x REAL,
                plate_z REAL,
                zone INTEGER,
                pitch_description TEXT,
                event TEXT,
                launch_speed REAL,
                launch_angle REAL,
                estimated_distance REAL,
                estimated_woba REAL,
                estimated_ba REAL,
                barrel INTEGER,
                hard_hit INTEGER,
                balls INTEGER,
                strikes INTEGER,
                outs INTEGER,
                inning INTEGER,
                rbi INTEGER,
                runs_produced INTEGER,
                updated_at TEXT,
                PRIMARY KEY (game_pk, at_bat_number, pitch_number)
            );

            CREATE TABLE IF NOT EXISTS plate_appearance_sequences (
                game_pk INTEGER NOT NULL,
                game_date TEXT,
                season INTEGER,
                at_bat_number INTEGER NOT NULL,
                batter_id INTEGER,
                pitcher_id INTEGER,
                inning INTEGER,
                outs INTEGER,
                starting_count TEXT,
                final_count TEXT,
                pa_result TEXT,
                rbi INTEGER,
                runs_produced INTEGER,
                pitch_count INTEGER,
                pitch_sequence TEXT,
                launch_speed REAL,
                launch_angle REAL,
                estimated_distance REAL,
                barrel INTEGER,
                hard_hit INTEGER,
                updated_at TEXT,
                PRIMARY KEY (game_pk, at_bat_number)
            );

            CREATE TABLE IF NOT EXISTS bvp_pitch_type_stats (
                season INTEGER,
                batter_id INTEGER,
                pitcher_id INTEGER,
                pitch_type TEXT,
                pitch_name TEXT,
                pitch_count INTEGER,
                usage_pct REAL,
                avg_velocity REAL,
                max_velocity REAL,
                avg_spin_rate REAL,
                horizontal_movement REAL,
                vertical_movement REAL,
                zone_pct REAL,
                chase_pct REAL,
                whiff_pct REAL,
                csw_pct REAL,
                contact_pct REAL,
                hard_hit_pct REAL,
                barrel_pct REAL,
                AVG REAL,
                SLG REAL,
                wOBA REAL,
                xwOBA REAL,
                K_pct REAL,
                balls_in_play INTEGER,
                sample_size TEXT,
                last_game_date TEXT,
                last_updated TEXT,
                PRIMARY KEY (season, batter_id, pitcher_id, pitch_type)
            );

            CREATE TABLE IF NOT EXISTS daily_bullpen_projections (
                game_date TEXT NOT NULL,
                game_pk INTEGER NOT NULL,
                team_id INTEGER NOT NULL,
                pitcher_id INTEGER NOT NULL,
                projected_role TEXT,
                availability_score REAL,
                availability_label TEXT,
                appearance_probability REAL,
                expected_batters_faced_range TEXT,
                recent_workload TEXT,
                projection_reason TEXT,
                projection_timestamp TEXT,
                PRIMARY KEY (game_pk, team_id, pitcher_id)
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
            CREATE INDEX IF NOT EXISTS idx_bpg_logs_batter_pitcher_date_game
                ON batter_pitcher_game_logs(
                    batter_id,
                    pitcher_id,
                    game_date DESC,
                    game_pk DESC
                );
            CREATE INDEX IF NOT EXISTS idx_game_logs_game_date
                ON batter_pitcher_game_logs(game_date);
            CREATE INDEX IF NOT EXISTS idx_batter_streak_logs
                ON batter_pitcher_game_logs(season, batter_id, game_date, game_pk);
            CREATE INDEX IF NOT EXISTS idx_bvp_stats_batter_pitcher
                ON batter_pitcher_stats(batter_id, pitcher_id);
            CREATE INDEX IF NOT EXISTS idx_batter_pitch_type_logs_lookup
                ON batter_pitch_type_game_logs(season, batter_id, pitcher_hand);
            CREATE INDEX IF NOT EXISTS idx_batter_pitch_type_stats_lookup
                ON batter_pitch_type_stats(batter_id, season, pitcher_hand);
            CREATE INDEX IF NOT EXISTS idx_batter_pitch_type_stats_batch
                ON batter_pitch_type_stats(
                    season,
                    batter_id,
                    pitcher_hand,
                    pitch_code
                );
            CREATE INDEX IF NOT EXISTS idx_pitcher_pitch_type_logs_lookup
                ON pitcher_pitch_type_game_logs(season, pitcher_id);
            CREATE INDEX IF NOT EXISTS idx_pitcher_pitch_type_stats_lookup
                ON pitcher_pitch_type_stats(pitcher_id, season);
            CREATE INDEX IF NOT EXISTS idx_pitcher_pitch_type_stats_batch
                ON pitcher_pitch_type_stats(
                    season,
                    pitcher_id,
                    pitch_count DESC
                );
            CREATE INDEX IF NOT EXISTS idx_pitcher_logs_pitcher
                ON pitcher_game_logs(pitcher_id);
            CREATE INDEX IF NOT EXISTS idx_pitcher_logs_opponent
                ON pitcher_game_logs(opponent);
            CREATE INDEX IF NOT EXISTS idx_pitcher_logs_pitcher_opponent_date_game
                ON pitcher_game_logs(
                    pitcher_id,
                    opponent,
                    game_date DESC,
                    game_pk DESC
                );
            CREATE INDEX IF NOT EXISTS idx_pitcher_logs_season_pitcher_date_game
                ON pitcher_game_logs(
                    season,
                    pitcher_id,
                    game_date DESC,
                    game_pk DESC
                );
            CREATE INDEX IF NOT EXISTS idx_pitcher_streak_logs
                ON pitcher_game_logs(season, pitcher_id, game_date);
            CREATE INDEX IF NOT EXISTS idx_pitcher_stats_pitcher_season
                ON pitcher_stats(pitcher_id, season);
            CREATE INDEX IF NOT EXISTS idx_live_game_contacts_game
                ON live_game_contacts(game_pk, inning, play_index);
            CREATE INDEX IF NOT EXISTS idx_pitch_level_batter_pitcher_date
                ON pitch_level_events(batter_id, pitcher_id, game_date);
            CREATE INDEX IF NOT EXISTS idx_pitch_level_pitcher_type_date
                ON pitch_level_events(pitcher_id, pitch_type, game_date);
            CREATE INDEX IF NOT EXISTS idx_pitch_level_batter_type_date
                ON pitch_level_events(batter_id, pitch_type, game_date);
            CREATE INDEX IF NOT EXISTS idx_pitch_level_game_pitch
                ON pitch_level_events(game_pk, at_bat_number, pitch_number);
            CREATE INDEX IF NOT EXISTS idx_pa_sequences_batter_pitcher_date
                ON plate_appearance_sequences(batter_id, pitcher_id, game_date);
            CREATE INDEX IF NOT EXISTS idx_bvp_pitch_type_batter_pitcher
                ON bvp_pitch_type_stats(batter_id, pitcher_id, season);
            CREATE INDEX IF NOT EXISTS idx_bvp_pitch_type_pitcher
                ON bvp_pitch_type_stats(pitcher_id, pitch_type, last_game_date);
            CREATE INDEX IF NOT EXISTS idx_daily_bullpen_team_date
                ON daily_bullpen_projections(team_id, game_date);
            CREATE INDEX IF NOT EXISTS idx_daily_bullpen_game_pitcher
                ON daily_bullpen_projections(game_pk, pitcher_id);
            DROP TABLE IF EXISTS plate_appearances;
            """
        )
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    _INITIALIZED_PATH = _database_identity()


def ensure_database():
    global _INITIALIZED_PATH
    database_identity = _database_identity()
    if database_identity != _INITIALIZED_PATH:
        with _INITIALIZE_LOCK:
            if database_identity == _INITIALIZED_PATH:
                return
            if using_turso():
                with read_connection() as conn:
                    conn.execute("SELECT 1 FROM games LIMIT 1").fetchone()
                _INITIALIZED_PATH = database_identity
            else:
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


def _upsert_pitch_type(conn, pitch_code, pitch_name):
    if pitch_code is None:
        return
    pitch_code = str(pitch_code).strip()
    if not pitch_code:
        return
    conn.execute(
        """
        INSERT INTO pitch_types (pitch_code, pitch_name, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(pitch_code) DO UPDATE SET
            pitch_name = COALESCE(excluded.pitch_name, pitch_types.pitch_name),
            updated_at = excluded.updated_at
        """,
        (pitch_code, pitch_name, now_text()),
    )


def upsert_pitch_type(pitch_code, pitch_name):
    with transaction() as conn:
        _upsert_pitch_type(conn, pitch_code, pitch_name)


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
    conn.execute("DELETE FROM batter_pitch_type_game_logs WHERE game_pk = ?", (int(game_pk),))
    conn.execute("DELETE FROM pitcher_pitch_type_game_logs WHERE game_pk = ?", (int(game_pk),))
    conn.execute("DELETE FROM pitcher_game_logs WHERE game_pk = ?", (int(game_pk),))
    conn.execute("DELETE FROM processed_games WHERE game_pk = ?", (int(game_pk),))


def delete_game_logs(game_pk):
    with transaction() as conn:
        _delete_game_logs(conn, game_pk)


def _nullable_int(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _nullable_float(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def live_contact_play_key(play):
    play = play if isinstance(play, dict) else {}
    hit_data = play.get("hit_data") or {}
    play_index = play.get("play_index")
    if play_index is not None:
        return f"play_index:{play_index}"
    return "|".join(
        str(part or "")
        for part in (
            play.get("inning"),
            play.get("half_inning"),
            (play.get("batter") or {}).get("player_id"),
            (play.get("pitcher") or {}).get("player_id"),
            play.get("result_type"),
            play.get("description"),
            hit_data.get("x"),
            hit_data.get("y"),
            hit_data.get("location"),
        )
    )


def save_live_game_contacts(game_pk, plays):
    """Persist batted-ball contact plays so the Stats tab survives reloads/days."""
    contact_plays = [
        play
        for play in (plays or [])
        if isinstance(play, dict) and play.get("hit_data")
    ]
    if not contact_plays:
        return 0
    if not database_writes_enabled():
        return 0

    rows = []
    for play in contact_plays:
        hit_data = play.get("hit_data") or {}
        batter = play.get("batter") or {}
        pitcher = play.get("pitcher") or {}
        rows.append(
            (
                int(game_pk),
                live_contact_play_key(play),
                _nullable_int(play.get("play_index")),
                _nullable_int(play.get("inning")),
                play.get("half_inning"),
                play.get("batting_side"),
                play.get("batting_team"),
                _nullable_int(batter.get("player_id")),
                batter.get("name"),
                _nullable_int(pitcher.get("player_id")),
                pitcher.get("name"),
                play.get("result_type"),
                play.get("result_label"),
                play.get("description"),
                _nullable_int(play.get("runs_scored")),
                _nullable_int(play.get("away_score")),
                _nullable_int(play.get("home_score")),
                _nullable_float(hit_data.get("x")),
                _nullable_float(hit_data.get("y")),
                _nullable_float(hit_data.get("launch_speed")),
                _nullable_float(hit_data.get("launch_angle")),
                _nullable_float(hit_data.get("distance")),
                hit_data.get("trajectory"),
                hit_data.get("hardness"),
                _nullable_int(hit_data.get("location")),
                json.dumps(play, separators=(",", ":"), default=str),
                now_text(),
            )
        )

    ensure_database()
    with transaction() as conn:
        conn.executemany(
            """
            INSERT INTO live_game_contacts (
                game_pk, play_key, play_index, inning, half_inning,
                batting_side, batting_team, batter_id, batter_name,
                pitcher_id, pitcher_name, result_type, result_label,
                description, runs_scored, away_score, home_score,
                hit_x, hit_y, launch_speed, launch_angle, distance,
                trajectory, hardness, location, payload_json, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(game_pk, play_key) DO UPDATE SET
                play_index = excluded.play_index,
                inning = excluded.inning,
                half_inning = excluded.half_inning,
                batting_side = excluded.batting_side,
                batting_team = excluded.batting_team,
                batter_id = excluded.batter_id,
                batter_name = excluded.batter_name,
                pitcher_id = excluded.pitcher_id,
                pitcher_name = excluded.pitcher_name,
                result_type = excluded.result_type,
                result_label = excluded.result_label,
                description = excluded.description,
                runs_scored = excluded.runs_scored,
                away_score = excluded.away_score,
                home_score = excluded.home_score,
                hit_x = excluded.hit_x,
                hit_y = excluded.hit_y,
                launch_speed = excluded.launch_speed,
                launch_angle = excluded.launch_angle,
                distance = excluded.distance,
                trajectory = excluded.trajectory,
                hardness = excluded.hardness,
                location = excluded.location,
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            """,
            rows,
        )
    return len(rows)


def load_live_game_contacts(game_pk):
    ensure_database()
    with read_connection() as conn:
        rows = conn.execute(
            """
            SELECT payload_json
            FROM live_game_contacts
            WHERE game_pk = ?
            ORDER BY COALESCE(inning, 0), COALESCE(play_index, 0), play_key
            """,
            (int(game_pk),),
        ).fetchall()

    plays = []
    for row in rows:
        try:
            play = json.loads(row["payload_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(play, dict) and play.get("hit_data"):
            plays.append(play)
    return plays


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


def _upsert_batter_pitch_type_game_log(conn, log_row):
    game_pk = int(log_row["game_pk"])
    game_id = log_row.get("game_id") or f"mlb:{game_pk}"
    source = log_row.get("source") or "mlb_statsapi"
    conn.execute(
        """
        INSERT INTO batter_pitch_type_game_logs (
            game_pk, game_id, source, game_date, season, batter_id,
            batting_team, pitcher_hand, pitch_code, PA, AB, H, singles,
            doubles, triples, BB, HBP, SO, HR, SF, TB
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(game_pk, batter_id, pitcher_hand, pitch_code) DO UPDATE SET
            game_id = excluded.game_id,
            source = excluded.source,
            game_date = excluded.game_date,
            season = excluded.season,
            batting_team = excluded.batting_team,
            PA = excluded.PA,
            AB = excluded.AB,
            H = excluded.H,
            singles = excluded.singles,
            doubles = excluded.doubles,
            triples = excluded.triples,
            BB = excluded.BB,
            HBP = excluded.HBP,
            SO = excluded.SO,
            HR = excluded.HR,
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
            log_row.get("batting_team"),
            log_row.get("pitcher_hand"),
            log_row.get("pitch_code"),
            log_row.get("PA", 0),
            log_row.get("AB", 0),
            log_row.get("H", 0),
            log_row.get("singles", 0),
            log_row.get("doubles", 0),
            log_row.get("triples", 0),
            log_row.get("BB", 0),
            log_row.get("HBP", 0),
            log_row.get("SO", 0),
            log_row.get("HR", 0),
            log_row.get("SF", 0),
            log_row.get("TB", 0),
        ),
    )


def upsert_batter_pitch_type_game_log(log_row):
    with transaction() as conn:
        _upsert_batter_pitch_type_game_log(conn, log_row)


def _upsert_pitcher_pitch_type_game_log(conn, log_row):
    game_pk = int(log_row["game_pk"])
    game_id = log_row.get("game_id") or f"mlb:{game_pk}"
    source = log_row.get("source") or "mlb_statsapi"
    conn.execute(
        """
        INSERT INTO pitcher_pitch_type_game_logs (
            game_pk, game_id, source, game_date, season, pitcher_id,
            team, opponent, pitch_code, pitch_count, total_speed,
            measured_pitches
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(game_pk, pitcher_id, pitch_code) DO UPDATE SET
            game_id = excluded.game_id,
            source = excluded.source,
            game_date = excluded.game_date,
            season = excluded.season,
            team = excluded.team,
            opponent = excluded.opponent,
            pitch_count = excluded.pitch_count,
            total_speed = excluded.total_speed,
            measured_pitches = excluded.measured_pitches
        """,
        (
            game_pk,
            game_id,
            source,
            log_row.get("game_date"),
            log_row.get("season"),
            log_row.get("pitcher_id"),
            log_row.get("team"),
            log_row.get("opponent"),
            log_row.get("pitch_code"),
            _nullable_int(log_row.get("pitch_count")) or 0,
            _nullable_float(log_row.get("total_speed")) or 0,
            _nullable_int(log_row.get("measured_pitches")) or 0,
        ),
    )


def upsert_pitcher_pitch_type_game_log(log_row):
    with transaction() as conn:
        _upsert_pitcher_pitch_type_game_log(conn, log_row)


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


def _refresh_completed_game_summaries(
    conn,
    batter_pitcher_logs,
    batter_pitch_type_logs,
    pitcher_pitch_type_logs,
    pitcher_logs,
):
    """Refresh only summary rows touched by one game to protect free quotas."""
    refreshed_at = now_text()
    batter_pitcher_keys = sorted(
        {
            (int(row["batter_id"]), int(row["pitcher_id"]))
            for row in batter_pitcher_logs
            if row.get("batter_id") is not None and row.get("pitcher_id") is not None
        }
    )
    if batter_pitcher_keys:
        conn.executemany(
            "DELETE FROM batter_pitcher_stats WHERE batter_id = ? AND pitcher_id = ?",
            batter_pitcher_keys,
        )
        conn.executemany(
            """
            INSERT INTO batter_pitcher_stats (
                batter_id, pitcher_id, batter_name, pitcher_name,
                PA, AB, H, doubles, triples, BB, HBP, SO, HR, RBI, SF, TB,
                AVG, OBP, SLG, OPS, K_pct, BB_pct, last_game_date, last_updated
            )
            SELECT
                gl.batter_id, gl.pitcher_id, MAX(bp.player_name), MAX(pp.player_name),
                SUM(gl.PA), SUM(gl.AB), SUM(gl.H), SUM(gl.doubles), SUM(gl.triples),
                SUM(gl.BB), SUM(gl.HBP), SUM(gl.SO), SUM(gl.HR), SUM(gl.RBI),
                SUM(gl.SF), SUM(gl.TB),
                CASE WHEN SUM(gl.AB) > 0
                    THEN ROUND(SUM(gl.H) * 1.0 / SUM(gl.AB), 3) ELSE 0 END,
                CASE WHEN SUM(gl.AB) + SUM(gl.BB) + SUM(gl.HBP) + SUM(gl.SF) > 0
                    THEN ROUND(
                        (SUM(gl.H) + SUM(gl.BB) + SUM(gl.HBP)) * 1.0 /
                        (SUM(gl.AB) + SUM(gl.BB) + SUM(gl.HBP) + SUM(gl.SF)), 3
                    ) ELSE 0 END,
                CASE WHEN SUM(gl.AB) > 0
                    THEN ROUND(SUM(gl.TB) * 1.0 / SUM(gl.AB), 3) ELSE 0 END,
                CASE WHEN SUM(gl.AB) > 0
                    AND SUM(gl.AB) + SUM(gl.BB) + SUM(gl.HBP) + SUM(gl.SF) > 0
                    THEN ROUND(
                        (SUM(gl.H) + SUM(gl.BB) + SUM(gl.HBP)) * 1.0 /
                        (SUM(gl.AB) + SUM(gl.BB) + SUM(gl.HBP) + SUM(gl.SF)) +
                        SUM(gl.TB) * 1.0 / SUM(gl.AB), 3
                    ) ELSE 0 END,
                CASE WHEN SUM(gl.PA) > 0
                    THEN ROUND(SUM(gl.SO) * 100.0 / SUM(gl.PA), 2) ELSE 0 END,
                CASE WHEN SUM(gl.PA) > 0
                    THEN ROUND(SUM(gl.BB) * 100.0 / SUM(gl.PA), 2) ELSE 0 END,
                MAX(gl.game_date), ?
            FROM batter_pitcher_game_logs gl
            LEFT JOIN players bp ON gl.batter_id = bp.player_id
            LEFT JOIN players pp ON gl.pitcher_id = pp.player_id
            WHERE gl.batter_id = ? AND gl.pitcher_id = ?
            GROUP BY gl.batter_id, gl.pitcher_id
            """,
            [(refreshed_at, *key) for key in batter_pitcher_keys],
        )

    batter_pitch_type_keys = sorted(
        {
            (
                int(row["season"]),
                int(row["batter_id"]),
                str(row["pitcher_hand"]),
                str(row["pitch_code"]),
            )
            for row in batter_pitch_type_logs
            if all(
                row.get(field) is not None
                for field in ("season", "batter_id", "pitcher_hand", "pitch_code")
            )
        }
    )
    if batter_pitch_type_keys:
        conn.executemany(
            """
            DELETE FROM batter_pitch_type_stats
            WHERE season = ? AND batter_id = ? AND pitcher_hand = ? AND pitch_code = ?
            """,
            batter_pitch_type_keys,
        )
        conn.executemany(
            """
            INSERT INTO batter_pitch_type_stats (
                season, batter_id, batter_name, pitcher_hand, pitch_code,
                pitch_name, PA, AB, H, singles, doubles, triples, BB, HBP,
                SO, HR, SF, TB, AVG, SLG, ISO, K_pct, last_game_date, last_updated
            )
            SELECT
                gl.season, gl.batter_id, MAX(bp.player_name), gl.pitcher_hand,
                gl.pitch_code, COALESCE(MAX(pt.pitch_name), gl.pitch_code),
                SUM(gl.PA), SUM(gl.AB), SUM(gl.H), SUM(gl.singles),
                SUM(gl.doubles), SUM(gl.triples), SUM(gl.BB), SUM(gl.HBP),
                SUM(gl.SO), SUM(gl.HR), SUM(gl.SF), SUM(gl.TB),
                CASE WHEN SUM(gl.AB) > 0
                    THEN ROUND(SUM(gl.H) * 1.0 / SUM(gl.AB), 3) ELSE 0 END,
                CASE WHEN SUM(gl.AB) > 0
                    THEN ROUND(SUM(gl.TB) * 1.0 / SUM(gl.AB), 3) ELSE 0 END,
                CASE WHEN SUM(gl.AB) > 0
                    THEN ROUND((SUM(gl.TB) - SUM(gl.H)) * 1.0 / SUM(gl.AB), 3)
                    ELSE 0 END,
                CASE WHEN SUM(gl.PA) > 0
                    THEN ROUND(SUM(gl.SO) * 100.0 / SUM(gl.PA), 2) ELSE 0 END,
                MAX(gl.game_date), ?
            FROM batter_pitch_type_game_logs gl
            LEFT JOIN players bp ON gl.batter_id = bp.player_id
            LEFT JOIN pitch_types pt ON gl.pitch_code = pt.pitch_code
            WHERE gl.season = ? AND gl.batter_id = ?
                AND gl.pitcher_hand = ? AND gl.pitch_code = ?
            GROUP BY gl.season, gl.batter_id, gl.pitcher_hand, gl.pitch_code
            """,
            [(refreshed_at, *key) for key in batter_pitch_type_keys],
        )

    pitcher_pitch_type_keys = sorted(
        {
            (int(row["season"]), int(row["pitcher_id"]), str(row["pitch_code"]))
            for row in pitcher_pitch_type_logs
            if all(
                row.get(field) is not None
                for field in ("season", "pitcher_id", "pitch_code")
            )
        }
    )
    if pitcher_pitch_type_keys:
        conn.executemany(
            """
            DELETE FROM pitcher_pitch_type_stats
            WHERE season = ? AND pitcher_id = ? AND pitch_code = ?
            """,
            pitcher_pitch_type_keys,
        )
        conn.executemany(
            """
            INSERT INTO pitcher_pitch_type_stats (
                season, pitcher_id, pitcher_name, pitch_code, pitch_name,
                pitch_count, percentage, avg_speed, last_game_date, last_updated
            )
            WITH pitch_totals AS (
                SELECT season, pitcher_id, SUM(pitch_count) AS total_pitches
                FROM pitcher_pitch_type_game_logs
                WHERE season = ? AND pitcher_id = ?
                GROUP BY season, pitcher_id
            )
            SELECT
                gl.season, gl.pitcher_id, MAX(pp.player_name), gl.pitch_code,
                COALESCE(MAX(pt.pitch_name), gl.pitch_code), SUM(gl.pitch_count),
                CASE WHEN MAX(pitch_totals.total_pitches) > 0
                    THEN ROUND(
                        SUM(gl.pitch_count) * 100.0 /
                        MAX(pitch_totals.total_pitches), 1
                    ) ELSE 0 END,
                CASE WHEN SUM(gl.measured_pitches) > 0
                    THEN ROUND(
                        SUM(gl.total_speed) * 1.0 / SUM(gl.measured_pitches), 1
                    ) END,
                MAX(gl.game_date), ?
            FROM pitcher_pitch_type_game_logs gl
            INNER JOIN pitch_totals
                ON pitch_totals.season = gl.season
                AND pitch_totals.pitcher_id = gl.pitcher_id
            LEFT JOIN players pp ON gl.pitcher_id = pp.player_id
            LEFT JOIN pitch_types pt ON gl.pitch_code = pt.pitch_code
            WHERE gl.season = ? AND gl.pitcher_id = ? AND gl.pitch_code = ?
            GROUP BY gl.season, gl.pitcher_id, gl.pitch_code
            """,
            [
                (season, pitcher_id, refreshed_at, season, pitcher_id, pitch_code)
                for season, pitcher_id, pitch_code in pitcher_pitch_type_keys
            ],
        )

    pitcher_keys = sorted(
        {
            (int(row["season"]), int(row["pitcher_id"]))
            for row in pitcher_logs
            if row.get("season") is not None and row.get("pitcher_id") is not None
        }
    )
    if pitcher_keys:
        conn.executemany(
            "DELETE FROM pitcher_stats WHERE season = ? AND pitcher_id = ?",
            pitcher_keys,
        )
        conn.executemany(
            """
            INSERT INTO pitcher_stats (
                season, pitcher_id, pitcher_name, games, starts, IP_outs, IP,
                avg_ip_per_start, avg_pitch_count_per_start,
                BF, H, BB, HBP, SO, HR, R, ER, ERA, WHIP, K_pct, K9,
                projected_ip, projected_pitch_count, projected_ks,
                last_game_date, last_updated
            )
            SELECT
                season, pitcher_id, MAX(pitcher_name), COUNT(*), SUM(is_starter),
                SUM(IP_outs),
                CAST(SUM(IP_outs) / 3 AS INTEGER) + (SUM(IP_outs) % 3) / 10.0,
                CASE WHEN SUM(is_starter) > 0
                    THEN ROUND(
                        SUM(CASE WHEN is_starter = 1 THEN IP_outs ELSE 0 END)
                        / 3.0 / SUM(is_starter), 2
                    ) ELSE ROUND(SUM(IP_outs) / 3.0 / COUNT(*), 2) END,
                ROUND(AVG(CASE WHEN is_starter = 1 THEN pitch_count END), 0),
                SUM(BF), SUM(H), SUM(BB), SUM(HBP), SUM(SO), SUM(HR),
                SUM(R), SUM(ER),
                CASE WHEN SUM(IP_outs) > 0
                    THEN ROUND(SUM(ER) * 27.0 / SUM(IP_outs), 2) ELSE 0 END,
                CASE WHEN SUM(IP_outs) > 0
                    THEN ROUND((SUM(BB) + SUM(H)) * 3.0 / SUM(IP_outs), 2)
                    ELSE 0 END,
                CASE WHEN SUM(BF) > 0
                    THEN ROUND(SUM(SO) * 100.0 / SUM(BF), 2) ELSE 0 END,
                CASE WHEN SUM(IP_outs) > 0
                    THEN ROUND(SUM(SO) * 27.0 / SUM(IP_outs), 2) ELSE 0 END,
                CASE WHEN SUM(is_starter) > 0
                    THEN ROUND(
                        SUM(CASE WHEN is_starter = 1 THEN IP_outs ELSE 0 END)
                        / 3.0 / SUM(is_starter), 2
                    ) ELSE ROUND(SUM(IP_outs) / 3.0 / COUNT(*), 2) END,
                ROUND(AVG(CASE WHEN is_starter = 1 THEN pitch_count END), 0),
                CASE WHEN SUM(IP_outs) > 0
                    THEN ROUND(
                        (CASE WHEN SUM(is_starter) > 0
                            THEN SUM(CASE WHEN is_starter = 1 THEN IP_outs ELSE 0 END)
                                / 3.0 / SUM(is_starter)
                            ELSE SUM(IP_outs) / 3.0 / COUNT(*) END)
                        * (SUM(SO) * 3.0 / SUM(IP_outs)), 2
                    ) ELSE 0 END,
                MAX(game_date), ?
            FROM pitcher_game_logs
            WHERE season = ? AND pitcher_id = ?
            GROUP BY season, pitcher_id
            """,
            [(refreshed_at, *key) for key in pitcher_keys],
        )


def save_completed_game(
    game,
    players,
    batter_pitcher_logs,
    pitcher_logs,
    plate_appearances_loaded,
    batter_pitch_type_logs=None,
    pitcher_pitch_type_logs=None,
    pitch_types=None,
    reprocess_existing=False,
):
    """Persist one completed StatsAPI game as a single atomic transaction."""
    game_pk, game_id, source = _game_identity(game)
    batter_pitch_type_logs = batter_pitch_type_logs or []
    pitcher_pitch_type_logs = pitcher_pitch_type_logs or []
    pitch_types = pitch_types or {}
    with transaction() as conn:
        if reprocess_existing:
            _delete_game_logs(conn, game_pk)
        _upsert_game(conn, game)
        for player_id, player_name in players.items():
            _upsert_player(conn, player_id, player_name)
        for pitch_code, pitch_name in pitch_types.items():
            _upsert_pitch_type(conn, pitch_code, pitch_name)
        for row in batter_pitcher_logs:
            _upsert_batter_pitcher_game_log(conn, row)
        for row in batter_pitch_type_logs:
            _upsert_batter_pitch_type_game_log(conn, row)
        for row in pitcher_pitch_type_logs:
            _upsert_pitcher_pitch_type_game_log(conn, row)
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
        if using_turso():
            _refresh_completed_game_summaries(
                conn,
                batter_pitcher_logs,
                batter_pitch_type_logs,
                pitcher_pitch_type_logs,
                pitcher_logs,
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
        conn.execute("DELETE FROM batter_pitch_type_game_logs WHERE season = ?", (season,))
        conn.execute("DELETE FROM batter_pitch_type_stats WHERE season = ?", (season,))
        conn.execute("DELETE FROM pitcher_pitch_type_game_logs WHERE season = ?", (season,))
        conn.execute("DELETE FROM pitcher_pitch_type_stats WHERE season = ?", (season,))
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


def rebuild_batter_pitch_type_stats():
    with transaction() as conn:
        conn.execute("DELETE FROM batter_pitch_type_stats")
        conn.execute(
            """
            INSERT INTO batter_pitch_type_stats (
                season, batter_id, batter_name, pitcher_hand, pitch_code,
                pitch_name, PA, AB, H, singles, doubles, triples, BB, HBP,
                SO, HR, SF, TB, AVG, SLG, ISO, K_pct, last_game_date,
                last_updated
            )
            SELECT
                gl.season,
                gl.batter_id,
                MAX(bp.player_name),
                gl.pitcher_hand,
                gl.pitch_code,
                COALESCE(MAX(pt.pitch_name), gl.pitch_code),
                SUM(gl.PA),
                SUM(gl.AB),
                SUM(gl.H),
                SUM(gl.singles),
                SUM(gl.doubles),
                SUM(gl.triples),
                SUM(gl.BB),
                SUM(gl.HBP),
                SUM(gl.SO),
                SUM(gl.HR),
                SUM(gl.SF),
                SUM(gl.TB),
                CASE WHEN SUM(gl.AB) > 0
                    THEN ROUND(SUM(gl.H) * 1.0 / SUM(gl.AB), 3) ELSE 0 END,
                CASE WHEN SUM(gl.AB) > 0
                    THEN ROUND(SUM(gl.TB) * 1.0 / SUM(gl.AB), 3) ELSE 0 END,
                CASE WHEN SUM(gl.AB) > 0
                    THEN ROUND(
                        (SUM(gl.TB) - SUM(gl.H)) * 1.0 / SUM(gl.AB),
                        3
                    ) ELSE 0 END,
                CASE WHEN SUM(gl.PA) > 0
                    THEN ROUND(SUM(gl.SO) * 100.0 / SUM(gl.PA), 2) ELSE 0 END,
                MAX(gl.game_date),
                ?
            FROM batter_pitch_type_game_logs gl
            LEFT JOIN players bp ON gl.batter_id = bp.player_id
            LEFT JOIN pitch_types pt ON gl.pitch_code = pt.pitch_code
            GROUP BY gl.season, gl.batter_id, gl.pitcher_hand, gl.pitch_code
            """,
            (now_text(),),
        )


def rebuild_pitcher_pitch_type_stats():
    with transaction() as conn:
        conn.execute("DELETE FROM pitcher_pitch_type_stats")
        conn.execute(
            """
            INSERT INTO pitcher_pitch_type_stats (
                season, pitcher_id, pitcher_name, pitch_code, pitch_name,
                pitch_count, percentage, avg_speed, last_game_date,
                last_updated
            )
            WITH pitch_totals AS (
                SELECT
                    season,
                    pitcher_id,
                    SUM(pitch_count) AS total_pitches
                FROM pitcher_pitch_type_game_logs
                GROUP BY season, pitcher_id
            )
            SELECT
                gl.season,
                gl.pitcher_id,
                MAX(pp.player_name),
                gl.pitch_code,
                COALESCE(MAX(pt.pitch_name), gl.pitch_code),
                SUM(gl.pitch_count),
                CASE WHEN MAX(pitch_totals.total_pitches) > 0
                    THEN ROUND(
                        SUM(gl.pitch_count) * 100.0 /
                        MAX(pitch_totals.total_pitches),
                        1
                    ) ELSE 0 END,
                CASE WHEN SUM(gl.measured_pitches) > 0
                    THEN ROUND(
                        SUM(gl.total_speed) * 1.0 /
                        SUM(gl.measured_pitches),
                        1
                    ) END,
                MAX(gl.game_date),
                ?
            FROM pitcher_pitch_type_game_logs gl
            INNER JOIN pitch_totals
                ON pitch_totals.season = gl.season
                AND pitch_totals.pitcher_id = gl.pitcher_id
            LEFT JOIN players pp ON gl.pitcher_id = pp.player_id
            LEFT JOIN pitch_types pt ON gl.pitch_code = pt.pitch_code
            GROUP BY gl.season, gl.pitcher_id, gl.pitch_code
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
    rebuild_batter_pitch_type_stats()
    rebuild_pitcher_pitch_type_stats()
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
            f"""
            SELECT {", ".join(BVP_STAT_COLUMNS)}
            FROM batter_pitcher_stats
            WHERE batter_id = ? AND pitcher_id = ?
            """,
            (int(batter_id), int(pitcher_id)),
        ).fetchone()
    if row is None:
        return empty_bvp_result("No History")
    return _bvp_result_from_row(row)


def _bvp_result_from_row(row):
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
        "SF": row["SF"],
        "TB": row["TB"],
        "AVG": row["AVG"],
        "OBP": row["OBP"],
        "SLG": row["SLG"],
        "OPS": row["OPS"],
        "K%": row["K_pct"],
        "BB%": row["BB_pct"],
        "last_game_date": row["last_game_date"],
        "matchup_grade": grade_bvp(row["AB"], row["AVG"]),
    }


def get_batter_vs_pitcher_stats_batch_from_db(matchup_pairs):
    ensure_database()
    clean_pairs = []
    seen_pairs = set()
    for batter_id, pitcher_id in matchup_pairs:
        if batter_id is None or pitcher_id is None:
            continue
        try:
            pair = (int(batter_id), int(pitcher_id))
        except (TypeError, ValueError):
            continue
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
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
                SELECT {", ".join(BVP_STAT_COLUMNS)}
                FROM batter_pitcher_stats
                WHERE (batter_id, pitcher_id) IN ({placeholders})
                """,
                params,
            ).fetchall()
            for row in rows:
                results[(row["batter_id"], row["pitcher_id"])] = (
                    _bvp_result_from_row(row)
                )
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


def get_batter_pitch_type_stats_from_db(batter_id, season, pitcher_hand=None):
    if batter_id is None or season is None:
        return []
    rows = get_batter_pitch_type_stats_batch_from_db(
        [batter_id],
        season,
        pitcher_hand=pitcher_hand,
    )
    return [
        {key: value for key, value in row.items() if key != "batter_id"}
        for row in rows
    ]


def get_batter_pitch_type_stats_batch_from_db(
    batter_ids,
    season,
    pitcher_hand=None,
):
    if season is None:
        return []
    clean_ids = []
    seen_ids = set()
    for batter_id in batter_ids:
        if batter_id is None:
            continue
        try:
            numeric_id = int(batter_id)
        except (TypeError, ValueError):
            continue
        if numeric_id in seen_ids:
            continue
        seen_ids.add(numeric_id)
        clean_ids.append(numeric_id)
    if not clean_ids:
        return []

    ensure_database()
    placeholders = ",".join("?" for _ in clean_ids)
    params = [int(season), *clean_ids]
    hand_filter = ""
    if pitcher_hand:
        hand_filter = " AND pitcher_hand = ?"
        params.append(str(pitcher_hand).upper()[:1])
    with read_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT
                batter_id,
                pitch_code,
                COALESCE(pitch_name, pitch_code) AS PITCH,
                pitcher_hand,
                PA,
                AB,
                H,
                singles AS "1B",
                doubles AS "2B",
                triples AS "3B",
                HR,
                SO AS K,
                BB,
                HBP,
                SF,
                TB,
                AVG,
                SLG,
                ISO,
                K_pct AS "K%"
            FROM batter_pitch_type_stats
            WHERE season = ? AND batter_id IN ({placeholders}){hand_filter}
            ORDER BY batter_id, AB DESC, PA DESC, PITCH
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def get_pitcher_pitch_type_stats_from_db(pitcher_id, season):
    if pitcher_id is None or season is None:
        return []
    rows = get_pitcher_pitch_type_stats_batch_from_db([pitcher_id], season)
    return [
        {key: value for key, value in row.items() if key != "pitcher_id"}
        for row in rows
    ]


def get_pitcher_pitch_type_stats_batch_from_db(pitcher_ids, season):
    if season is None:
        return []
    clean_ids = []
    seen_ids = set()
    for pitcher_id in pitcher_ids:
        if pitcher_id is None:
            continue
        try:
            numeric_id = int(pitcher_id)
        except (TypeError, ValueError):
            continue
        if numeric_id in seen_ids:
            continue
        seen_ids.add(numeric_id)
        clean_ids.append(numeric_id)
    if not clean_ids:
        return []

    ensure_database()
    placeholders = ",".join("?" for _ in clean_ids)
    with read_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT
                pitcher_id,
                pitch_code,
                COALESCE(pitch_name, pitch_code) AS PITCH,
                pitch_count AS COUNT,
                percentage AS PERCENTAGE,
                avg_speed AS "AVG SPEED",
                last_game_date
            FROM pitcher_pitch_type_stats
            WHERE season = ? AND pitcher_id IN ({placeholders})
            ORDER BY pitcher_id, pitch_count DESC, PITCH
            """,
            [int(season), *clean_ids],
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
            (
                f"SELECT {', '.join(PITCHER_STAT_COLUMNS)} "
                "FROM pitcher_stats WHERE season = ? AND pitcher_id = ?"
            ),
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


PITCH_LEVEL_COLUMNS = (
    "game_pk",
    "game_date",
    "season",
    "at_bat_number",
    "pitch_number",
    "batter_id",
    "pitcher_id",
    "batter_side",
    "pitcher_hand",
    "pitch_type",
    "pitch_name",
    "release_speed",
    "release_spin_rate",
    "pfx_x",
    "pfx_z",
    "plate_x",
    "plate_z",
    "zone",
    "pitch_description",
    "event",
    "launch_speed",
    "launch_angle",
    "estimated_distance",
    "estimated_woba",
    "estimated_ba",
    "barrel",
    "hard_hit",
    "balls",
    "strikes",
    "outs",
    "inning",
    "rbi",
    "runs_produced",
)

PLATE_SEQUENCE_COLUMNS = (
    "game_pk",
    "game_date",
    "season",
    "at_bat_number",
    "batter_id",
    "pitcher_id",
    "inning",
    "outs",
    "starting_count",
    "final_count",
    "pa_result",
    "rbi",
    "runs_produced",
    "pitch_count",
    "pitch_sequence",
    "launch_speed",
    "launch_angle",
    "estimated_distance",
    "barrel",
    "hard_hit",
)

BVP_PITCH_TYPE_COLUMNS = (
    "season",
    "batter_id",
    "pitcher_id",
    "pitch_type",
    "pitch_name",
    "pitch_count",
    "usage_pct",
    "avg_velocity",
    "max_velocity",
    "avg_spin_rate",
    "horizontal_movement",
    "vertical_movement",
    "zone_pct",
    "chase_pct",
    "whiff_pct",
    "csw_pct",
    "contact_pct",
    "hard_hit_pct",
    "barrel_pct",
    "AVG",
    "SLG",
    "wOBA",
    "xwOBA",
    "K_pct",
    "balls_in_play",
    "sample_size",
    "last_game_date",
)


def _clean_int_values(values):
    clean_values = []
    seen = set()
    for value in values:
        if value is None:
            continue
        try:
            clean_value = int(value)
        except (TypeError, ValueError):
            continue
        if clean_value in seen:
            continue
        seen.add(clean_value)
        clean_values.append(clean_value)
    return clean_values


def save_pitch_level_events(events):
    rows = [dict(row) for row in events or []]
    if not rows:
        return 0
    if not database_writes_enabled():
        return 0
    ensure_database()
    columns = (*PITCH_LEVEL_COLUMNS, "updated_at")
    placeholders = ",".join("?" for _ in columns)
    updates = ", ".join(
        f"{column}=excluded.{column}"
        for column in columns
        if column not in {"game_pk", "at_bat_number", "pitch_number"}
    )
    saved_at = now_text()
    values = [
        tuple(row.get(column) for column in PITCH_LEVEL_COLUMNS) + (saved_at,)
        for row in rows
    ]
    with transaction() as conn:
        conn.executemany(
            f"""
            INSERT INTO pitch_level_events ({", ".join(columns)})
            VALUES ({placeholders})
            ON CONFLICT(game_pk, at_bat_number, pitch_number)
            DO UPDATE SET {updates}
            """,
            values,
        )
    return len(rows)


def save_plate_appearance_sequences(sequences):
    rows = [dict(row) for row in sequences or []]
    if not rows:
        return 0
    if not database_writes_enabled():
        return 0
    ensure_database()
    columns = (*PLATE_SEQUENCE_COLUMNS, "updated_at")
    placeholders = ",".join("?" for _ in columns)
    updates = ", ".join(
        f"{column}=excluded.{column}"
        for column in columns
        if column not in {"game_pk", "at_bat_number"}
    )
    saved_at = now_text()
    values = [
        tuple(row.get(column) for column in PLATE_SEQUENCE_COLUMNS) + (saved_at,)
        for row in rows
    ]
    with transaction() as conn:
        conn.executemany(
            f"""
            INSERT INTO plate_appearance_sequences ({", ".join(columns)})
            VALUES ({placeholders})
            ON CONFLICT(game_pk, at_bat_number)
            DO UPDATE SET {updates}
            """,
            values,
        )
    return len(rows)


def save_bvp_pitch_type_stats(rows):
    rows = [dict(row) for row in rows or []]
    if not rows:
        return 0
    if not database_writes_enabled():
        return 0
    ensure_database()
    columns = (*BVP_PITCH_TYPE_COLUMNS, "last_updated")
    placeholders = ",".join("?" for _ in columns)
    updates = ", ".join(
        f"{column}=excluded.{column}"
        for column in columns
        if column not in {"season", "batter_id", "pitcher_id", "pitch_type"}
    )
    saved_at = now_text()
    values = [
        tuple(row.get(column) for column in BVP_PITCH_TYPE_COLUMNS) + (saved_at,)
        for row in rows
    ]
    with transaction() as conn:
        conn.executemany(
            f"""
            INSERT INTO bvp_pitch_type_stats ({", ".join(columns)})
            VALUES ({placeholders})
            ON CONFLICT(season, batter_id, pitcher_id, pitch_type)
            DO UPDATE SET {updates}
            """,
            values,
        )
    return len(rows)


def get_pitch_level_events_for_matchup(batter_id, pitcher_id):
    if batter_id is None or pitcher_id is None:
        return []
    ensure_database()
    with read_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM pitch_level_events
            WHERE batter_id = ? AND pitcher_id = ?
            ORDER BY game_date DESC, game_pk DESC, at_bat_number, pitch_number
            """,
            (int(batter_id), int(pitcher_id)),
        ).fetchall()
    return [dict(row) for row in rows]


def get_plate_appearance_sequences_for_matchup(batter_id, pitcher_id):
    if batter_id is None or pitcher_id is None:
        return []
    ensure_database()
    with read_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM plate_appearance_sequences
            WHERE batter_id = ? AND pitcher_id = ?
            ORDER BY game_date DESC, game_pk DESC, at_bat_number DESC
            """,
            (int(batter_id), int(pitcher_id)),
        ).fetchall()
    return [dict(row) for row in rows]


def get_bvp_pitch_type_stats_from_db(batter_id, pitcher_id, season=None):
    if batter_id is None or pitcher_id is None:
        return []
    ensure_database()
    params = [int(batter_id), int(pitcher_id)]
    season_filter = ""
    if season is not None:
        season_filter = " AND season = ?"
        params.append(int(season))
    with read_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT
                season,
                batter_id,
                pitcher_id,
                pitch_type,
                COALESCE(pitch_name, pitch_type) AS pitch_name,
                pitch_count,
                usage_pct,
                avg_velocity,
                max_velocity,
                avg_spin_rate,
                horizontal_movement,
                vertical_movement,
                zone_pct,
                chase_pct,
                whiff_pct,
                csw_pct,
                contact_pct,
                hard_hit_pct,
                barrel_pct,
                AVG,
                SLG,
                wOBA,
                xwOBA,
                K_pct AS "K%",
                balls_in_play,
                sample_size,
                last_game_date
            FROM bvp_pitch_type_stats
            WHERE batter_id = ? AND pitcher_id = ?{season_filter}
            ORDER BY pitch_count DESC, pitch_name
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def get_pitcher_game_logs_batch_from_db(pitcher_ids, season=None, through_date=None):
    pitcher_ids = _clean_int_values(pitcher_ids)
    if not pitcher_ids:
        return []
    ensure_database()
    placeholders = ",".join("?" for _ in pitcher_ids)
    params = list(pitcher_ids)
    filters = [f"pitcher_id IN ({placeholders})"]
    if season is not None:
        filters.append("season = ?")
        params.append(int(season))
    if through_date is not None:
        filters.append("game_date <= ?")
        params.append(str(through_date))
    where_clause = " AND ".join(filters)
    with read_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM pitcher_game_logs
            WHERE {where_clause}
            ORDER BY pitcher_id, game_date DESC, game_pk DESC
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def save_daily_bullpen_projections(rows):
    rows = [dict(row) for row in rows or []]
    if not rows:
        return 0
    if not database_writes_enabled():
        return 0
    ensure_database()
    columns = (
        "game_date",
        "game_pk",
        "team_id",
        "pitcher_id",
        "projected_role",
        "availability_score",
        "availability_label",
        "appearance_probability",
        "expected_batters_faced_range",
        "recent_workload",
        "projection_reason",
        "projection_timestamp",
    )
    placeholders = ",".join("?" for _ in columns)
    updates = ", ".join(
        f"{column}=excluded.{column}"
        for column in columns
        if column not in {"game_pk", "team_id", "pitcher_id"}
    )
    values = [
        tuple(row.get(column) for column in columns)
        for row in rows
    ]
    with transaction() as conn:
        conn.executemany(
            f"""
            INSERT INTO daily_bullpen_projections ({", ".join(columns)})
            VALUES ({placeholders})
            ON CONFLICT(game_pk, team_id, pitcher_id)
            DO UPDATE SET {updates}
            """,
            values,
        )
    return len(rows)


def get_daily_bullpen_projection_from_db(game_pk, team_id):
    if game_pk is None or team_id is None:
        return []
    ensure_database()
    with read_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM daily_bullpen_projections
            WHERE game_pk = ? AND team_id = ?
            ORDER BY appearance_probability DESC, projected_role, pitcher_id
            """,
            (int(game_pk), int(team_id)),
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
        "pitch_types",
        "batter_pitch_type_game_logs",
        "batter_pitch_type_stats",
        "pitcher_pitch_type_game_logs",
        "pitcher_pitch_type_stats",
        "pitcher_game_logs",
        "pitcher_stats",
        "pitch_level_events",
        "plate_appearance_sequences",
        "bvp_pitch_type_stats",
        "daily_bullpen_projections",
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

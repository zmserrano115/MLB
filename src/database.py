from pathlib import Path
import sqlite3
from datetime import datetime


DB_PATH = Path("data") / "mlb.db"


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS games (
            game_pk INTEGER PRIMARY KEY,
            game_date TEXT,
            season INTEGER,
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
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS players (
            player_id INTEGER PRIMARY KEY,
            player_name TEXT,
            team TEXT,
            bats TEXT,
            throws TEXT,
            updated_at TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS plate_appearances (
            pa_key TEXT PRIMARY KEY,
            game_pk INTEGER,
            game_date TEXT,
            season INTEGER,
            inning INTEGER,
            half_inning TEXT,
            batter_id INTEGER,
            batter_name TEXT,
            pitcher_id INTEGER,
            pitcher_name TEXT,
            batting_team TEXT,
            pitching_team TEXT,
            event_type TEXT,
            description TEXT,
            is_ab INTEGER,
            is_hit INTEGER,
            is_bb INTEGER,
            is_hbp INTEGER,
            is_so INTEGER,
            is_hr INTEGER,
            rbi INTEGER,
            created_at TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS batter_pitcher_stats (
            batter_id INTEGER,
            pitcher_id INTEGER,
            batter_name TEXT,
            pitcher_name TEXT,
            PA INTEGER,
            AB INTEGER,
            H INTEGER,
            BB INTEGER,
            HBP INTEGER,
            SO INTEGER,
            HR INTEGER,
            RBI INTEGER,
            AVG REAL,
            OBP REAL,
            SLG REAL,
            OPS REAL,
            K_pct REAL,
            BB_pct REAL,
            last_updated TEXT,
            PRIMARY KEY (batter_id, pitcher_id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS refresh_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            refresh_type TEXT,
            refresh_date TEXT,
            games_checked INTEGER,
            plate_appearances_added INTEGER,
            status TEXT,
            message TEXT,
            created_at TEXT
        )
        """
    )

    conn.commit()
    conn.close()


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log_refresh(refresh_type, refresh_date, games_checked, plate_appearances_added, status, message):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO refresh_log (
            refresh_type,
            refresh_date,
            games_checked,
            plate_appearances_added,
            status,
            message,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            refresh_type,
            refresh_date,
            games_checked,
            plate_appearances_added,
            status,
            message,
            now_text(),
        ),
    )

    conn.commit()
    conn.close()


def upsert_game(game):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO games (
            game_pk,
            game_date,
            season,
            away_team,
            home_team,
            away_team_id,
            home_team_id,
            away_probable_pitcher,
            away_probable_pitcher_id,
            home_probable_pitcher,
            home_probable_pitcher_id,
            game_status,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(game_pk) DO UPDATE SET
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
            game.get("game_pk"),
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

    conn.commit()
    conn.close()


def insert_plate_appearance(pa):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT OR IGNORE INTO plate_appearances (
            pa_key,
            game_pk,
            game_date,
            season,
            inning,
            half_inning,
            batter_id,
            batter_name,
            pitcher_id,
            pitcher_name,
            batting_team,
            pitching_team,
            event_type,
            description,
            is_ab,
            is_hit,
            is_bb,
            is_hbp,
            is_so,
            is_hr,
            rbi,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            pa.get("pa_key"),
            pa.get("game_pk"),
            pa.get("game_date"),
            pa.get("season"),
            pa.get("inning"),
            pa.get("half_inning"),
            pa.get("batter_id"),
            pa.get("batter_name"),
            pa.get("pitcher_id"),
            pa.get("pitcher_name"),
            pa.get("batting_team"),
            pa.get("pitching_team"),
            pa.get("event_type"),
            pa.get("description"),
            pa.get("is_ab"),
            pa.get("is_hit"),
            pa.get("is_bb"),
            pa.get("is_hbp"),
            pa.get("is_so"),
            pa.get("is_hr"),
            pa.get("rbi"),
            now_text(),
        ),
    )

    inserted = cur.rowcount
    conn.commit()
    conn.close()

    return inserted


def rebuild_batter_pitcher_stats():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("DELETE FROM batter_pitcher_stats")

    cur.execute(
        """
        INSERT INTO batter_pitcher_stats (
            batter_id,
            pitcher_id,
            batter_name,
            pitcher_name,
            PA,
            AB,
            H,
            BB,
            HBP,
            SO,
            HR,
            RBI,
            AVG,
            OBP,
            SLG,
            OPS,
            K_pct,
            BB_pct,
            last_updated
        )
        SELECT
            batter_id,
            pitcher_id,
            MAX(batter_name) AS batter_name,
            MAX(pitcher_name) AS pitcher_name,
            COUNT(*) AS PA,
            SUM(is_ab) AS AB,
            SUM(is_hit) AS H,
            SUM(is_bb) AS BB,
            SUM(is_hbp) AS HBP,
            SUM(is_so) AS SO,
            SUM(is_hr) AS HR,
            SUM(rbi) AS RBI,

            CASE 
                WHEN SUM(is_ab) > 0 
                THEN ROUND(CAST(SUM(is_hit) AS REAL) / SUM(is_ab), 3)
                ELSE 0.000
            END AS AVG,

            CASE 
                WHEN COUNT(*) > 0 
                THEN ROUND(CAST(SUM(is_hit) + SUM(is_bb) + SUM(is_hbp) AS REAL) / COUNT(*), 3)
                ELSE 0.000
            END AS OBP,

            CASE
                WHEN SUM(is_ab) > 0
                THEN ROUND(CAST(SUM(is_hit) + (SUM(is_hr) * 3) AS REAL) / SUM(is_ab), 3)
                ELSE 0.000
            END AS SLG,

            CASE
                WHEN COUNT(*) > 0 AND SUM(is_ab) > 0
                THEN ROUND(
                    (CAST(SUM(is_hit) + SUM(is_bb) + SUM(is_hbp) AS REAL) / COUNT(*))
                    +
                    (CAST(SUM(is_hit) + (SUM(is_hr) * 3) AS REAL) / SUM(is_ab)),
                    3
                )
                ELSE 0.000
            END AS OPS,

            CASE
                WHEN COUNT(*) > 0
                THEN ROUND(CAST(SUM(is_so) AS REAL) / COUNT(*) * 100, 2)
                ELSE 0.00
            END AS K_pct,

            CASE
                WHEN COUNT(*) > 0
                THEN ROUND(CAST(SUM(is_bb) AS REAL) / COUNT(*) * 100, 2)
                ELSE 0.00
            END AS BB_pct,

            ?
        FROM plate_appearances
        WHERE batter_id IS NOT NULL
          AND pitcher_id IS NOT NULL
        GROUP BY batter_id, pitcher_id
        """,
        (now_text(),),
    )

    conn.commit()
    conn.close()


def get_batter_vs_pitcher_stats_from_db(batter_id, pitcher_id):
    if batter_id is None or pitcher_id is None:
        return empty_bvp_result("No Pitcher ID")

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM batter_pitcher_stats
        WHERE batter_id = ?
          AND pitcher_id = ?
        """,
        (int(batter_id), int(pitcher_id)),
    )

    row = cur.fetchone()
    conn.close()

    if row is None:
        return empty_bvp_result("No History")

    return {
        "PA": row["PA"],
        "AB": row["AB"],
        "H": row["H"],
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
        "matchup_grade": grade_bvp(row["PA"], row["OPS"], row["OBP"]),
    }


def empty_bvp_result(grade):
    return {
        "PA": 0,
        "AB": 0,
        "H": 0,
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


def grade_bvp(pa, ops, obp):
    if pa == 0:
        return "No History"

    if pa < 5:
        return "Small Sample"

    if ops >= 0.900 or obp >= 0.380:
        return "Strong"

    if ops >= 0.750 or obp >= 0.330:
        return "Good"

    if ops >= 0.650 or obp >= 0.300:
        return "Neutral"

    return "Avoid"
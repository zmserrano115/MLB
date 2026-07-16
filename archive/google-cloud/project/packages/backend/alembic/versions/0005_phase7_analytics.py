"""Add persisted Phase 7 research and leaderboard read models.

Revision ID: 0005_phase7_analytics
Revises: 0004_slate_weather_read_models
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_phase7_analytics"
down_revision: str | None = "0004_slate_weather_read_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pitch_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("game_id", sa.BigInteger(), nullable=False),
        sa.Column("game_date", sa.Date(), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("at_bat_number", sa.Integer(), nullable=False),
        sa.Column("pitch_number", sa.Integer(), nullable=False),
        sa.Column("batter_id", sa.BigInteger(), nullable=False),
        sa.Column("pitcher_id", sa.BigInteger(), nullable=False),
        sa.Column("pitch_type", sa.String(8)),
        sa.Column("pitch_name", sa.String(80)),
        sa.Column("description", sa.String(120)),
        sa.Column("event", sa.String(120)),
        sa.Column("release_speed", sa.Numeric(8, 3)),
        sa.Column("plate_x", sa.Numeric(8, 3)),
        sa.Column("plate_z", sa.Numeric(8, 3)),
        sa.Column("launch_speed", sa.Numeric(8, 3)),
        sa.Column("launch_angle", sa.Numeric(8, 3)),
        sa.Column("estimated_distance", sa.Numeric(10, 3)),
        sa.Column("estimated_woba", sa.Numeric(8, 5)),
        sa.Column("barrel", sa.Boolean()),
        sa.Column("hard_hit", sa.Boolean()),
        sa.Column("balls", sa.Integer()),
        sa.Column("strikes", sa.Integer()),
        sa.Column("source_updated_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["batter_id"], ["players.id"]),
        sa.ForeignKeyConstraint(["pitcher_id"], ["players.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("game_id", "at_bat_number", "pitch_number"),
    )
    op.create_index(
        "ix_pitch_events_matchup_date",
        "pitch_events",
        ["batter_id", "pitcher_id", "game_date"],
    )
    op.create_table(
        "plate_appearance_sequences",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("game_id", sa.BigInteger(), nullable=False),
        sa.Column("game_date", sa.Date(), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("at_bat_number", sa.Integer(), nullable=False),
        sa.Column("batter_id", sa.BigInteger(), nullable=False),
        sa.Column("pitcher_id", sa.BigInteger(), nullable=False),
        sa.Column("result", sa.String(120)),
        sa.Column("pitch_count", sa.Integer(), nullable=False),
        sa.Column("pitch_sequence", sa.Text(), nullable=False),
        sa.Column("launch_speed", sa.Numeric(8, 3)),
        sa.Column("launch_angle", sa.Numeric(8, 3)),
        sa.Column("estimated_distance", sa.Numeric(10, 3)),
        sa.Column("barrel", sa.Boolean()),
        sa.Column("hard_hit", sa.Boolean()),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["batter_id"], ["players.id"]),
        sa.ForeignKeyConstraint(["pitcher_id"], ["players.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("game_id", "at_bat_number"),
    )
    op.create_index(
        "ix_pa_sequences_matchup_date",
        "plate_appearance_sequences",
        ["batter_id", "pitcher_id", "game_date"],
    )
    op.create_table(
        "batter_pitch_type_summaries",
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("batter_id", sa.BigInteger(), nullable=False),
        sa.Column("pitcher_id", sa.BigInteger(), nullable=False),
        sa.Column("pitch_type", sa.String(8), nullable=False),
        sa.Column("pitch_name", sa.String(80)),
        sa.Column("pitch_count", sa.Integer(), nullable=False),
        sa.Column("average_velocity", sa.Numeric(8, 3)),
        sa.Column("whiff_percentage", sa.Numeric(8, 5)),
        sa.Column("hard_hit_percentage", sa.Numeric(8, 5)),
        sa.Column("barrel_percentage", sa.Numeric(8, 5)),
        sa.Column("expected_woba", sa.Numeric(8, 5)),
        sa.Column("last_game_date", sa.Date()),
        sa.Column("generation", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["batter_id"], ["players.id"]),
        sa.ForeignKeyConstraint(["pitcher_id"], ["players.id"]),
        sa.PrimaryKeyConstraint("season", "batter_id", "pitcher_id", "pitch_type"),
    )
    op.create_table(
        "batter_season_summaries",
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("batter_id", sa.BigInteger(), nullable=False),
        sa.Column("team_id", sa.BigInteger()),
        sa.Column("games", sa.Integer(), nullable=False),
        *[
            sa.Column(name, sa.BigInteger(), nullable=False)
            for name in (
                "pa",
                "ab",
                "hits",
                "doubles",
                "triples",
                "walks",
                "hit_by_pitch",
                "strikeouts",
                "home_runs",
                "rbi",
                "total_bases",
            )
        ],
        sa.Column("last_game_date", sa.Date()),
        sa.Column("generation", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["batter_id"], ["players.id"]),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"]),
        sa.PrimaryKeyConstraint("season", "batter_id"),
    )
    op.create_index("ix_batter_season_leaders", "batter_season_summaries", ["season", "pa"])
    op.create_table(
        "team_season_summaries",
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        sa.Column("games", sa.Integer(), nullable=False),
        *[
            sa.Column(name, sa.BigInteger(), nullable=False)
            for name in (
                "pa",
                "runs",
                "hits",
                "walks",
                "strikeouts",
                "home_runs",
                "innings_outs",
                "runs_allowed",
                "earned_runs_allowed",
                "hits_allowed",
                "walks_allowed",
                "strikeouts_pitched",
                "home_runs_allowed",
            )
        ],
        sa.Column("last_game_date", sa.Date()),
        sa.Column("generation", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"]),
        sa.PrimaryKeyConstraint("season", "team_id"),
    )
    op.create_table(
        "streak_summaries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("through_date", sa.Date(), nullable=False),
        sa.Column("group_name", sa.String(24), nullable=False),
        sa.Column("metric", sa.String(48), nullable=False),
        sa.Column("subject_key", sa.String(80), nullable=False),
        sa.Column("player_id", sa.BigInteger()),
        sa.Column("team_id", sa.BigInteger()),
        sa.Column("streak", sa.Integer(), nullable=False),
        sa.Column("last_game_date", sa.Date()),
        sa.Column("generation", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"]),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("through_date", "group_name", "metric", "subject_key"),
    )
    op.create_index(
        "ix_streak_leaderboard",
        "streak_summaries",
        ["through_date", "group_name", "metric", "streak"],
    )

    _build_initial_summaries()


def _build_initial_summaries() -> None:
    op.execute(
        """
        INSERT INTO batter_season_summaries (
            season, batter_id, team_id, games, pa, ab, hits, doubles, triples, walks,
            hit_by_pitch, strikeouts, home_runs, rbi, total_bases, last_game_date, generation
        )
        SELECT season, batter_id,
               (array_agg(batting_team_id ORDER BY game_date DESC)
                   FILTER (WHERE batting_team_id IS NOT NULL))[1],
               COUNT(DISTINCT game_id), SUM(pa), SUM(ab), SUM(hits), SUM(doubles),
               SUM(triples), SUM(walks), SUM(hit_by_pitch), SUM(strikeouts),
               SUM(home_runs), SUM(rbi), SUM(total_bases), MAX(game_date), 'phase7-bootstrap'
        FROM batter_pitcher_game_logs
        GROUP BY season, batter_id
        """
    )
    op.execute(
        """
        WITH batting AS (
            SELECT season, batting_team_id AS team_id, COUNT(DISTINCT game_id) AS games,
                   SUM(pa) AS pa, SUM(rbi) AS runs, SUM(hits) AS hits, SUM(walks) AS walks,
                   SUM(strikeouts) AS strikeouts, SUM(home_runs) AS home_runs,
                   MAX(game_date) AS last_game_date
            FROM batter_pitcher_game_logs WHERE batting_team_id IS NOT NULL
            GROUP BY season, batting_team_id
        ), pitching AS (
            SELECT season, team_id, COUNT(DISTINCT game_id) AS games,
                   SUM(innings_outs) AS innings_outs, SUM(runs) AS runs_allowed,
                   SUM(earned_runs) AS earned_runs_allowed, SUM(hits) AS hits_allowed,
                   SUM(walks) AS walks_allowed, SUM(strikeouts) AS strikeouts_pitched,
                   SUM(home_runs) AS home_runs_allowed, MAX(game_date) AS last_game_date
            FROM pitcher_game_logs WHERE team_id IS NOT NULL GROUP BY season, team_id
        )
        INSERT INTO team_season_summaries (
            season, team_id, games, pa, runs, hits, walks, strikeouts, home_runs,
            innings_outs, runs_allowed, earned_runs_allowed, hits_allowed, walks_allowed,
            strikeouts_pitched, home_runs_allowed, last_game_date, generation
        )
        SELECT COALESCE(b.season, p.season), COALESCE(b.team_id, p.team_id),
               GREATEST(COALESCE(b.games, 0), COALESCE(p.games, 0)),
               COALESCE(b.pa, 0), COALESCE(b.runs, 0), COALESCE(b.hits, 0),
               COALESCE(b.walks, 0), COALESCE(b.strikeouts, 0), COALESCE(b.home_runs, 0),
               COALESCE(p.innings_outs, 0), COALESCE(p.runs_allowed, 0),
               COALESCE(p.earned_runs_allowed, 0), COALESCE(p.hits_allowed, 0),
               COALESCE(p.walks_allowed, 0), COALESCE(p.strikeouts_pitched, 0),
               COALESCE(p.home_runs_allowed, 0),
               GREATEST(b.last_game_date, p.last_game_date), 'phase7-bootstrap'
        FROM batting b FULL OUTER JOIN pitching p
          ON p.season = b.season AND p.team_id = b.team_id
        """
    )
    op.execute(_BATTER_STREAK_SQL)
    op.execute(_PITCHER_STREAK_SQL)
    op.execute(_TEAM_STREAK_SQL)


_BATTER_STREAK_SQL = """
WITH game_stats AS (
    SELECT batter_id, game_id, game_date, SUM(hits) hits, SUM(home_runs) home_runs,
           SUM(total_bases) total_bases, SUM(rbi) rbi
    FROM batter_pitcher_game_logs GROUP BY batter_id, game_id, game_date
), expanded AS (
    SELECT gs.*, m.metric, m.achieved
    FROM game_stats gs CROSS JOIN LATERAL (VALUES
        ('hit', gs.hits >= 1), ('home_run', gs.home_runs >= 1),
        ('two_total_bases', gs.total_bases >= 2), ('rbi', gs.rbi >= 1)
    ) m(metric, achieved)
), ordered AS (
    SELECT *, SUM(CASE WHEN achieved THEN 0 ELSE 1 END) OVER (
        PARTITION BY batter_id, metric ORDER BY game_date DESC, game_id DESC
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    ) AS prior_misses
    FROM expanded
), active AS (
    SELECT batter_id, metric, MAX(game_date) through_date,
           COUNT(*) FILTER (WHERE achieved AND COALESCE(prior_misses, 0) = 0) streak
    FROM ordered GROUP BY batter_id, metric
)
INSERT INTO streak_summaries (
    through_date, group_name, metric, subject_key, player_id, streak, last_game_date, generation
)
SELECT through_date, 'batter', metric, 'player:' || batter_id, batter_id, streak,
       through_date, 'phase7-bootstrap'
FROM active WHERE streak > 0
"""

_PITCHER_STREAK_SQL = """
WITH expanded AS (
    SELECT pg.*, m.metric, m.achieved
    FROM pitcher_game_logs pg CROSS JOIN LATERAL (VALUES
        ('five_strikeouts', pg.strikeouts >= 5), ('seven_strikeouts', pg.strikeouts >= 7),
        ('scoreless', pg.earned_runs = 0)
    ) m(metric, achieved)
), ordered AS (
    SELECT *, SUM(CASE WHEN achieved THEN 0 ELSE 1 END) OVER (
        PARTITION BY pitcher_id, metric ORDER BY game_date DESC, game_id DESC
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    ) AS prior_misses
    FROM expanded
), active AS (
    SELECT pitcher_id, metric, MAX(game_date) through_date,
           COUNT(*) FILTER (WHERE achieved AND COALESCE(prior_misses, 0) = 0) streak
    FROM ordered GROUP BY pitcher_id, metric
)
INSERT INTO streak_summaries (
    through_date, group_name, metric, subject_key, player_id, streak, last_game_date, generation
)
SELECT through_date, 'pitcher', metric, 'player:' || pitcher_id, pitcher_id, streak,
       through_date, 'phase7-bootstrap'
FROM active WHERE streak > 0
"""

_TEAM_STREAK_SQL = """
WITH results AS (
    SELECT id game_id, game_date, home_team_id team_id, (home_score > away_score) won
    FROM games WHERE home_score IS NOT NULL AND away_score IS NOT NULL
    UNION ALL
    SELECT id, game_date, away_team_id, (away_score > home_score)
    FROM games WHERE home_score IS NOT NULL AND away_score IS NOT NULL
), ordered AS (
    SELECT *, SUM(CASE WHEN won THEN 0 ELSE 1 END) OVER (
        PARTITION BY team_id ORDER BY game_date DESC, game_id DESC
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    ) AS prior_losses
    FROM results
), active AS (
    SELECT team_id, MAX(game_date) through_date,
           COUNT(*) FILTER (WHERE won AND COALESCE(prior_losses, 0) = 0) streak
    FROM ordered GROUP BY team_id
)
INSERT INTO streak_summaries (
    through_date, group_name, metric, subject_key, team_id, streak, last_game_date, generation
)
SELECT through_date, 'team', 'wins', 'team:' || team_id, team_id, streak,
       through_date, 'phase7-bootstrap'
FROM active WHERE streak > 0
"""


def downgrade() -> None:
    op.drop_index("ix_streak_leaderboard", table_name="streak_summaries")
    op.drop_table("streak_summaries")
    op.drop_table("team_season_summaries")
    op.drop_index("ix_batter_season_leaders", table_name="batter_season_summaries")
    op.drop_table("batter_season_summaries")
    op.drop_table("batter_pitch_type_summaries")
    op.drop_index("ix_pa_sequences_matchup_date", table_name="plate_appearance_sequences")
    op.drop_table("plate_appearance_sequences")
    op.drop_index("ix_pitch_events_matchup_date", table_name="pitch_events")
    op.drop_table("pitch_events")

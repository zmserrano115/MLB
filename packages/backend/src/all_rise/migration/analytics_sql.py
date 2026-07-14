"""Idempotent SQL used after legacy fact imports to rebuild Phase 7 read models."""

BATTER_SUMMARY_SQL = """
INSERT INTO batter_season_summaries (
    season, batter_id, team_id, games, pa, ab, hits, doubles, triples, walks,
    hit_by_pitch, strikeouts, home_runs, rbi, total_bases, last_game_date, generation
)
SELECT season, batter_id,
       (array_agg(batting_team_id ORDER BY game_date DESC)
           FILTER (WHERE batting_team_id IS NOT NULL))[1],
       COUNT(DISTINCT game_id), SUM(pa), SUM(ab), SUM(hits), SUM(doubles),
       SUM(triples), SUM(walks), SUM(hit_by_pitch), SUM(strikeouts), SUM(home_runs),
       SUM(rbi), SUM(total_bases), MAX(game_date), %(generation)s
FROM batter_pitcher_game_logs GROUP BY season, batter_id
"""

TEAM_SUMMARY_SQL = """
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
       GREATEST(COALESCE(b.games, 0), COALESCE(p.games, 0)), COALESCE(b.pa, 0),
       COALESCE(b.runs, 0), COALESCE(b.hits, 0), COALESCE(b.walks, 0),
       COALESCE(b.strikeouts, 0), COALESCE(b.home_runs, 0),
       COALESCE(p.innings_outs, 0), COALESCE(p.runs_allowed, 0),
       COALESCE(p.earned_runs_allowed, 0), COALESCE(p.hits_allowed, 0),
       COALESCE(p.walks_allowed, 0), COALESCE(p.strikeouts_pitched, 0),
       COALESCE(p.home_runs_allowed, 0), GREATEST(b.last_game_date, p.last_game_date),
       %(generation)s
FROM batting b FULL OUTER JOIN pitching p
  ON p.season = b.season AND p.team_id = b.team_id
"""

BATTER_STREAK_SQL = """
WITH game_stats AS (
    SELECT batter_id, game_id, game_date, SUM(hits) hits, SUM(home_runs) home_runs,
           SUM(total_bases) total_bases, SUM(rbi) rbi
    FROM batter_pitcher_game_logs GROUP BY batter_id, game_id, game_date
), expanded AS (
    SELECT gs.*, m.metric, m.achieved FROM game_stats gs CROSS JOIN LATERAL (VALUES
        ('hit', gs.hits >= 1), ('home_run', gs.home_runs >= 1),
        ('two_total_bases', gs.total_bases >= 2), ('rbi', gs.rbi >= 1)
    ) m(metric, achieved)
), ordered AS (
    SELECT *, SUM(CASE WHEN achieved THEN 0 ELSE 1 END) OVER (
        PARTITION BY batter_id, metric ORDER BY game_date DESC, game_id DESC
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prior_misses FROM expanded
), active AS (
    SELECT batter_id, metric, MAX(game_date) through_date,
           COUNT(*) FILTER (WHERE achieved AND COALESCE(prior_misses, 0) = 0) streak
    FROM ordered GROUP BY batter_id, metric
)
INSERT INTO streak_summaries (
    through_date, group_name, metric, subject_key, player_id, streak, last_game_date, generation
)
SELECT through_date, 'batter', metric, 'player:' || batter_id, batter_id, streak,
       through_date, %(generation)s FROM active WHERE streak > 0
"""

PITCHER_STREAK_SQL = """
WITH expanded AS (
    SELECT pg.*, m.metric, m.achieved FROM pitcher_game_logs pg CROSS JOIN LATERAL (VALUES
        ('five_strikeouts', pg.strikeouts >= 5),
        ('seven_strikeouts', pg.strikeouts >= 7), ('scoreless', pg.earned_runs = 0)
    ) m(metric, achieved)
), ordered AS (
    SELECT *, SUM(CASE WHEN achieved THEN 0 ELSE 1 END) OVER (
        PARTITION BY pitcher_id, metric ORDER BY game_date DESC, game_id DESC
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prior_misses FROM expanded
), active AS (
    SELECT pitcher_id, metric, MAX(game_date) through_date,
           COUNT(*) FILTER (WHERE achieved AND COALESCE(prior_misses, 0) = 0) streak
    FROM ordered GROUP BY pitcher_id, metric
)
INSERT INTO streak_summaries (
    through_date, group_name, metric, subject_key, player_id, streak, last_game_date, generation
)
SELECT through_date, 'pitcher', metric, 'player:' || pitcher_id, pitcher_id, streak,
       through_date, %(generation)s FROM active WHERE streak > 0
"""

TEAM_STREAK_SQL = """
WITH results AS (
    SELECT id game_id, game_date, home_team_id team_id, (home_score > away_score) won
    FROM games WHERE home_score IS NOT NULL AND away_score IS NOT NULL
    UNION ALL
    SELECT id, game_date, away_team_id, (away_score > home_score)
    FROM games WHERE home_score IS NOT NULL AND away_score IS NOT NULL
), ordered AS (
    SELECT *, SUM(CASE WHEN won THEN 0 ELSE 1 END) OVER (
        PARTITION BY team_id ORDER BY game_date DESC, game_id DESC
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prior_losses FROM results
), active AS (
    SELECT team_id, MAX(game_date) through_date,
           COUNT(*) FILTER (WHERE won AND COALESCE(prior_losses, 0) = 0) streak
    FROM ordered GROUP BY team_id
)
INSERT INTO streak_summaries (
    through_date, group_name, metric, subject_key, team_id, streak, last_game_date, generation
)
SELECT through_date, 'team', 'wins', 'team:' || team_id, team_id, streak,
       through_date, %(generation)s FROM active WHERE streak > 0
"""

PHASE7_REBUILD_SQL = (
    BATTER_SUMMARY_SQL,
    TEAM_SUMMARY_SQL,
    BATTER_STREAK_SQL,
    PITCHER_STREAK_SQL,
    TEAM_STREAK_SQL,
)

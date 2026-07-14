# All Rise Analytics

> The native Next.js/API/worker migration stack now covers the slate, weather,
> research, analytics, and live Game Center. The parameterized Phase 9 GCP
> foundations are ready for a reviewed staging plan. Streamlit remains the
> rollback target until the Cloud Run canary and observation gates pass. See
> [`docs/architecture/`](docs/architecture/README.md) for the audited plan and
> [`docs/runbooks/local-development.md`](docs/runbooks/local-development.md) for
> the new local stack.

This Streamlit app uses:

- Retrosheet yearly CSV archives for historical 2005-2025 data.
- The Chadwick Register to map Retrosheet player IDs to MLBAM IDs.
- MLB StatsAPI for live schedules, probable pitchers, current rosters/stats,
  and completed current-season games.
- Open-Meteo for game-time stadium weather forecasts.
- SQLite for career BvP summaries, BvP game logs, pitcher game logs, and
  pitcher season summaries.

Raw play-by-play is streamed from each Retrosheet ZIP, aggregated, and then
discarded. SQLite does not contain a raw plate-appearance table.

## Live Weather Context

The live slate uses the scheduled MLB venue's coordinates, elevation, center-
field azimuth, roof type, and first-pitch time. Forecast wind is projected
relative to the field so matchup tables can distinguish wind blowing out, in,
or across the diamond.

Outdoor hitter rankings include a capped wind and air-density adjustment.
Pitcher strikeout scores receive only a small inverse run-environment
adjustment because wind does not directly change strikeout skill. Retractable-
roof games display the forecast but remain projection-neutral while roof
status is unknown. These are bounded matchup heuristics rather than calibrated
batted-ball or sportsbook projections.

Probable pitchers and forecasts use a 15-minute Streamlit cache and can be
refreshed immediately with the **Refresh Live Context** button. The nightly
database job remains limited to completed-game history.

## Install

```powershell
python -m pip install -r requirements.txt
```

For development and tests:

```powershell
python -m pip install -r requirements-dev.txt
```

## Historical Backfill

The default command imports regular-season history from 2005 through 2025:

```powershell
python backfill_database.py
```

Useful variants:

```powershell
python backfill_database.py --start-season 2025 --end-season 2025
python backfill_database.py --start-season 2005 --end-season 2025 --db data/mlb.db
```

The importer downloads one official `YYYYcsvs.zip` archive at a time, reads
`gameinfo`, `plays`, and `pitching`, and removes the temporary ZIP after that
season commits successfully. Use `--archive-dir` for predownloaded archives or
`--chadwick-dir` for local `people-0.csv` through `people-f.csv` files.

## Nightly Refresh

The nightly job checks final games only. It does not build future schedules or
precomputed matchup files:

```powershell
python refresh_nightly.py
python refresh_nightly.py --date 2026-06-06 --lookback-days 3
python refresh_nightly.py --date 2026-06-06 --season-to-date
```

The lookback catches games whose final status arrived late. Existing games are
idempotently skipped unless `--reprocess-existing` is supplied. Repository
pushes run the season-to-date mode so a new deployment cannot miss earlier
current-season games; scheduled nightly runs use the three-day lookback.

## Cloud Database

A full 2005-2025 SQLite file is too large for GitHub's normal file limit.
Create a compressed copy and publish both assets on a release tagged
`mlb-data`:

```powershell
python -c "import gzip, shutil; shutil.copyfileobj(open('data/mlb.db','rb'), gzip.open('data/mlb.db.gz','wb'))"
gh release create mlb-data data/mlb.db data/mlb.db.gz --title "MLB data" --notes "SQLite data"
```

For later manual replacements:

```powershell
python -c "import gzip, shutil; shutil.copyfileobj(open('data/mlb.db','rb'), gzip.open('data/mlb.db.gz','wb'))"
gh release upload mlb-data data/mlb.db data/mlb.db.gz --clobber
```

Set this Streamlit secret to the public release asset URL:

```toml
MLB_DB_URL = "https://github.com/OWNER/REPO/releases/download/mlb-data/mlb.db.gz"
```

On a clean deployment, the app downloads and transparently expands the
compressed database before opening SQLite. Raw `.db` URLs remain supported.
The nightly GitHub Action publishes both raw and compressed release assets.

## Verification

```powershell
python -m compileall -q app.py refresh_database.py refresh_nightly.py backfill_database.py src tests
python -m pytest -q
python backfill_database.py --help
python refresh_nightly.py --help
```

## Data Attribution

Historical game information was obtained free of charge from and is
copyrighted by [Retrosheet](https://www.retrosheet.org/).
Player ID cross-references come from the
[Chadwick Register](https://github.com/chadwickbureau/register).
Forecast data comes from [Open-Meteo](https://open-meteo.com/).

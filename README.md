# All Rise Analytics

This Streamlit app uses:

- Retrosheet yearly CSV archives for historical 2005-2025 data.
- The Chadwick Register to map Retrosheet player IDs to MLBAM IDs.
- MLB StatsAPI for live schedules, probable pitchers, current rosters/stats,
  and completed current-season games.
- SQLite for career BvP summaries, BvP game logs, pitcher game logs, and
  pitcher season summaries.

Raw play-by-play is streamed from each Retrosheet ZIP, aggregated, and then
discarded. SQLite does not contain a raw plate-appearance table.

## Install

```powershell
python -m pip install -r requirements.txt
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
```

The lookback catches games whose final status arrived late. Existing games are
idempotently skipped unless `--reprocess-existing` is supplied.

## Cloud Database

A full 2005-2025 SQLite file is too large for GitHub's normal file limit.
Publish it as the `mlb.db` asset on a release tagged `mlb-data`:

```powershell
gh release create mlb-data data/mlb.db --title "MLB data" --notes "SQLite data"
```

For later manual replacements:

```powershell
gh release upload mlb-data data/mlb.db --clobber
```

Set this Streamlit secret to the public release asset URL:

```toml
MLB_DB_URL = "https://github.com/OWNER/REPO/releases/download/mlb-data/mlb.db"
```

On a clean deployment, the app downloads the database once before opening
SQLite. The nightly GitHub Action downloads the same release asset, updates
completed games, and replaces the asset.

## Verification

```powershell
python -m compileall -q app.py refresh_database.py refresh_nightly.py backfill_database.py src tests
python -m unittest discover -s tests -v
python backfill_database.py --help
python refresh_nightly.py --help
```

## Data Attribution

Historical game information was obtained free of charge from and is
copyrighted by [Retrosheet](https://www.retrosheet.org/).
Player ID cross-references come from the
[Chadwick Register](https://github.com/chadwickbureau/register).

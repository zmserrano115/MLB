# All Rise Analytics

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

The runtime dependencies in `requirements.txt` cover every third-party import
used by the app and refresh scripts. Python 3.12 is used by both Streamlit
Cloud and the Docker image.

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

`MLB_DB_PATH` controls the local SQLite location. It defaults to
`data/mlb.db`; the Elastic Beanstalk container sets it to
`/app/data/mlb.db`. `MLB_DB_URL` controls the bootstrap download URL.

## AWS Elastic Beanstalk

The repository includes a single-container Docker deployment for Elastic
Beanstalk. It builds the image directly from `Dockerfile`, so ECR is not
required. The container runs as a non-root user, listens on `0.0.0.0:8080`,
keeps Streamlit CORS and XSRF protection enabled, and exposes
`/_stcore/health` for health checks.

The local SQLite file is intentionally excluded from Docker and Elastic
Beanstalk bundles. Each new instance downloads the published release asset on
first start. Because that file is instance-local and ephemeral, the included
Elastic Beanstalk configuration holds the environment at one instance. Move
to shared durable storage before increasing `MaxSize`.

### Prerequisites

- Docker for local image testing.
- AWS CLI and the Elastic Beanstalk CLI (`eb`) installed locally.
- An authenticated AWS CLI profile or AWS IAM Identity Center session.
- A deployment IAM user or role with least-privilege access to Elastic
  Beanstalk and its CloudFormation, EC2, Auto Scaling, Elastic Load Balancing,
  S3, and CloudWatch Logs resources, plus `iam:PassRole` for the two roles
  below. ECR permissions are needed only if the deployment is later changed
  to pull a registry image.
- An Elastic Beanstalk service role, normally
  `aws-elasticbeanstalk-service-role`, with
  `AWSElasticBeanstalkEnhancedHealth` and
  `AWSElasticBeanstalkManagedUpdatesCustomerRolePolicy`.
- An EC2 instance profile, normally `aws-elasticbeanstalk-ec2-role`, with
  `AWSElasticBeanstalkWebTier` and only the additional permissions the app
  needs for Secrets Manager or Parameter Store.

Do not commit or paste AWS access keys, API keys, `.env` files,
`.streamlit/secrets.toml`, or downloaded credential files. Prefer temporary
credentials from an IAM role or IAM Identity Center. Store future application
secrets in AWS Secrets Manager or SSM Parameter Store and expose them through
Elastic Beanstalk environment secrets. For a future GitHub Actions deployment,
prefer GitHub OIDC; if long-lived credentials are unavoidable, store them only
in GitHub Secrets.

### Test The Container

```powershell
docker build -t all-rise-analytics .
docker run --rm -p 8080:8080 `
  -e MLB_DB_PATH=/app/data/mlb.db `
  -e MLB_DB_URL=https://github.com/zmserrano115/MLB/releases/download/mlb-data/mlb.db `
  all-rise-analytics
```

Open `http://localhost:8080` and verify the health endpoint:

```powershell
Invoke-WebRequest http://localhost:8080/_stcore/health
```

### First Deployment

The examples use `us-west-2`, the selected region for this deployment. Change
it before `eb init` if another region is required.

```powershell
aws sts get-caller-identity
aws configure get region
eb --version

eb init all-rise-analytics --platform docker --region us-west-2
eb create all-rise-analytics-prod `
  --elb-type application `
  --service-role aws-elasticbeanstalk-service-role `
  --instance_profile aws-elasticbeanstalk-ec2-role

eb setenv `
  APP_TIMEZONE=America/Denver `
  MLB_DB_PATH=/app/data/mlb.db `
  MLB_DB_URL=https://github.com/zmserrano115/MLB/releases/download/mlb-data/mlb.db

eb deploy --process
eb status
eb health
eb logs --cloudwatch-logs enable
eb open
```

The first start can take several minutes while the SQLite release asset
downloads. The Docker health check allows a five-minute startup period.

In the Elastic Beanstalk console, enable an Application Load Balancer HTTPS
listener with an ACM certificate, redirect HTTP to HTTPS, and restrict the
EC2 security group so application instances accept traffic only from the load
balancer security group. Keep CloudWatch log streaming enabled and create
alarms for environment health and HTTP 5xx responses.

For later deployments:

```powershell
eb deploy --process
eb health
```

Do not remove or disable the existing Streamlit Cloud deployment during this
migration. Verify the AWS URL, HTTPS, health checks, logs, database bootstrap,
and live application behavior first. Keep Streamlit Cloud available as the
rollback target until AWS production traffic has been confirmed successful.

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
Forecast data comes from [Open-Meteo](https://open-meteo.com/).

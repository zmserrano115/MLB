# Phase 7 Next.js migration status

Status: complete. Every non-live route now has a persisted FastAPI contract and
a native Next.js page. Streamlit remains only as the Phase 8 live-game fallback;
production request paths do not read SQLite or call upstream providers.

## Completed foundation

- Replaced the placeholder Next.js page with a responsive All Rise shell,
  navigation, footer, operational home, and global failure/loading states.
- Preserved the original website's navy, white, gray, and blue palette. Orange
  is intentionally excluded and protected by a regression test.
- Added reusable UI tokens and components in `packages/ui`.
- Generated TypeScript API contracts from the FastAPI OpenAPI document in
  `packages/shared-types` rather than duplicating response shapes by hand.
- Added a timeout-aware, server-side API client for readiness and source-status
  data, including ready, empty, stale, unavailable, and malformed-response
  handling.
- Migrated `/methodology` as the first complete static page.
- Added canonical, allowlisted URL-state handoffs for the remaining analytical
  routes. Unknown routes return the Next.js not-found view; arbitrary query
  parameters are not forwarded to the legacy application.
- Added site metadata and a palette-matched social preview image.
- Added migration `0004_slate_weather_read_models`, including venues, game
  schedule/score fields, and versioned weather snapshots.
- Added cached, persisted read APIs for game lists, game details, weather
  lists, and per-game weather. The contracts include bounded filters,
  cursor pagination, safe 404/422 responses, ETags, and conditional 304s.
- Generated the new OpenAPI contracts into `packages/shared-types` and used
  those types in the web API client.
- Migrated `/games`, `/games/[gameId]`, and `/weather` with canonical date and
  filter URLs, explicit loading/error/empty/stale states, responsive cards,
  and permanent context-preserving links to the legacy views.
- Registered active-capable MLB schedule and Open-Meteo worker adapters behind
  the existing per-task allowlist. Schedule publication upserts provider-linked
  teams, venues, probable pitchers, and games; weather publication calculates
  field-relative wind and bounded run-environment adjustments.
- Made dataset rows, checkpoints, data-source status, and serving watermarks a
  single PostgreSQL transaction. Invalid identities, duplicate records, missing
  coordinates, and out-of-range values fail closed before publication.
- Added an eight-day weather window bound, immutable normalized artifacts, and
  separate Cloud Run Job templates/allowlists for schedule and weather.
- Added cached, bounded player-directory, player-profile, season-summary,
  recent-game-log, and direct batter-versus-pitcher APIs over persisted facts.
- Migrated `/players`, `/players/[playerId]`, and the direct-history portion of
  `/matchups`, including canonical player/season/group filters, responsive
  tables, and permanent context-preserving legacy links.
- Corrected the web container workspace copy so source refreshes do not replace
  the lockfile-created dependency links in shared packages.
- Added migration `0005_phase7_analytics` with normalized pitch events,
  plate-appearance sequences, direct pitch-type summaries, batter/team season
  summaries, and precomputed streak summaries. The pinned SQLite importer now
  copies available pitch facts and rebuilds every derived Phase 7 read model.
- Added bounded, cached APIs for Advanced HVP, pitcher-versus-opponent,
  projected bullpen, streaks, player leaderboards, and team comparisons.
- Migrated `/research/batter-vs-pitcher`,
  `/matchups/pitcher-vs-opponent`, `/matchups/bullpen`, `/streaks`,
  `/stats/players`, and `/stats/teams`, including canonical URL filters,
  responsive tables, explicit coverage/empty states, and accessible landmarks.

## Verification completed

- API validation image: 19 Pytest tests passed.
- Web validation image: TypeScript, ESLint, and 7 Vitest tests passed.
- Production Next.js image: built successfully with dynamic Games, game
  detail, and Weather routes.
- Docker Compose integration applied migration `0004_slate_weather_read_models`;
  schema readiness, API Games/Weather, and all three web routes returned HTTP
  200. The persisted sample date returned 12 games, a repeated collection
  request returned 304, and an encoded `mlb:*` game ID rendered its scoreboard.
- Worker validation: Ruff, strict mypy, and 15 worker/publisher tests passed.
- Controlled active rehearsal: July 13 correctly published an empty All-Star
  break slate; July 17 published 15 games, 15 linked venues with coordinates,
  and 15 weather snapshots. Identical weather redelivery returned `duplicate`.
- End-to-end publisher verification: the API returned 15 games and 15 available
  weather records, while Games, Weather, and game detail pages returned HTTP
  200 and the detail page rendered its persisted scoreboard.
- Browser review: home and Methodology checked at 1440 px and 390 px; no
  horizontal overflow, orange accents, or console warnings/errors were found.
- Mobile navigation opened successfully and exposed all current routes.
- Research validation: strict mypy and Ruff passed; the full Python suite passed
  142 tests; TypeScript, ESLint, and 9 Vitest tests passed; the local and
  container production Next.js builds passed.
- PostgreSQL integration returned Miguel Cabrera's 98-game 2023 batting
  profile and a persisted Miguel Cabrera versus Eli Morgan matchup; `/players`,
  player detail, and `/matchups` all returned HTTP 200 through Next.js.
- Migration `0005_phase7_analytics` applied to the retained PostgreSQL volume
  and produced 19,249 batter-season summaries, 660 team-season summaries, and
  3,898 active streak summaries. The legacy snapshot contains zero pitch-level
  rows, so Advanced HVP correctly reports explicit zero pitch coverage while
  still serving direct BvP history; it never fabricates pitch results.
- All six new APIs returned typed responses from PostgreSQL. All six native web
  routes returned HTTP 200, and the container production build listed each as
  a dynamic Next.js route. Runtime logs were free of 500s after nullable query
  parameters were explicitly typed for PostgreSQL.
- Repeated ownership rehearsal published 15 July 17 games and a second complete
  15-game weather observation (30 retained weather snapshots total). Identical
  schedule and weather redelivery returned `duplicate`; only those two tasks
  were allowlisted and all other jobs remained shadow-owned.

## Preservation boundary

All non-live pages read only persisted PostgreSQL snapshots; they do not call
MLB, Statcast, or weather providers during a request. Provider adapters are
available only through explicit task allowlists and repository ownership
defaults to shadow, preventing an accidental dual writer. The zero-row
pitch-event source is exposed as a coverage state rather than silently falling
back or inventing analytics. Streamlit remains isolated for the live-game work
scheduled in Phase 8.

## Fixed remaining slice ledger

This ledger fixes the unit of work used for progress counts. A slice is complete
only when its persisted contract, page or runtime behavior, regression tests,
production build, fallback, and applicable integration gate pass. Splitting a
slice during implementation does not increase the roadmap count; it remains one
slice until its listed exit gate passes.

### Phase 7 - complete (0 slices remaining)

All seven fixed slices passed their persistence, API, native-page, regression,
production-build, PostgreSQL integration, repeated-observation, accessibility,
and ownership gates in this checkpoint.

### Phase 8 - 3 slices remaining

1. Add worker-owned live snapshots with one upstream poll per game and final
   game shutdown.
2. Add the compact conditional live API/cache path and provider/Redis failure
   behavior.
3. Migrate React Game Center, recorded replays, animation/mobile visual parity,
   and the live fallback flag.

### Phase 9 - 4 slices remaining

1. Provision parameterized GCP foundations: Cloud SQL, Memorystore, GCS, VPC,
   secrets, IAM, probes, logs, and alert policies.
2. Deploy staging images, migrations, worker pool, jobs, and Scheduler; migrate
   and reconcile staging data.
3. Pass the staging acceptance matrix, load/resilience/security checks,
   backup/PITR restore, and operational runbooks.
4. Run the canary, observe SLOs, rehearse rollback, and approve traffic/source
   ownership cutover.

### Phase 10 - 2 slices remaining

1. Complete the defined observation period, usage/log review, final legacy
   image/snapshot, and retirement approval.
2. Remove production Streamlit, SQLite bootstrap, local caches, old workflows,
   and duplicate code; then pass the final no-legacy-dependency gate.

**Exact count after this checkpoint: 9 slices remain**: 3 in Phase 8, 4 in
Phase 9, and 2 in Phase 10.

The next slice is Phase 8.1: worker-owned live snapshots with one upstream poll
per game and final-game shutdown.

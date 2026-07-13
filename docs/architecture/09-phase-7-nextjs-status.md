# Phase 7 Next.js migration status

Status: in progress. The shared shell, Methodology page, and persisted Games
and Weather preview have passed their Phase 7 gates. The legacy application
remains available for full live/current coverage while source publishing is
activated route by route.

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

## Preservation boundary

The Games and Weather pages read only persisted PostgreSQL snapshots; they do
not call MLB or weather providers during a request. The provider adapters are
available only through explicit task allowlists and the repository default
remains shadow, preventing an accidental dual writer. Streamlit remains the
authoritative production fallback until repeated parity and ownership approval,
and for player profiles, matchup research, bullpen, streak, and player/team
stat views. Each Next.js route preserves supported context when it hands off.

## Next Phase 7 slice

Collect repeated schedule/weather parity observations before any production
ownership flip. In parallel, migrate the next analytical inventory (player
directory/profile and matchup research) only after its persisted API contracts
exist. Phase 8 must not start until the non-live Phase 7 route inventory is
complete.

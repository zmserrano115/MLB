# Phase 7 Next.js migration status

Status: in progress. The shared shell and Methodology page have passed their
Phase 7 gates; analytical routes still hand off to the legacy application.

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

## Verification completed

- Docker validation target: TypeScript, ESLint, and 5 Vitest tests passed.
- Production Next.js image: built successfully.
- Docker Compose integration: web health, home, Methodology, and API readiness
  all returned HTTP 200.
- Browser review: home and Methodology checked at 1440 px and 390 px; no
  horizontal overflow, orange accents, or console warnings/errors were found.
- Mobile navigation opened successfully and exposed all current routes.

## Preservation boundary

The current Streamlit application remains authoritative for games, game
details, player profiles, matchup research, bullpen, streak, player/team stat,
and weather views. Each Next.js route preserves supported date, team, game, and
player context when it hands off. Those pages should migrate only after their
FastAPI contracts exist and their data, failure-state, accessibility, URL, and
responsive parity gates pass.

## Next Phase 7 slice

Implement the read-only games and weather API contracts, then migrate `/games`,
`/games/[gameId]`, and `/weather` behind route-level parity tests. Phase 8 must
not start until the non-live Phase 7 route inventory is complete.

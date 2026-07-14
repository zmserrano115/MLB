# Phase 8 live migration status

Completed: 2026-07-13

## Slice 8.1 — worker-owned live snapshots

- Added migration `0006_phase8_live_game` with bounded, replay-safe live snapshot and
  event tables.
- Added a pure MLB feed reducer shared by recorded replays and active worker polling.
- The worker performs one upstream request per game poll, parses once, publishes SQL
  facts atomically, and schedules the next five-second poll only while the game is not
  final.
- Compact payloads are rejected above 128 KiB. Stable game/version and event keys make
  retries idempotent.

## Slice 8.2 — conditional API and cache fallback

- Added `GET /api/v1/games/{game_id}/live?since=` with a compact typed envelope,
  `ETag`, `304`, cache status, snapshot age, and stale metadata.
- API requests read Redis/SQL only; they never call MLB. Redis failure falls back to the
  latest PostgreSQL snapshot and marks the response stale. Provider failure leaves the
  last persisted generation available.
- Final snapshots remain non-expiring source truth and stop the worker polling loop.

## Slice 8.3 — React Game Center

- Added a native responsive Game Center with scoreboard, inning/count/base state,
  current matchup, recent-play animation, contact metrics, and compact box scores.
- The client conditionally polls one API endpoint every five seconds, retains the last
  good snapshot during reconnects, and stops when `is_final` is true.
- Live, Contact, and Box Score tabs are URL-backed. Reduced-motion, screen-reader base
  state, mobile layouts, and explicit legacy fallback flags are covered by gates.

## Verification

- Python: 150 tests passed; Ruff and strict mypy passed.
- Web: 14 Vitest tests, TypeScript, ESLint, and the production Next.js build passed.
- Recorded live-to-final replay proves version progression, the 128 KiB bound, one
  provider request per worker execution, conditional `304`, Redis degradation fallback,
  and final-game shutdown.

## Remaining roadmap

Exactly **6 slices remain**:

- Phase 9: 4 slices.
- Phase 10: 2 slices.

Phase 8 has no remaining slices. The next slice is Phase 9.1.

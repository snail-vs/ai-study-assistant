# Durable course-generation lease

## Objective

Make course-generation scheduling safe across process restarts and multiple
application workers by adding a database-backed lease around the existing
persisted generation state.

## Design

- Add lease owner/token and expiry fields to `LearningSpace` via an Alembic
  migration.
- Atomically claim queued/running work before scheduling a local task.
- Refresh/release the lease on lifecycle transitions; expired leases can be
  reclaimed during startup recovery.
- Keep the local task dictionary only as an in-process optimization.

## Constraints and verification

- Preserve HTTP contracts and generation status/phase semantics.
- Avoid duplicate card creation when workers race.
- Cover atomic claim, live-lease deduplication, expired-lease recovery,
  failure/cancellation release, and startup recovery with SQLite tests.
- Run migration upgrade, full tests, compile, OpenAPI/AST checks, then commit.

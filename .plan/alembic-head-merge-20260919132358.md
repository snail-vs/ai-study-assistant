# Alembic head merge

## Objective

Merge the two current Alembic heads (`0a12bc34de56` and `b5c6d7e8f9a0`) into a
single schema head without changing database objects.

## Implementation

- Add one no-op merge revision whose `down_revision` names both heads.
- Do not alter existing revision files or models.

## Verification

- `alembic heads` reports exactly one head.
- Upgrade an empty SQLite database with `alembic upgrade head`.
- Downgrade/upgrade traversal remains valid and backend tests pass.

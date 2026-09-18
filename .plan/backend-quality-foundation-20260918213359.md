# Backend quality foundation

## Goal

Build a regression-test safety net around the highest-risk seams in `backend/api.py`, then use the evidence from those tests to define a staged extraction plan. Preserve the existing HTTP contract and database schema in this phase.

## Current baseline

- `backend/api.py`: 1,875 lines and 44 route handlers across provider settings/OAuth, course generation, learning runtime/cards, activities/assessment, conversations/streaming, proposals, and notes.
- Existing tests: 20 passing tests, concentrated in assessment and activity follow-up behavior.
- Baseline command: `UV_CACHE_DIR=/tmp/studycenter-uv-cache uv run --project backend python -m unittest discover -s backend/tests -v` from the repository root.
- The test command depends on running from the repository root; running discovery from `backend/` cannot import the `backend` package.

## Phase 1: characterization tests (this change)

1. Add focused unit tests for authorization/resource ownership helpers and API response projections.
2. Add focused tests for provider/model-route validation and persistence, especially invalid-provider/model behavior and deletion semantics.
3. Add tests for application error mapping and request-id propagation where they can stay isolated from external services.
4. Keep tests deterministic: no network, no real provider credentials, and no persistent database.
5. Run the complete backend suite and report any uncovered constraints discovered while testing.

## Phase 2: extraction sequence (follow-up change)

Extract one domain at a time only after its characterization tests pass:

1. Provider settings and ChatGPT OAuth into a dedicated router plus provider-settings service.
2. Learning-space generation/runtime into a router and generation coordinator; replace module-global task bookkeeping behind one abstraction.
3. Activities/assessment into a router that delegates orchestration to the existing assessment service.
4. Conversations/streaming into a router and conversation service, isolating SSE serialization from persistence and agent orchestration.
5. Cards/guidance/proposals/notes into smaller domain routers with shared ownership-query helpers.

`backend/api.py` should temporarily remain a composition/compatibility module so imports and route registration do not move all at once.

## Architectural rules for extraction

- Routers own HTTP parsing/status codes and dependency injection only.
- Services own orchestration and transaction intent; repository/query helpers own SQLAlchemy selection.
- Provider and agent instances must not be mutable process-global request state.
- Response projection from JSON blobs must use explicit allowlists and have security regression tests.
- Ownership checks must be centralized and tested for cross-user access, missing parent resources, and soft-deleted resources.
- Transaction boundaries must be explicit; failure-path tests must assert no commit or partial persisted state.

## Verification gates

- All existing and new backend tests pass from the repository root.
- Tests do not make network calls or depend on developer-local state.
- No API schema, migration, or frontend client changes in Phase 1.
- Before each Phase 2 extraction, compare generated OpenAPI behavior and run the entire backend suite.

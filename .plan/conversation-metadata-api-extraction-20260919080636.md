# Conversation metadata API extraction

## Objective

Complete the conversation router by moving conversation creation and listing
from the legacy API module into `backend/conversation_api.py`.

## Scope

- Move `POST /cards/{card_id}/conversations`.
- Move `GET /cards/{card_id}/conversations`.
- Keep message listing, active-run lookup and stream operations in their
  current router positions.
- Reduce `backend/api.py` to the public health route and authenticated agent
  directory route only.

## Compatibility constraints

- Preserve paths, verbs, schema/status contracts, query alias `sectionId`,
  auth, operation IDs, ordering, default participants, and exact errors.
- Preserve user ownership, soft-deleted-card behavior, section checks, and
  transaction timing.
- Use `services.ownership`; new router/service code must not depend on
  `backend.api`.
- Do not change models, migrations, provider configuration, or `.gitignore`.

## Verification

- Extend the conversation contract tests for all five router operations,
  auth, app registration uniqueness and legacy route removal.
- Characterize default/invalid participants, card/section validation and list
  ordering.
- Run full tests, compileall, diff/line checks, dependency check, isolated
  OpenAPI comparison, AST equality for retained legacy handlers, then commit.

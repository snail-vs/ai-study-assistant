# Ownership query extraction

## Objective

Remove the remaining cross-router dependency on `backend.api` by moving
user-scoped space, card, and conversation lookups into a dedicated service.

## Target structure

- `backend/services/ownership.py`: `owned_space`, `owned_card`, and
  `owned_conversation` queries, including their current-user lookup and exact
  404 contracts.
- `backend/api.py`: consume the service during the transition; retain no local
  ownership-query implementation.
- `backend/activity_api.py`, `backend/learning_space_api.py`, and
  `backend/conversation_api.py`: import their respective query directly from
  the ownership service.

## Compatibility constraints

- Preserve joins, current-user scope, return types, and existing 404 messages.
- Preserve every route, response model, operation ID, and authentication
  dependency; this change introduces no new HTTP endpoint.
- Do not change models, migrations, provider configuration, or user-owned
  `.gitignore` edits.

## Tests and verification

- Move ownership-helper unit tests to the service import path.
- Retain SQLite checks that prove cross-user resources are uniformly invisible.
- Add a dependency-boundary test: extracted routers must not import
  `backend.api`, while the ownership service must not depend on API/router code.
- Run the full backend suite, `compileall`, `git diff --check`, the full
  pre-change/current OpenAPI comparison, and an AST check of unrelated legacy
  API functions.

## Non-goals

- Do not extract the remaining knowledge-card routes in this change. That is
  the next refactor once ownership queries are independent.

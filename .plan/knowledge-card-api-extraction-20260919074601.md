# Knowledge-card API extraction

## Objective

Extract the remaining knowledge-card resource endpoints from `backend/api.py`
into a focused authenticated router now that ownership queries are independent.

## Target structure

- `backend/knowledge_card_api.py`: card CRUD, section guidance, related-card
  proposals, and notes routes.
- `backend/main.py`: register the new router before the legacy router.
- `backend/api.py`: retain health, agents, learning runtime, and conversation
  metadata routes for later domain-specific extraction.

## Route scope

- Cards: list/create by space; get/delete by card.
- Guidance: list/create for a card section.
- Proposals: list, accept, start discussion, reject.
- Notes: create/list by card, list all, update, delete.

Conversation create/list routes deliberately remain in the conversation refactor
that follows, even though they are nested under cards.

## Compatibility constraints

- Preserve all 15 operations: paths, verbs, schemas, status codes, operation
  IDs, auth dependencies, query aliases, and exact exceptions.
- Preserve soft-delete behavior, idempotent section-enter guidance, proposal
  lifecycle, card/section validation, ordering, transaction timing, and note
  normalization.
- Use `services.ownership`; do not import API/router modules from the new
  router.
- No changes to models, migrations, AI prompts, provider config, or user-owned
  `.gitignore`.

## Tests and verification

- Add router contract tests for exact routes/models/status/auth/app registration
  and absence from the legacy router.
- Add characterization tests for card soft-delete, guidance idempotency,
  proposal invalid/accepted paths, and note validation/ownership.
- Full tests, compileall, diff checks, line checks, service/router dependency
  check, OpenAPI comparison, and AST equality of every retained legacy API
  function.

## Non-goals

- Do not move conversation create/list or learning runtime endpoints in this
  change.

# Related-card workflow extraction

## Objective

Move proposal acceptance, discussion startup and rejection orchestration out of
the knowledge-card HTTP router into a transactional application service.

## Target structure

- `backend/services/related_card_workflow.py`: proposal lookup/ownership,
  acceptance (AI draft, card/section/bridge creation), discussion startup,
  rejection, and relation-label helper.
- `backend/knowledge_card_api.py`: retain list endpoint and HTTP handlers that
  delegate to the service.

## Compatibility constraints

- Preserve proposal/card ownership, exact 404/400/409 contracts, idempotent
  accepted-card return, relation wording, ordering, and status transitions.
- Preserve generated card/section/bridge fields, flush then commit ordering,
  provider selection, and response models/statuses/operation IDs.
- Keep list proposals, card/guidance/note routes in their existing router.
- Service may use ownership service but must not import API/router code.
- No models/migrations/prompts/provider behavior/.gitignore changes.

## Tests and verification

- Migrate proposal behavior tests to service seams without weakening.
- Add successful acceptance characterization: persisted branch card, ordered
  sections, bridge note and accepted linkage.
- Add discussion invalid-section and reject ownership/state tests.
- Full tests, compileall, diff/line/dependency checks, isolated OpenAPI and
  legacy-router AST checks; commit independently once verified.

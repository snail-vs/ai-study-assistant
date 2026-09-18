# Activity workflow extraction

## Objective

Extract learning-activity routes and orchestration from `backend/api.py` while preserving every API contract, scoring path, transaction boundary, and privacy projection.

## Target structure

- `backend/activity_api.py`: authenticated activity routes only.
- `backend/services/activity_workflow.py`:
  - owned activity lookup and public response projection;
  - quiz generation lifecycle;
  - attempt and follow-up submission orchestration;
  - post-assessment mentor/gap hooks;
  - mastery and gap-diagnosis decision helpers.
- `backend/main.py`: register the extracted router.
- `backend/api.py`: remove the extracted activity routes/helpers and retain all other legacy domains.

## Compatibility constraints

- Keep all six existing activity operations, methods, paths, response models, status codes, exception messages, and OpenAPI schema unchanged.
- Preserve explicit allowlists that prevent answer keys, rubric data, and provider payloads from leaking into public attempt responses.
- Preserve scoring order: evaluate before mutating attempts; retain retryable pending follow-ups on evaluation failure.
- Preserve quiz generation `generating` / `ready` / `failed` state transitions and database commit timing.
- Keep the existing assessment domain package as the scoring engine; do not change models, migrations, frontend contracts, or AI prompts.
- Preserve the user's `.gitignore` modification without staging it.

## Tests and verification

- Migrate activity-helper and activity-follow-up tests to the workflow service seam without weakening assertions.
- Add router registration/authentication/OpenAPI contract coverage.
- Add characterization tests for quiz-generation failure state persistence and owned-activity lookup across users.
- Run complete backend tests, compileall, line-length checks for new files, diff checks, full OpenAPI comparison, and AST comparison proving unrelated legacy API functions remain unchanged.

## Non-goals

- Do not change the current external semantics of post-assessment hooks or follow-up retries.
- Do not extract card ownership helpers in this change; the new router may use the existing helper temporarily.

# Provider settings and OAuth extraction

## Objective

Reduce `backend/api.py` by moving the provider-settings domain behind explicit router and service modules without changing HTTP paths, response schemas, authentication, database schema, or provider behavior.

## Target structure

- `backend/services/provider_settings.py`: provider construction, credential projection, active-provider restoration, settings projection, task-route validation/persistence, and ChatGPT credential persistence helpers.
- `backend/provider_api.py`: the authenticated `/settings/*` routes and ChatGPT OAuth session orchestration.
- `backend/api.py`: learning-domain routes only; import `restore_active_provider` from the service as a temporary compatibility seam for existing call sites and tests.
- `backend/main.py`: register the extracted provider router under `/api/v1`.

## Compatibility constraints

- Preserve every existing method/path/status code/response model in the provider settings and ChatGPT OAuth block.
- Keep `backend.api.restore_active_provider` patchable for learning, assessment, and streaming tests.
- Do not change encryption formats, database models, OAuth protocol calls, or OpenAPI schema.
- Keep authentication dependency on the extracted router.
- No network calls in tests.

## State cleanup

- Replace mutable `provider_state` with an immutable supported-provider definition; active provider/model must come from persisted user-scoped state.
- Remove unused module-level gateway/agent instances from `backend/api.py`.
- Keep the existing in-memory ChatGPT login-session behavior in this extraction; its replacement requires a separate lifecycle design.

## Verification

- Existing provider-settings service tests move to/import the new service seam and continue to cover user isolation, credential redaction, validation, upsert, and deletion.
- Add router-registration/contract tests covering the extracted route set and authentication dependency.
- Full backend suite passes.
- Generated OpenAPI contains the same provider settings/OAuth operations and no duplicate operations.
- `compileall` and `git diff --check` pass.

## Non-goals

- Do not fix streaming cancellation, course-generation cancellation, soft-delete semantics, or contradictory SSE terminal events in this change.
- Do not introduce a generic repository framework or class hierarchy.

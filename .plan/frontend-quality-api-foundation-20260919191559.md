# Frontend quality and API foundation

## Objective

Establish automated frontend checks and a single typed API boundary before
moving UI state out of the monolithic `App.vue`.

## Scope

- Add TypeScript checking, ESLint, Vitest, and scripts for test/typecheck/lint.
- Make API schema freshness check part of the verification workflow.
- Add `src/api/client.ts`: JSON request/error handling based on the generated
  OpenAPI client types; preserve same-origin credentials.
- Move only the generic `App.vue` request helper to this client; retain all
  endpoint paths and UI behavior.
- Add unit tests for success, JSON/non-JSON failures and API error envelopes.

## Constraints

- No visual/UI behavior changes and no backend changes.
- No routing/store/component extraction in this phase.
- Do not regenerate or hand-edit generated OpenAPI schema.
- Preserve `.gitignore` user change.

## Verification

- package scripts: build, api check, typecheck, lint, test.
- Full frontend checks and focused API client tests.
- Existing backend tests remain unaffected.

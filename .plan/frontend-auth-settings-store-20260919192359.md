# Frontend auth and settings stores

## Objective

Extract authentication and provider/settings state from `App.vue` into focused
Pinia stores, using the new typed API client as the only JSON request boundary.

## Scope

- `stores/auth.ts`: auth check, login/register, logout and auth UI state.
- `stores/settings.ts`: provider settings, model discovery/configuration, task
  routes and ChatGPT OAuth UI state.
- Update `App.vue` to consume stores without visual or endpoint changes.
- Add store tests for success/failure/loading/reset paths.

## Constraints

- Preserve current field names, loading/error UX, same-origin credentials and
  all API paths.
- Leave learning, conversations, activities, notes and manual URL navigation
  in `App.vue` for later phases.
- No backend/generated-schema/.gitignore change.

## Verification

- typecheck, unit tests, schema check, build and lint with no new errors.
- Confirm App no longer owns auth/provider/OAuth mutable refs or direct request
  calls for these domains.

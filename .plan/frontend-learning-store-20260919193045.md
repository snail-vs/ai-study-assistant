# Frontend learning workspace store

## Objective

Extract learning-space, card, section navigation and generation/runtime state
from `App.vue` into a focused Pinia store.

## Scope

- `stores/learning.ts`: history, active space/card/root card, related cards,
  navigation stack, active section, generation polling, runtime persistence.
- Update `App.vue` to consume the store with no visual or route behavior change.
- Tests for navigation stack, generation lifecycle, runtime payload and errors.

## Constraints

- Preserve manual URL behavior, current API paths, loading/error UX and local
  history semantics.
- Leave conversation messages, activities, notes and UI component extraction
  for later phases.
- No backend/generated schema/.gitignore changes.

## Verification

- typecheck, Vitest, schema check, build, lint and diff checks.

# Frontend activity store

## Objective

Move activity list, quiz generation, answers, submissions, follow-up and result
state from `App.vue` into a focused Pinia store.

## Implementation

- Add `stores/activity.ts` with section-aware load/reset, quiz generation,
  answer updates, attempt submission and follow-up actions.
- Update `App.vue` to consume store state/actions without template, URL or API
  contract changes.
- Preserve loading flags, errors and safe reset behavior during section/card
  navigation.

## Tests

- Cover generation success/failure, submission, follow-up failure without local
  result corruption, and section switch reset.
- Run typecheck, Vitest, schema check, build, lint and diff check.

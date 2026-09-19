# Frontend conversation store

## Objective

Move conversation state, SSE streaming side effects, message highlighting and
discussion-panel state from `App.vue` into a Pinia store without changing UI,
URLs or backend contracts.

## Implementation

- Add `stores/conversation.ts` for list/select/load/send streaming actions,
  run state, highlighted IDs and mobile/list visibility.
- Update `App.vue` to use this store while retaining the existing template,
  manual URL synchronization and composer DOM behavior.
- Preserve same-origin streaming request behavior, event ordering and current
  error/cancellation semantics.

## Tests

- Cover section validation, selection reset, SSE deltas/terminal states,
  errors, highlighter cleanup and panel flags with Vitest.
- Run typecheck, tests, schema check, build, lint and diff check.

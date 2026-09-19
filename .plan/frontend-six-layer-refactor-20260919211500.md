# Frontend six-layer refactor

## Delivery rule

Deliver every layer as an independently verified Git commit. Preserve UI
behavior, URLs, and API contracts unless a later layer explicitly changes them.

## Layers

1. Extract notes state and CRUD actions into a `notes` Pinia store, with tests
   for loading, editing, saving, deleting, and context reset.
2. Extract per-section teacher guidance and related-card recommendation loading
   into a focused study-assist store, keeping SSE-driven updates coherent.
3. Introduce a thin workspace orchestration layer for card opening, section
   switching, route restoration, and runtime persistence across stores.
4. Split the remaining App view into focused presentation components without
   shifting business rules back into components.
5. Replace hand-managed study URLs with Vue Router routes and query handling.
6. Add component-level workflow regression tests for route restoration,
   navigation, activity submission, and conversation-stream failure recovery.

## Validation for each layer

Run TypeScript checks, the relevant unit/component tests, generated API schema
check, production build, ESLint, whitespace diff check, and review the staged
diff before committing.

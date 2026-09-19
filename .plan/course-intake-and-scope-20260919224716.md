# Course intake and scope implementation plan

## Goal

Add a pre-generation course-design conversation that turns a vague topic into a structured course brief, lets the learner choose/confirm a quick, standard, or series scale, previews the proposed outline, and passes the confirmed brief into course generation.

## Product boundaries

- Keep intake transient in the browser for this first version; persist the confirmed brief and scale on the learning space so retries and resumed jobs are deterministic.
- Limit intake to at most three AI turns, one high-value question per turn, with a "generate directly" escape hatch.
- A series course generates a series-oriented first knowledge card/overview in this iteration. Multi-card progressive module generation is intentionally deferred.
- Existing direct course creation requests remain compatible by defaulting to a standard brief.

## Backend

1. Add structured intake schemas for messages, `CourseBrief`, outline items, turn request/response, and course scale constraints.
2. Add a course-intake agent/prompt that updates the brief, asks the next missing high-value question, recommends scale, and returns a preview outline. Validate its structured output and add deterministic normalization/defaults.
3. Expose an authenticated `POST /course-design/turn` endpoint using the active provider.
4. Extend learning-space persistence with `course_brief_json` and `course_scale`, including an Alembic migration, response fields, create/retry behavior, and safe JSON accessors.
5. Feed the confirmed brief and scale into `MainAgent.create_card`; parameterize planner and author constraints for quick/standard/series and enforce section-count bounds in application code.
6. Add the intake task to model routing/registry if required by the gateway.
7. Update the OpenAPI contract/generated frontend types.

## Frontend

1. Add a focused course-design store that owns intake messages, draft brief, quick options, scale selection, readiness, outline preview, loading/error state, skip, edit/reset, and final payload construction.
2. Replace the one-step home form with a compact staged UI: initial goal, conversational questions with option chips/free text, editable scale cards, brief/outline confirmation, and generation action.
3. Preserve failed-generation retry behavior and the existing background generation/history polling flow.
4. Add accessible loading/disabled states and responsive styles.

## Verification

- Backend tests: intake endpoint/agent contract, default/backward-compatible creation, brief persistence, scale-aware generation constraints, retry/resume behavior.
- Frontend tests: store state transitions and payload; update integration/component expectations where the creation flow changed.
- Regenerate/check OpenAPI types, run targeted backend and frontend tests, then full available suites and type/build checks.

## Deferred

- Persisting unfinished intake chats across devices.
- Generating every series module as ordered knowledge cards.
- Adapting later module plans from learning-assessment results.

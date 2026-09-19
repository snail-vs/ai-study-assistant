# Course outline confirmation flow

## Goal

Make course scale selection explicit and add a conversational outline-review loop before course generation.

## User flow

1. Keep the current learning-requirements confirmation UI.
2. Show quick/standard/series as unselected choices; mark the AI recommendation without selecting it. Do not generate an outline until the learner clicks a scale.
3. Generate and show the scale-specific outline with a loading state.
4. Let the learner send natural-language outline change requests repeatedly. Each response returns an updated outline and a short assistant acknowledgement.
5. Only an explicit “confirm outline and generate course” action starts course generation.

## Backend

- Extend outline request/response schemas and OpenAPI for scale generation and outline revision conversations.
- Add a revision endpoint/agent that receives the brief, scale, current outline, learner feedback, and prior revision messages; validate unique, non-empty, scale-bounded outline items.
- Persist the confirmed outline on LearningSpace, including migration and create/retry response fields.
- Pass the confirmed outline into MainAgent so generated sections follow the user-approved titles/objectives instead of replanning them away.
- Keep invalid model output as an actionable error; never fabricate placeholder outlines.

## Frontend

- Make selected scale nullable until an explicit click; preserve recommended scale separately.
- Gate outline generation on explicit scale selection.
- Add outline revision conversation state, loading/error/retry, and a composer; allow repeated revisions.
- Gate course submission on a non-empty confirmed outline and include it in the final creation payload.

## Verification

- Backend tests for unselected scale, outline generation/revision validation, persistence, and approved-outline propagation into MainAgent.
- Frontend tests for recommendation not being selected, click-to-generate, revision loop, and confirmation gating.
- Run full backend unittest, frontend tests/typecheck/build, OpenAPI generation consistency, and migration validation.

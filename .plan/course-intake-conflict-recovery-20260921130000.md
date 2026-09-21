# Course intake conflict recovery plan

## Objective

Prevent contradictory intake choices from trapping learners in repeated goal/background questions, and prevent semantically invalid background questions from leaving the UI with no matching selected options.

## Changes

1. Add deterministic, stage-specific fallback questions and semantic guards for intake questions. A question about course duration/scale must never be accepted as a background question.
2. Mark and handle a conflict-resolution follow-up as a replacement answer for its target field instead of merging it with the previously contradictory selections.
3. Keep the existing client-side preselection rule, which already only selects labels present in the current question; the backend fallback restores the required label/category alignment.
4. Add backend state-machine coverage for the invalid question and conflict-replacement paths.

## Verification

Run the targeted backend unittest modules and frontend store tests, then run the relevant typecheck/test command if available.

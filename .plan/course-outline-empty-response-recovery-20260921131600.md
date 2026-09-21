# Course outline empty-response recovery plan

## Objective

Recover automatically when the outline provider returns an empty or otherwise invalid outline, instead of immediately returning a 422 to the learner.

## Changes

1. Centralize outline validation (exact scale count, unique non-empty titles/objectives, and placeholder checks).
2. On the first invalid generated outline, issue one structured repair request containing the original response, brief, selected scale, validation failure, and exact required count.
3. Reuse the same recovery logic for outline revisions while preserving the revision-specific response contract.
4. Add tests for successful recovery from an empty outline and controlled failure when the repair remains invalid.

## Verification

Run the outline/intake and course-design state-machine tests, plus the existing frontend tests and typecheck.

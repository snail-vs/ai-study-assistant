# Activity workflow internal split

## Objective

Split activity projection/query, assessment submission, and post-assessment
hooks from `activity_workflow.py` into cohesive services without changing APIs.

## Structure

- `activity_query.py`: safe public projections and owned activity lookup.
- `activity_assessment.py`: quiz generation, attempt/follow-up submission.
- `activity_hooks.py`: mastery derivation, mentor guidance and gap diagnosis.
- `activity_workflow.py`: compatibility re-exports only during transition.

## Verification

- Preserve all activity API contracts and current error/transaction semantics.
- Keep privacy allowlists and retryable follow-up failures intact.
- Extend service-boundary tests; full test/OpenAPI/AST validation before commit.

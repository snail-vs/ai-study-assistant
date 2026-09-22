# Course generation quality implementation plan

## Goal

Upgrade course generation without introducing a general-purpose agent runtime. Preserve the confirmed teaching plan, carry learner and cross-section context through generation, persist recoverable section progress, and gate publication on a course-level quality review.

## Stage 1: richer planning and continuous section context

- Extend outline and agent schemas with teaching roles, prerequisites, concepts, strategy, mastery evidence, and section connections while accepting legacy title/objective outlines.
- Treat an approved outline as the authoritative plan and preserve its section role/type.
- Remove generic filler sections; repair invalid direct plans once and otherwise keep a valid smaller plan with warnings.
- Pass the complete learner brief and neighboring plan information to author/reviewer/repair prompts.
- Produce an `ActualSectionSummary` after each completed section and feed the actual result into the next section.
- Expand section review dimensions and tests.
- Commit after focused backend tests pass.

## Stage 2: incremental persistence and recovery

- Add durable course-plan/review metadata to cards and per-section plan, actual-summary, generation-state, attempts, error, and generation metadata fields.
- Create the draft card and pending section rows before content generation.
- Refactor the generation service to generate/review/persist one section at a time and resume from durable state.
- Refresh the generation lease around section work and expose section progress through generation status.
- Keep draft cards unpublished until all required generation work finishes.
- Add migration/backfill behavior and recovery/idempotency tests.
- Commit after backend and relevant frontend/type tests pass.

## Stage 3: course-level review and targeted repair

- Add course-review schemas and prompt using course brief, plan, actual summaries, and section quality reports.
- Persist the course review and execute bounded, section-targeted repairs.
- Re-review repaired sections and update actual summaries before the final course review.
- Publish only after the bounded review/repair workflow finishes; retain actionable quality state when issues remain.
- Add tests for summary-only review inputs, targeted repairs, bounds, and publication behavior.
- Commit after the complete relevant test suite passes.

## Compatibility and safety

- Existing outlines containing only `title` and `objective` remain valid.
- Existing Markdown rendering remains the primary content path; content blocks are deferred.
- Existing learning cards and sections receive safe defaults/backfills.
- Existing user changes outside this plan are not modified or committed.

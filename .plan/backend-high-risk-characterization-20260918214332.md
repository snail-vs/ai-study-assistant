# Backend high-risk characterization tests

## Objective

Create the final targeted safety net needed before splitting `backend/api.py`. This phase changes tests only and preserves the current API, persistence, and streaming behavior.

## Workstreams

### 1. Real SQLite integration boundary

- Use an isolated temporary SQLite database with foreign keys enabled.
- Exercise real SQLAlchemy statements for ownership helpers instead of reproducing query behavior in mocks.
- Prove current-user isolation, relationship joins, missing-resource behavior, and the current soft-delete semantics.
- Keep all engine/session state local to the test file; never touch `backend/studycenter.db`.

### 2. Course generation state machine

- Characterize `queued/running/generating/saving/completed/failed` transitions.
- Cover successful persistence, provider/agent failure, rollback/failure persistence, missing spaces, cancellation, task de-duplication, cleanup, and startup resumption.
- Assert session close behavior and `course_generation_tasks` cleanup.
- Use controlled doubles; no provider/network calls.

### 3. Conversation streaming lifecycle

- Characterize preflight conflicts before streaming begins.
- Consume the streaming iterator and assert key SSE ordering and terminal events.
- Cover successful answer completion, provider failure with and without partial text, and diagnosis/guidance failure isolation.
- Assert `AIRun` terminal status/error state and persistence of partial assistant output.
- Use controlled async iterators and session doubles; no provider/network calls.

## Acceptance criteria

- Each workstream owns a separate new test file to avoid overlapping edits.
- Tests assert externally meaningful state and failure cleanup, not implementation-only call counts unless the call represents a transaction/session invariant.
- The full backend suite passes from the repository root.
- `compileall` and `git diff --check` pass.
- Any behavior that cannot be tested without production changes is reported as a refactoring seam, not silently worked around.

## Refactoring gate after this phase

Begin extraction only after these tests pass. Use Provider Settings/OAuth as the first router/service split, then course generation, then conversation streaming. Preserve `backend.api` imports temporarily as a compatibility surface.

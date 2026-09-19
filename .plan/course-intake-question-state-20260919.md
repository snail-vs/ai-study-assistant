# Course intake question-state fix

## Problem

The interview UI exposes the learner answer controls before an AI question exists. A failed or incomplete first response therefore looks like the learner is expected to ask themselves a question. The response also carries `assistantMessage` and `question` separately, while the UI can render only the former.

## Changes

- Track whether the intake is waiting for the AI or waiting for the learner.
- Render a pending assistant bubble while the first/next question is loading.
- Combine the assistant lead-in and explicit question into one visible assistant turn.
- Show quick options and the answer composer only after a valid AI question exists.
- Show intake errors inline with a retry action; do not leave an answer composer active after failure.
- Add backend normalization so a non-ready response always has a visible question.
- Cover initial loading, explicit question rendering, failure/retry, and answer-control gating with tests.

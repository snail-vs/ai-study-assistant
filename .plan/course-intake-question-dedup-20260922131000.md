# Course intake question deduplication

1. Pass the question just answered to the intake agent, so it can distinguish a useful follow-up from a restatement.
2. Make generated fallback IDs unique per question content, avoiding stale UI state when a provider omits an ID.
3. Reject repeated same-stage follow-up questions at the service boundary and advance using the existing AI-completion path instead.
4. Add state-machine coverage for repeated questions and run the focused backend tests.

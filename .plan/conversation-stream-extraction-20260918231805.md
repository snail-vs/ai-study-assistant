# Conversation stream extraction

Pure structural change: preserve HTTP contracts, event payloads/order, commit timing,
partial-answer persistence, planning fallback, guidance failure isolation, diagnosis
failure terminal sequence, and current cancellation behavior.

- Add `backend/conversation_api.py` for three routes: message listing, active run,
  and message streaming. Keep authentication and preflight checks before response.
- Add `backend/services/conversation_stream.py` for stream preparation and lazy
  event iteration. Service must not import legacy API or router modules.
- Add lightweight `backend/sse.py` event encoder, preserving existing JSON options.
- Router may temporarily import `owned_conversation` from legacy API; service takes
  validated conversation/card data. Keep synchronous session lifetime unchanged.
- Move only these three routes; conversation creation/listing stays in legacy API.
- Migrate six streaming characterization tests without weakening assertions.
- Add meaningful success guidance/proposal persistence tests, preflight 404 checks,
  active-run expiry checks and router registration/authentication contract tests.
- Compare complete generated OpenAPI against the pre-change snapshot; inspect
  route lists before converting to sets so duplicate registration is detectable.
- Run full backend suite, compilation and diff checks. Preserve user `.gitignore`.
- Cancellation/terminal-event fixes are a separate subsequent change. No commit
  or push in this implementation turn.

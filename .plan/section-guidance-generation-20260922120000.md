# Section guidance generation gating and idempotency

## Problem

Partially generated courses are now browsable. Entering an unfinished section currently treats an empty guidance list as a generation request, so the mentor runs against placeholder content. Concurrent/repeated entry can also pass the read-before-write check and create duplicate `section_enter` guidance.

## Implementation

1. Expose each section's generation status in the card response and API contract.
2. Make the client load stored guidance for every section, but request new guidance only when section content is ready and non-empty.
3. Enforce the same readiness rule in the guidance creation endpoint.
4. Add a database partial unique index for one `section_enter` guidance per card/section. Insert an empty placeholder before calling AI so only the request that wins the insert performs generation; hide placeholders from list responses and remove them when generation fails.
5. Add backend and frontend regression tests for unfinished sections, existing/in-flight guidance, and the successful generation path.

## Verification

- Run focused backend behavior/contract tests and migration/model checks.
- Run focused frontend store tests plus TypeScript checks/build if available.

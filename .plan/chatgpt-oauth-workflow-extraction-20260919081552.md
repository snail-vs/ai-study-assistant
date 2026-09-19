# ChatGPT OAuth workflow extraction

## Objective

Extract the ChatGPT device/browser login state machine and credential persistence
from `provider_api.py` into a service while retaining its current in-process
session semantics.

## Target structure

- `backend/services/chatgpt_oauth.py`: login-session registry, device poll task,
  credential save/model refresh, browser completion, status and logout workflow.
- `backend/provider_api.py`: OAuth route handlers delegate to the service;
  provider/model configuration routes remain unchanged.

## Compatibility constraints

- Preserve all five OAuth operations, schemas, status codes, errors, response
  fields and operation IDs.
- Preserve session lifecycle, task scheduling, completion/failure cleanup,
  current-user scoping, credential encryption, active-provider refresh and model
  refresh behavior.
- Keep the intentionally in-memory session registry in this extraction. Moving
  it to Redis/database is a future deployment-design decision, not an implicit
  semantics change.
- Service must not import API/router modules; no model/migration/.gitignore
  changes.

## Tests and verification

- Add state-machine tests: device startup, polling success/failure, pending/
  done/failed/unknown status cleanup, browser completion, and logout cleanup.
- Extend provider API contract tests to lock all OAuth routes and router-service
  delegation seams.
- Full tests, compileall, diff/line/dependency checks, isolated OpenAPI and
  provider-router AST comparison; commit independently after verification.

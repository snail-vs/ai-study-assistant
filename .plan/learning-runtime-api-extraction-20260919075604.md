# Learning runtime API extraction

## Objective

Move the two learning-runtime endpoints from the legacy API router into the
existing learning-space router, completing that domain's HTTP boundary.

## Target structure

- `backend/learning_space_api.py`: add runtime read/write routes and required
  model/schema imports.
- `backend/api.py`: remove the two runtime handlers and now-unused imports.
- `backend/main.py`: no registration change; it already mounts the learning
  space router.

## Compatibility constraints

- Preserve GET/PUT paths, models, operation IDs, auth and 404/400 details.
- Preserve stack/card/section validation, record sequencing, JSON aliasing,
  flush/commit/refresh timing, and soft-delete handling.
- Keep conversation metadata routes out of scope.
- Do not change models, migrations, or user `.gitignore`.

## Tests and verification

- Extend learning-space router contract to include exactly the two runtime
  operations, legacy removal and one registration.
- Characterize runtime creation, record sequence, invalid current card/section,
  invalid stack entries, and user scope.
- Full tests, compileall, diff/line checks, router dependency checks, isolated
  OpenAPI comparison and legacy-API AST comparison.

# Course generation extraction

## Objective

Move course-generation orchestration and its learning-space HTTP endpoints out of `backend/api.py` without changing API behavior, generation state transitions, cancellation semantics, or persistence.

## Target structure

- `backend/services/course_generation.py`
  - `course_generation_tasks`
  - `generate_course`
  - `schedule_course_generation`
  - `resume_pending_course_generations`
- `backend/learning_space_api.py`
  - create/list/get learning spaces
  - get/retry generation status
- `backend/main.py`
  - register the extracted learning-space router
  - import startup resume behavior from the course-generation service
- `backend/api.py`
  - remove the extracted routes and orchestration
  - keep runtime/cards/activities/conversations/proposals/notes unchanged

## Compatibility constraints

- Preserve existing paths, methods, status codes, response models, authentication, error text, and scheduling timing.
- Preserve all current state-machine behavior, including the currently characterized cancellation behavior; fix it only in a separate follow-up.
- Do not change models, migrations, schemas, provider behavior, or task persistence strategy.
- The new learning-space router may temporarily import the legacy `owned_space` helper from `backend.api`; ownership extraction is a later cross-domain change.
- Do not include or modify the user's existing `.gitignore` change.

## Test migration and additions

- Migrate `test_course_generation.py` to patch the new service module directly.
- Add a learning-space router contract test covering the five extracted method/path pairs, authentication dependency, no duplicate registration, and absence from the legacy router.
- Keep the full existing backend suite green.

## Acceptance criteria

- The five HTTP operations remain present exactly once in OpenAPI.
- Startup still resumes queued/running generation through the extracted service.
- Course-generation state-machine tests continue to pass without weakening assertions.
- Full backend tests, `compileall`, line-width checks for new files, and `git diff --check` pass.

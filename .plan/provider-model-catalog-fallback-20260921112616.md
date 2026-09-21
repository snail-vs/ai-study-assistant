# Provider model catalog resolution

## Objective

Make provider configuration usable regardless of how a provider exposes (or
does not expose) its model list.  In particular, adding Zhipu GLM (China) and
Z.AI (overseas) must support a provider-specific catalog URL and user-entered
model IDs without assuming an OpenAI-compatible `GET /models` endpoint.

## Problem and decision

The settings UI currently has a single discovery path:

```text
API Key -> POST /settings/providers/{provider}/models -> GET {base_url}/models
        -> checkbox list -> save provider
```

`OpenAICompatibleProvider.list_models()` implements the middle step directly.
That endpoint is not universally available, and some providers publish a
separate model-catalog URL instead.  Treating `{base_url}/models` as mandatory
would make a valid key unconfigurable.

Use a **three-level model-resolution strategy**, shared by API-key providers.
Its ordered priority is fixed:

1. **User-specified model ID** — a model typed/selected by the user is the
   request model and always wins.  It is persisted in the existing `models`
   field and can be selected globally or assigned to a task immediately.
2. **Provider-specific catalog URL** — when no user model has been supplied,
   query a documented URL carried by that provider definition.  This URL may
   differ from the chat API base URL and has provider-specific response
   parsing.
3. **Conventional catalog URL** — only when level 2 is absent, call
   `{base_url}/models` through the existing OpenAI-compatible implementation.

If neither remote discovery path is available, show the manual model-ID input
and explain that the provider did not provide a model list.  Remote listing is
therefore helpful but never a prerequisite for saving a key or making a
request.  A 401/403 from an attempted catalog request remains an
authentication error; endpoint-not-supported and incompatible-list responses
fall through to manual entry with a visible warning.

This preserves the current settings persistence schema: a configured model is
already an arbitrary string in `ProviderCredential.models_json`; no database
migration is necessary.

## Request-model precedence

Model-list discovery does not select the request model.  At request time use:

```text
task-route model -> user selected global model -> provider definition default
```

The first two values are user-specified and therefore take precedence over all
catalog sources.  The final fallback is the `default_model` in the provider
definition.  The registry then joins the provider base URL and protocol path
(for GLM/Z.AI, `{base_url}/chat/completions`) as it does today.

## API contract

Extend `DiscoverModelsResponse` compatibly from `{ models }` to:

```json
{
  "models": ["..."],
  "source": "provider_catalog | conventional | manual",
  "warning": "optional human-readable explanation",
  "keyValidated": true
}
```

Existing clients can continue reading `models`.  `keyValidated` means the key
was authenticated by a remote catalog request; a manual-only result is false.
Model selection and saving remain available for manual IDs, while the UI makes
that uncertainty explicit.  Avoid a test inference request merely to validate
a key: it would consume quota and would make saving configuration depend on
model-specific availability.

## Target design

- Introduce a provider-definition/catalog module adjacent to the registry.
  Each definition owns its display-independent ID, chat base URL, default
  request model, and optional dedicated catalog specification (URL plus parser
  identifier).  Keep request routing/protocol behavior in `model_routing.py`.
- Add a catalog-resolution function in the provider service (or a focused
  provider-catalog service).  It returns the dedicated catalog result when a
  definition supplies one; otherwise calls the conventional `/models` method;
  and returns a manual-entry result on unsupported/malformed endpoints.  The
  API router should delegate rather than duplicate URL construction, parsing,
  or error classification.
- Retain `OpenAICompatibleProvider.list_models()` as the conventional
  level-3 request.  Add a separate low-level catalog request/parser seam for
  level 2.  Give errors sufficient status/category information to distinguish
  authentication from an unsupported endpoint; do not broadly catch
  `Exception`.
- Add `glm` (`https://open.bigmodel.cn/api/paas/v4`) and `zai`
  (`https://api.z.ai/api/paas/v4`) definitions.  Both use the existing
  OpenAI-compatible chat-completions adapter, but have separate credentials,
  catalogs, active selections, and task routes.
- Populate GLM/Z.AI catalog specifications only from their official documented
  APIs at implementation time; do not assume the two regions offer identical
  models.  If no stable dedicated endpoint is documented, leave level 2 absent
  and use level 3/manual entry rather than inventing a URL.
- In the settings store, retain existing selected/manual models when discovery
  returns a catalog or warning; never filter a manual model out just because a
  remote list omitted it.  The manual input is available even after a remote
  catalog succeeds.
- Add a compact "add model ID" input and button in `SettingsDialog`.  It trims,
  rejects duplicates/empty values, adds the value to the candidate list, and
  selects it.  Show remote/catalog status and the warning next to the fetch
  control.  The feature is generic, so it also repairs other providers with
  incomplete model-list endpoints.

## Files and changes

1. `backend/ai/registry.py` and a new focused provider-definition/catalog
   module: centralize provider defaults, seed catalogs, and register `glm` and
   `zai` without altering provider-specific protocol adapters.
2. `backend/ai/providers/openai_compatible.py` and error helpers: preserve
   HTTP status/category needed to recognize unsupported `/models` without
   masking 401/403 errors.
3. `backend/services/provider_settings.py`, `backend/provider_api.py`, and
   `backend/schemas.py`: expose catalog-resolution metadata compatibly; use
   the same supported-provider source for deletion/settings projection.
4. `frontend/src/stores/settings.ts`,
   `frontend/src/components/SettingsDialog.vue`, and `frontend/src/App.vue`:
   add provider choices, discovery metadata, merge semantics, warning display,
   and manual model addition.  Display that a manually selected model takes
  precedence over discovered candidates.
5. Regenerate `frontend/src/api/generated/schema.ts` from the backend OpenAPI
   generator rather than hand-editing it.
6. Update `docs/ai-provider-compatibility.md` with discovery semantics and the
   two GLM region endpoints.

## Verification

- Backend unit tests cover user-selected model precedence, dedicated-catalog
  URL/parsing, conventional `{base_url}/models` fallback when no dedicated URL
  exists, manual-only result on unsupported/malformed catalog responses,
  401/403 propagation, and GLM/Z.AI routes resolving to `/chat/completions`.
- Provider-settings tests assert both new IDs appear in the safe settings
  projection and can be used in task routes without leaking credentials.
- Provider restoration tests assert an explicit global model and a task-route
  model each take precedence over the provider definition default.
- Frontend store/component tests cover catalog response, retained manual
  selection, warning state, adding/duplicate manual IDs, and both new provider
  choices being restored on opening settings.
- Regenerate and type-check the OpenAPI client, then run the backend suite,
  frontend test suite, and `git diff --check`.

## Non-goals

- This does not add a user-customizable arbitrary chat base URL or a database
  field for API region; separate provider IDs deliberately avoid that
  migration.
- This does not promise a universal key-validation endpoint or perform a
  token-consuming completion request during configuration.

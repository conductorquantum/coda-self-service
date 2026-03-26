# Configuration

The runtime is configured through a layered system of environment
variables, persisted state, and defaults. The `Settings` class
(Pydantic Settings) manages resolution and validation.

## Topics

| Document | Summary |
|---|---|
| [SETTINGS_REFERENCE.md](SETTINGS_REFERENCE.md) | Complete field reference for the `Settings` class. |
| [ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md) | All `CODA_`-prefixed environment variables. |

## Key Files

| File | Role |
|---|---|
| `src/coda_node/server/config.py` | `Settings` class, `load_persisted_runtime_config()`, file paths. |

## Precedence Order

Settings are resolved with the following priority (highest first):

1. **Environment variables** — `CODA_`-prefixed (e.g. `CODA_REDIS_URL`).
2. **Persisted runtime config** — from `/tmp/coda.config` (written
   after successful node provisioning).
3. **Hardcoded defaults** — defined on the `Settings` class.

Persisted values only apply when no `node_token` is set and the
environment variable is empty, `None`, or `[]`.

## Validation

The `Settings` model uses `validate_assignment=True` so that
mutations made during bundle application (e.g. `settings.qpu_id = ...`)
are validated against field types.

Two model validators enforce constraints:

### `merge_persisted_runtime_config` (mode="before")

Merges persisted config into the settings dict before field validation.
Skipped when a node token is present (to avoid overriding a
fresh provisioning with stale state).

### `check_jwt_or_node_token` (mode="after")

Requires either:
- A `node_token` (for auto-provisioning), or
- Both `jwt_private_key` and `jwt_key_id` (for direct JWT startup).

Raises `ValueError` if neither is available.

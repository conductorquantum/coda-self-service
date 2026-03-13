# coda-self-service

Minimal server runtime for connecting a machine to Coda with:

- RS256 JWT auth
- single-token self-service provisioning
- VPN preflight and background monitoring
- Redis stream job consumption
- signed result webhooks
- a pluggable execution backend

## Quick start

```bash
uv sync --dev
uv run pre-commit install
uv run pytest
uv run coda start --token <your-token>
```

The server uses the `CODA_` environment variable contract so it can be
used as a drop-in extraction of the server-side runtime from
`feat/stanza/server-vpn-unified`.

## Runtime configuration

Important environment variables:

- `CODA_SELF_SERVICE_TOKEN`: fetch runtime configuration from Coda
- `CODA_JWT_PRIVATE_KEY`: PEM private key when not using self-service
- `CODA_JWT_KEY_ID`: JWT key id when not using self-service
- `CODA_REDIS_URL`: Redis URL for the job stream
- `CODA_WEBAPP_URL`: Coda base URL
- `CODA_EXECUTOR_FACTORY`: optional import path like `my_pkg.runner:create_executor`

## Reconnect workflow

After a successful self-service bootstrap, the runtime now persists the issued
credentials locally so later restarts can run without a fresh bootstrap token.

- JWT private key: `/tmp/coda-private-key`
- Runtime config: `/tmp/coda.config`

Both files are written with `0600` permissions on POSIX systems.

On later starts, `uv run coda start` automatically loads `/tmp/coda.config`,
reads the private key from `/tmp/coda-private-key`, and reuses the saved VPN
profile to bring the tunnel back up when `self_service_auto_vpn` is enabled.

If `CODA_EXECUTOR_FACTORY` is unset, the package uses a `NoopExecutor` that
acknowledges jobs and returns a deterministic zero bitstring result. That keeps
the scaffold runnable while making backend integration explicit.

## GitHub Actions

CI runs on Linux, macOS, and Windows with `uv`, and checks:

- `ruff check`
- `ruff format --check`
- `mypy`
- `pytest`

Local pre-commit checks:

```bash
uv run pre-commit run --all-files
```

## Custom executor

Provide a factory that returns an object implementing:

```python
async def run(ir: NativeGateIR, shots: int) -> ExecutionResult:
    ...
```

Example:

```python
from self_service.server.executor import ExecutionResult


class MyExecutor:
    async def run(self, ir, shots: int) -> ExecutionResult:
        return ExecutionResult(
            counts={"0" * len(ir.measurements): shots},
            execution_time_ms=1.0,
            shots_completed=shots,
        )


def create_executor():
    return MyExecutor()
```

Then set:

```bash
export CODA_EXECUTOR_FACTORY="my_project.executor:create_executor"
uv run coda start
```

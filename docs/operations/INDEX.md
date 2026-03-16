# Operations

Runtime operations cover health endpoints, graceful shutdown, the CLI,
and the exception hierarchy.

## Topics

| Document | Summary |
|---|---|
| [health-endpoints.md](health-endpoints.md) | `/health` and `/ready` endpoints for liveness and readiness probes. |
| [graceful-shutdown.md](graceful-shutdown.md) | Shutdown sequence: drain, cancel, close, cleanup. |
| [cli.md](cli.md) | `coda` CLI subcommands: `start`, `stop`, `status`, `logs`, `doctor`, `reset`, `stop-vpn`. |
| [error-handling.md](error-handling.md) | `CodaError` exception hierarchy and when each type is raised. |

## Key Files

| File | Role |
|---|---|
| `src/self_service/server/app.py` | FastAPI app, lifespan, `/health`, `/ready`. |
| `src/self_service/server/cli.py` | CLI entry point and subcommands. |
| `src/self_service/server/daemon.py` | Daemon process management (start, stop, status, logs). |
| `src/self_service/errors.py` | Exception hierarchy. |

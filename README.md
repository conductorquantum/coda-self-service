# coda-self-service

Production-ready runtime for connecting an execution backend to the Coda
cloud platform.

It boots a FastAPI service, provisions or reconnects node credentials, manages
VPN health, consumes Redis jobs, and posts signed execution results back to
Coda.

## What It Does

- Provisions a node from a one-time self-service token
- Reconnects on restart with persisted JWT credentials
- Verifies and continuously monitors VPN connectivity
- Consumes jobs from Redis Streams with crash recovery
- Sends JWT-signed webhook results to Coda with retry
- Drains in-flight work on graceful shutdown
- Supports pluggable execution backends
- Auto-detects hardware frameworks from a device configuration file

## Install

```bash
uv sync --dev
```

Requires Python 3.11+.  Two equivalent CLI entry points are installed:

- `coda`
- `coda-self-service`

## Quick Start

Provision with a self-service token:

```bash
uv run coda start --token <self-service-token>
```

Or set the token as an environment variable:

```bash
export CODA_SELF_SERVICE_TOKEN=<self-service-token>
uv run coda start
```

After a successful first run, credentials are persisted to disk and
subsequent restarts reconnect automatically without a fresh token.

## How It Works

On startup the runtime:

1. Loads configuration from `CODA_`-prefixed environment variables, then
   persisted state on disk, then hardcoded defaults.
2. Connects to Coda using either a self-service token or persisted JWT
   credentials (with exponential-backoff retry on transient failures).
3. Brings up or validates VPN connectivity when required.
4. Starts the FastAPI service and a background Redis Streams consumer.
5. Dispatches jobs to the configured executor and posts signed results
   back via webhook.

On shutdown the runtime drains the in-flight job (up to
`CODA_SHUTDOWN_DRAIN_TIMEOUT_SEC`), cancels background tasks, closes
connections, and stops the managed VPN daemon.

## Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness probe.  Returns `200` if the process is running. |
| `GET /ready` | Readiness probe.  Returns `200` with component status when VPN and Redis are healthy; `503` when either is degraded or the check times out. |

The `/ready` response body always includes `vpn_state`, `redis_healthy`,
and `current_job` fields for observability.

## Configuration

All settings are driven by `CODA_`-prefixed environment variables.  When
no self-service token is provided, the runtime automatically loads
previously persisted config from disk.

### Core

| Variable | Default | Description |
|---|---|---|
| `CODA_SELF_SERVICE_TOKEN` | `""` | One-time self-service token for first-run provisioning. |
| `CODA_JWT_PRIVATE_KEY` | `""` | PEM-encoded RSA private key for direct JWT startup. |
| `CODA_JWT_KEY_ID` | `""` | `kid` header value for signed JWTs. |
| `CODA_REDIS_URL` | `""` | Redis connection string (`redis://…`). |
| `CODA_WEBAPP_URL` | `""` | Coda cloud base URL. |
| `CODA_HOST` | `0.0.0.0` | Bind address for the FastAPI server. |
| `CODA_PORT` | `8080` | Bind port for the FastAPI server. |
| `CODA_EXECUTOR_FACTORY` | `""` | Import path for a custom executor (see below). |
| `CODA_DEVICE_CONFIG` | `""` | Path to a YAML device config for framework-based execution (see below). |

Provide either `CODA_SELF_SERVICE_TOKEN` for auto-provisioning, or both
`CODA_JWT_PRIVATE_KEY` and `CODA_JWT_KEY_ID` for direct JWT startup.

### VPN

| Variable | Default | Description |
|---|---|---|
| `CODA_VPN_REQUIRED` | `true` | Fail preflight if no VPN tunnel is detected. |
| `CODA_VPN_CHECK_INTERVAL_SEC` | `10` | Seconds between background VPN health checks. |
| `CODA_VPN_INTERFACE_HINT` | `null` | Specific TUN/TAP interface name to look for. |
| `CODA_ALLOW_DEGRADED_STARTUP` | `false` | Allow the server to start even if VPN preflight fails. |

### Resilience

| Variable | Default | Description |
|---|---|---|
| `CODA_SELF_SERVICE_CONNECT_RETRIES` | `3` | Max attempts when connecting to the Coda cloud. |
| `CODA_SHUTDOWN_DRAIN_TIMEOUT_SEC` | `30` | Seconds to wait for an in-flight job before forced shutdown. |
| `CODA_SELF_SERVICE_TIMEOUT_SEC` | `15` | HTTP timeout for self-service connect requests. |

## Persisted State

After a successful self-service provisioning the runtime writes:

| File | Contents |
|---|---|
| `/tmp/coda.config` | JSON with QPU identity, Redis URL, API paths, and VPN settings. |
| `/tmp/coda-private-key` | PEM-encoded RSA private key. |

Both files use `0600` permissions on POSIX systems and are validated on
read.  They enable token-free reconnects across restarts, preserving JWT
credentials, machine fingerprint, VPN profile path, and connection
settings.

To wipe persisted state, run `coda reset`.

## CLI

```
coda start [--token TOKEN] [--host HOST] [--port PORT] [--daemon]
```

Start the node server.  Pass `--token` on first run for self-service
provisioning.  Use `--daemon` (or `-d`) to run as a background process.

```
coda stop
```

Stop the background daemon process.

```
coda status
```

Show daemon status (running/stopped, PID, log file, VPN interface).

```
coda logs [-n LINES]
```

Show recent daemon log output (default: last 50 lines).

```
coda doctor
```

Print a diagnostic summary (endpoints, executor, VPN interface, OpenVPN
status).

```
coda stop-vpn
```

Stop the managed OpenVPN daemon without clearing credentials.

```
coda reset
```

Stop the daemon and VPN, then remove all persisted runtime files.

## Hardware Frameworks

For hardware backends that use a device configuration file (YAML), set
`CODA_DEVICE_CONFIG` to point at your device config:

```bash
export CODA_DEVICE_CONFIG="./device.yaml"
export CODA_SELF_SERVICE_TOKEN="..."
coda start
```

The runtime loads the config, auto-detects the appropriate framework
from the device target (or an explicit `framework` field), validates
the configuration, and creates the executor automatically.

Example `device.yaml`:

```yaml
target: superconducting_cz
num_qubits: 3
calibration_path: ./calibration.yaml
opx_host: 192.168.1.100
```

Third-party frameworks can be installed as Python packages and are
discovered automatically via `coda.frameworks` entry points.  See
[`docs/frameworks/`](docs/frameworks/INDEX.md) for full details on
creating a framework.

## Custom Executor

When neither `CODA_EXECUTOR_FACTORY` nor `CODA_DEVICE_CONFIG` is set,
the runtime uses a built-in `NoopExecutor` that returns deterministic
all-zeros results, allowing the service to boot without hardware
integration.

To connect a real backend, point the variable at a `module:attribute`
import path:

```bash
export CODA_EXECUTOR_FACTORY="my_project.executor:create_executor"
```

The target must be either a pre-built object with a `run` method, or a
callable factory.  If the factory accepts parameters, the `Settings`
object is passed in automatically.

```python
from self_service.server.executor import ExecutionResult
from self_service.server.ir import NativeGateIR


class MyExecutor:
    async def run(self, ir: NativeGateIR, shots: int) -> ExecutionResult:
        counts = run_on_hardware(ir, shots)
        return ExecutionResult(
            counts=counts,
            execution_time_ms=42.0,
            shots_completed=shots,
        )


def create_executor() -> MyExecutor:
    return MyExecutor()
```

## Error Handling

All domain exceptions inherit from `CodaError`, making it easy to
distinguish expected operational errors from unexpected bugs:

| Exception | When |
|---|---|
| `ConfigError` | Invalid or missing configuration. |
| `AuthError` | JWT signing or verification failure. |
| `VPNError` | VPN tunnel or health check failure. |
| `SelfServiceError` | Self-service provisioning or reconnect failure. |
| `ExecutorError` | Executor loading or job execution failure. |
| `WebhookError` | Webhook delivery failure. |

Import from the top-level package:

```python
from self_service import CodaError
from self_service.errors import ConfigError, VPNError
```

## Development

Install dependencies (including dev tools):

```bash
uv sync --dev
```

Run the full quality check suite:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/self_service
uv run pytest --cov --cov-report=term-missing
```

Install pre-commit hooks (runs ruff format and lint on every commit):

```bash
uv run pre-commit install
```

Run all hooks manually:

```bash
uv run pre-commit run --all-files
```

## Architecture

- **FastAPI** — HTTP service, lifespan management, health endpoints
- **Pydantic Settings** — environment-driven configuration with layered
  defaults and persisted state
- **Redis Streams** — job delivery with consumer groups and crash recovery
- **httpx** — async HTTP for webhooks and self-service API calls
- **RS256 JWT** — authentication between the node and the Coda cloud
- **OpenVPN** — managed as a subprocess when VPN connectivity is required

# Environment Variables

All environment variables use the `CODA_` prefix and map directly to
`Settings` fields. The Pydantic Settings model handles parsing,
including type coercion for booleans, integers, and lists.

## Quick Reference

### Required (one of)

| Variable | Description |
|---|---|
| `CODA_SELF_SERVICE_TOKEN` | One-time self-service token. Provides all other settings automatically. |
| `CODA_JWT_PRIVATE_KEY` + `CODA_JWT_KEY_ID` | Direct JWT startup (requires pre-provisioned credentials). |

### Commonly Set

| Variable | Default | Description |
|---|---|---|
| `CODA_HOST` | `0.0.0.0` | Bind address. |
| `CODA_PORT` | `8080` | Bind port. |
| `CODA_EXECUTOR_FACTORY` | `""` | Custom executor import path. When unset, the runtime auto-discovers factories from installed packages (see below). |
| `CODA_DEVICE_CONFIG` | `""` | Path to YAML device config read by the executor factory. Defaults to `./site/device.yaml` if that file exists. |
| `CODA_VPN_REQUIRED` | `true` | Whether VPN is mandatory. |
| `CODA_ALLOW_DEGRADED_STARTUP` | `false` | Start despite VPN failure. |

### Heartbeat

| Variable | Default | Description |
|---|---|---|
| `CODA_HEARTBEAT_INTERVAL_SEC` | `30` | Seconds between heartbeat POSTs to the Coda cloud. The heartbeat keeps the QPU showing as "online"; missing ~3 consecutive heartbeats causes the cloud to mark it offline. |

### Resilience Tuning

| Variable | Default | Description |
|---|---|---|
| `CODA_SELF_SERVICE_CONNECT_RETRIES` | `3` | Connect attempts before giving up. |
| `CODA_SELF_SERVICE_TIMEOUT_SEC` | `15` | HTTP timeout per connect attempt. |
| `CODA_SHUTDOWN_DRAIN_TIMEOUT_SEC` | `30` | Seconds to wait for in-flight jobs. |

### VPN Tuning

| Variable | Default | Description |
|---|---|---|
| `CODA_VPN_CHECK_INTERVAL_SEC` | `10` | Background health check interval. |
| `CODA_VPN_INTERFACE_HINT` | `null` | Specific TUN/TAP interface name. |
| `CODA_SELF_SERVICE_AUTO_VPN` | `true` | Auto-start OpenVPN from profile. |

### Rarely Changed

| Variable | Default | Description |
|---|---|---|
| `CODA_NATIVE_GATE_SET` | `cz` | Hardware target. |
| `CODA_NUM_QUBITS` | `5` | Device qubit count. |
| `CODA_WEBAPP_URL` | `https://coda.conductorquantum.com` | Coda cloud base URL. Overridden by the self-service bundle on connect. |
| `CODA_SELF_SERVICE_CONNECT_HEADERS` | `{}` | Extra headers for connect requests (JSON object). Used for deployment protection bypass. |
| `CODA_ADVERTISED_PROVIDER` | `coda` | Legacy local metadata field. Not part of the self-service contract. |

### Auto-Populated (set by self-service)

These are populated from the connect response during self-service and
persisted to disk. They do not need to be set manually:

- `CODA_QPU_ID`
- `CODA_QPU_DISPLAY_NAME`
- `CODA_REDIS_URL`
- `CODA_WEBAPP_URL`
- `CODA_JWT_PRIVATE_KEY`
- `CODA_JWT_KEY_ID`
- `CODA_CONNECT_PATH`, `CODA_HEARTBEAT_PATH`, `CODA_WEBHOOK_PATH`
- `CODA_VPN_PROBE_TARGETS`
- `CODA_SELF_SERVICE_MACHINE_FINGERPRINT`

## CLI Overrides

The `coda start` command accepts flags that override env vars:

| Flag | Overrides |
|---|---|
| `--host HOST` | `CODA_HOST` |
| `--port PORT` | `CODA_PORT` |
| `--token TOKEN` | `CODA_SELF_SERVICE_TOKEN` |

These are injected into the environment before `Settings` is
constructed, so they take precedence over both env vars and persisted
config.

## Executor Auto-Discovery

When `CODA_EXECUTOR_FACTORY` is not set, the runtime scans installed
packages for the naming convention
`<package>.executor_factory:create_executor`.  If exactly one match is
found, it is used automatically.  If multiple matches are found, a
warning is logged and the runtime falls back to `NoopExecutor`.

Set `CODA_EXECUTOR_FACTORY` explicitly to skip discovery and force a
specific factory:

```bash
export CODA_EXECUTOR_FACTORY="coda_acme.executor_factory:create_executor"
```

See [Auto-Discovery](../frameworks/REGISTRY.md) for details.

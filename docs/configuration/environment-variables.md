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
| `CODA_EXECUTOR_FACTORY` | `""` | Custom executor import path. |
| `CODA_DEVICE_CONFIG` | `""` | Path to YAML device config for framework-based execution. See [Device Configuration](../frameworks/device-config.md). |
| `CODA_VPN_REQUIRED` | `true` | Whether VPN is mandatory. |
| `CODA_ALLOW_DEGRADED_STARTUP` | `false` | Start despite VPN failure. |

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
| `CODA_NATIVE_GATE_SET` | `superconducting_cz` | Hardware target. |
| `CODA_NUM_QUBITS` | `5` | Device qubit count. |
| `CODA_OPX_HOST` | `localhost` | Optional local executor setting for an OPX controller host. Not sent during self-service connect. |
| `CODA_OPX_PORT` | `80` | Optional local executor setting for an OPX controller port. Not sent during self-service connect. |
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
- `CODA_CONNECT_PATH`, `CODA_REGISTER_PATH`, `CODA_HEARTBEAT_PATH`,
  `CODA_WEBHOOK_PATH`
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

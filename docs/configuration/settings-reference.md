# Settings Reference

Complete field reference for the `Settings` class in
`server/config.py`.

## Identity

| Field | Type | Default | Env Var | Description |
|---|---|---|---|---|
| `qpu_id` | `str` | `""` | `CODA_QPU_ID` | QPU identifier (set during self-service). |
| `qpu_display_name` | `str` | `""` | `CODA_QPU_DISPLAY_NAME` | Human-readable QPU name. |
| `native_gate_set` | `str` | `"superconducting_cz"` | `CODA_NATIVE_GATE_SET` | Hardware target gate set. |
| `num_qubits` | `int` | `5` | `CODA_NUM_QUBITS` | Number of qubits on the device. |

## Connectivity

| Field | Type | Default | Env Var | Description |
|---|---|---|---|---|
| `redis_url` | `str` | `""` | `CODA_REDIS_URL` | Redis connection string. |
| `webapp_url` | `str` | `""` | `CODA_WEBAPP_URL` | Coda cloud base URL. |
| `host` | `str` | `"0.0.0.0"` | `CODA_HOST` | FastAPI bind address. |
| `port` | `int` | `8080` | `CODA_PORT` | FastAPI bind port. |

## API Paths

| Field | Type | Default | Env Var | Description |
|---|---|---|---|---|
| `webhook_path` | `str` | `"/api/internal/qpu/webhook"` | `CODA_WEBHOOK_PATH` | Webhook delivery path. |
| `connect_path` | `str` | `"/api/internal/qpu/connect"` | `CODA_CONNECT_PATH` | Self-service connect path. |
| `register_path` | `str` | `"/api/internal/qpu/register"` | `CODA_REGISTER_PATH` | QPU registration path. |
| `heartbeat_path` | `str` | `"/api/internal/qpu/heartbeat"` | `CODA_HEARTBEAT_PATH` | Heartbeat reporting path. |
| `self_service_path` | `str` | `"/api/internal/qpu/self-service"` | `CODA_SELF_SERVICE_PATH` | Legacy self-service path. |

## Authentication

| Field | Type | Default | Env Var | Description |
|---|---|---|---|---|
| `jwt_private_key` | `str` | `""` | `CODA_JWT_PRIVATE_KEY` | PEM-encoded RSA private key. |
| `jwt_key_id` | `str` | `""` | `CODA_JWT_KEY_ID` | JWT `kid` header value. |
| `self_service_token` | `str` | `""` | `CODA_SELF_SERVICE_TOKEN` | One-time self-service token. |

## VPN

| Field | Type | Default | Env Var | Description |
|---|---|---|---|---|
| `vpn_required` | `bool` | `True` | `CODA_VPN_REQUIRED` | Fail preflight without VPN. |
| `vpn_check_interval_sec` | `int` | `10` | `CODA_VPN_CHECK_INTERVAL_SEC` | Background check interval. |
| `vpn_probe_targets` | `list[str]` | `[]` | `CODA_VPN_PROBE_TARGETS` | URLs to probe for VPN health. |
| `vpn_interface_hint` | `str \| None` | `None` | `CODA_VPN_INTERFACE_HINT` | Specific interface to look for. |
| `allow_degraded_startup` | `bool` | `False` | `CODA_ALLOW_DEGRADED_STARTUP` | Allow startup despite VPN failure. |

## Self-Service

| Field | Type | Default | Env Var | Description |
|---|---|---|---|---|
| `self_service_timeout_sec` | `int` | `15` | `CODA_SELF_SERVICE_TIMEOUT_SEC` | HTTP timeout for connect requests. |
| `self_service_connect_retries` | `int` | `3` | `CODA_SELF_SERVICE_CONNECT_RETRIES` | Max connect attempts. |
| `self_service_machine_fingerprint` | `str` | `""` | `CODA_SELF_SERVICE_MACHINE_FINGERPRINT` | Explicit machine fingerprint (auto-generated if empty). |
| `self_service_auto_vpn` | `bool` | `True` | `CODA_SELF_SERVICE_AUTO_VPN` | Auto-start OpenVPN from profile. |
| `self_service_vpn_profile_path` | `str` | `/tmp/coda-self-service.ovpn` | `CODA_SELF_SERVICE_VPN_PROFILE_PATH` | Path to write VPN profile. |

## Execution

| Field | Type | Default | Env Var | Description |
|---|---|---|---|---|
| `executor_factory` | `str` | `""` | `CODA_EXECUTOR_FACTORY` | Import path for custom executor. |
| `device_config` | `str` | `""` | `CODA_DEVICE_CONFIG` | Path to a YAML device configuration file for framework-based execution. See [Device Configuration](../frameworks/device-config.md). |
| `advertised_provider` | `str` | `"coda"` | `CODA_ADVERTISED_PROVIDER` | Legacy local metadata field. Not used by the self-service connect handshake. |
| `opx_host` | `str` | `"localhost"` | `CODA_OPX_HOST` | Optional local executor setting for an OPX controller hostname. Not sent to the cloud connect endpoint. |
| `opx_port` | `int` | `80` | `CODA_OPX_PORT` | Optional local executor setting for an OPX controller port. Not sent to the cloud connect endpoint. |

## Resilience

| Field | Type | Default | Env Var | Description |
|---|---|---|---|---|
| `shutdown_drain_timeout_sec` | `int` | `30` | `CODA_SHUTDOWN_DRAIN_TIMEOUT_SEC` | Max drain wait on shutdown. |

## Computed Properties

| Property | Returns | Description |
|---|---|---|
| `callback_url` | `str` | `{webapp_url}{webhook_path}` |
| `register_url` | `str` | `{webapp_url}{register_path}` |
| `connect_url` | `str` | `{webapp_url}{connect_path}` |
| `heartbeat_url` | `str` | `{webapp_url}{heartbeat_path}` |
| `vpn_probe_urls` | `list[str]` | `vpn_probe_targets` if set, else `[connect_url, heartbeat_url]`. |

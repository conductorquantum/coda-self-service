# Settings Reference

Complete field reference for the `Settings` class in
`server/config.py`.

## Identity

| Field | Type | Default | Env Var | Description |
|---|---|---|---|---|
| `qpu_id` | `str` | `""` | `CODA_QPU_ID` | QPU identifier (set during node provisioning). |
| `qpu_display_name` | `str` | `""` | `CODA_QPU_DISPLAY_NAME` | Human-readable QPU name. |
| `native_gate_set` | `str` | `"cz"` | `CODA_NATIVE_GATE_SET` | Hardware target gate set. |
| `num_qubits` | `int` | `5` | `CODA_NUM_QUBITS` | Number of qubits on the device. |

## Connectivity

| Field | Type | Default | Env Var | Description |
|---|---|---|---|---|
| `redis_url` | `str` | `""` | `CODA_REDIS_URL` | Redis connection string. |
| `webapp_url` | `str` | `"https://coda.conductorquantum.com"` | `CODA_WEBAPP_URL` | Coda cloud base URL. Overridden by the node bundle on connect. |
| `host` | `str` | `"0.0.0.0"` | `CODA_HOST` | FastAPI bind address. |
| `port` | `int` | `8080` | `CODA_PORT` | FastAPI bind port. |

## API Paths

| Field | Type | Default | Env Var | Description |
|---|---|---|---|---|
| `webhook_path` | `str` | `"/api/internal/qpu/webhook"` | `CODA_WEBHOOK_PATH` | Webhook delivery path. |
| `connect_path` | `str` | `"/api/internal/qpu/connect"` | `CODA_CONNECT_PATH` | Node connect path. |
| `heartbeat_path` | `str` | `"/api/internal/qpu/heartbeat"` | `CODA_HEARTBEAT_PATH` | Heartbeat reporting path. |

## Authentication

| Field | Type | Default | Env Var | Description |
|---|---|---|---|---|
| `jwt_private_key` | `str` | `""` | `CODA_JWT_PRIVATE_KEY` | PEM-encoded RSA private key. |
| `jwt_key_id` | `str` | `""` | `CODA_JWT_KEY_ID` | JWT `kid` header value. |
| `node_token` | `str` | `""` | `CODA_NODE_TOKEN` | One-time node token. |

## VPN

| Field | Type | Default | Env Var | Description |
|---|---|---|---|---|
| `vpn_required` | `bool` | `True` | `CODA_VPN_REQUIRED` | Fail preflight without VPN. Automatically set to `False` by the connect response when the node token's `connection_mode` is `"https"`. |
| `vpn_check_interval_sec` | `int` | `10` | `CODA_VPN_CHECK_INTERVAL_SEC` | Background check interval. |
| `vpn_probe_targets` | `list[str]` | `[]` | `CODA_VPN_PROBE_TARGETS` | URLs to probe for VPN health. |
| `vpn_interface_hint` | `str \| None` | `None` | `CODA_VPN_INTERFACE_HINT` | Specific interface to look for. |
| `allow_degraded_startup` | `bool` | `False` | `CODA_ALLOW_DEGRADED_STARTUP` | Allow startup despite VPN failure. |

## Node

| Field | Type | Default | Env Var | Description |
|---|---|---|---|---|
| `node_timeout_sec` | `int` | `15` | `CODA_NODE_TIMEOUT_SEC` | HTTP timeout for connect requests. |
| `node_connect_headers` | `dict[str, str]` | `{}` | `CODA_NODE_CONNECT_HEADERS` | Extra headers for connect requests (e.g. deployment protection bypass). |
| `node_connect_retries` | `int` | `3` | `CODA_NODE_CONNECT_RETRIES` | Max connect attempts. |
| `node_machine_fingerprint` | `str` | `""` | `CODA_NODE_MACHINE_FINGERPRINT` | Explicit machine fingerprint (auto-generated if empty). |
| `node_auto_vpn` | `bool` | `True` | `CODA_NODE_AUTO_VPN` | Auto-start OpenVPN from profile. |
| `node_vpn_profile_path` | `str` | `/tmp/coda-node.ovpn` | `CODA_NODE_VPN_PROFILE_PATH` | Path to write VPN profile. |

## Execution

| Field | Type | Default | Env Var | Description |
|---|---|---|---|---|
| `executor_factory` | `str` | `""` | `CODA_EXECUTOR_FACTORY` | Import path for a custom executor factory (`module:attr` format). When unset, the runtime falls back to the device config's top-level `executor_factory` key before auto-discovery. See [Executor Factory Convention](../frameworks/FRAMEWORK_PROTOCOL.md). |
| `device_config` | `str` | `""` | `CODA_DEVICE_CONFIG` | Path to a YAML device configuration file, read by the executor factory. Defaults to `./site/device.yaml` if that file exists. The runtime also reads an optional top-level `executor_factory` key from this file when the env var is unset. See [Device Configuration](../frameworks/DEVICE_CONFIG.md). |
| `advertised_provider` | `str` | `"coda"` | `CODA_ADVERTISED_PROVIDER` | Legacy local metadata field. Not used by the node connect handshake. |
| `consumer_batch_size` | `int` | `1` | `CODA_CONSUMER_BATCH_SIZE` | Max jobs to read from Redis and dispatch together when the executor implements `batch_run()`. Values greater than `1` fall back to single-job processing if batch support is unavailable. See [Redis Consumer](../jobs/CONSUMER.md). |

## Heartbeat

| Field | Type | Default | Env Var | Description |
|---|---|---|---|---|
| `heartbeat_interval_sec` | `int` | `30` | `CODA_HEARTBEAT_INTERVAL_SEC` | Seconds between heartbeat POSTs to the Coda cloud. Keeps the QPU status "online". |

## Resilience

| Field | Type | Default | Env Var | Description |
|---|---|---|---|---|
| `shutdown_drain_timeout_sec` | `int` | `30` | `CODA_SHUTDOWN_DRAIN_TIMEOUT_SEC` | Max drain wait on shutdown. |

## Computed Properties

| Property | Returns | Description |
|---|---|---|
| `callback_url` | `str` | `{webapp_url}{webhook_path}` |
| `connect_url` | `str` | `{webapp_url}{connect_path}` |
| `heartbeat_url` | `str` | `{webapp_url}{heartbeat_path}` |
| `vpn_probe_urls` | `list[str]` | `vpn_probe_targets` if set, else `[connect_url, heartbeat_url]`. |

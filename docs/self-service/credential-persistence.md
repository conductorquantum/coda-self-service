# Credential Persistence

After a successful self-service provisioning or reconnect, the node writes runtime
state to disk so subsequent restarts can reconnect without a fresh
token.

## Persisted Files

| File | Contents | Permissions |
|---|---|---|
| `/tmp/coda.config` | JSON object with QPU identity, Redis URL, API paths, VPN settings, and a pointer to the private key file. | `0600` |
| `/tmp/coda-private-key` | PEM-encoded RSA private key for JWT signing. | `0600` |

Both paths are defined as constants in `server/config.py`:

```python
PERSISTED_CONFIG_PATH = Path(tempfile.gettempdir()) / "coda.config"
PERSISTED_PRIVATE_KEY_PATH = Path(tempfile.gettempdir()) / "coda-private-key"
```

## Config File Format

`/tmp/coda.config` contains a JSON object with these fields:

```json
{
  "qpu_id": "my-qpu",
  "qpu_display_name": "My QPU",
  "native_gate_set": "superconducting_cz",
  "num_qubits": 5,
  "jwt_key_id": "qpu-my-qpu-1710000000000",
  "jwt_private_key_path": "/tmp/coda-private-key",
  "redis_url": "rediss://default:token@host:6379",
  "webapp_url": "https://app.coda.example",
  "connect_path": "/api/internal/qpu/connect",
  "register_path": "/api/internal/qpu/register",
  "heartbeat_path": "/api/internal/qpu/heartbeat",
  "webhook_path": "/api/internal/qpu/webhook",
  "vpn_required": true,
  "vpn_check_interval_sec": 10,
  "vpn_interface_hint": null,
  "vpn_probe_targets": ["https://app.coda.example/api/internal/qpu/health"],
  "self_service_auto_vpn": true,
  "self_service_vpn_profile_path": "/tmp/coda-self-service.ovpn",
  "self_service_machine_fingerprint": "hostname-12345"
}
```

Executor-specific local settings such as `CODA_OPX_HOST` and `CODA_OPX_PORT`
are not part of the persisted self-service contract; they should be supplied
explicitly via environment variables when needed.

## Write Path

`_persist_runtime_config()` in `vpn/service.py`:

1. Writes the JWT private key to `PERSISTED_PRIVATE_KEY_PATH` with
   `0600` permissions.
2. Serializes the runtime config to `PERSISTED_CONFIG_PATH` with `0600`
   permissions.

This is called from `connect_settings()` after `apply_self_service_bundle()`
succeeds.

## Read Path

`load_persisted_runtime_config()` in `server/config.py`:

1. Checks if `PERSISTED_CONFIG_PATH` exists.
2. Reads and validates `0600` permissions via `_read_secure_text()`.
3. Parses the JSON and extracts known keys into a settings dict.
4. Reads the private key from the path stored in
   `jwt_private_key_path` (or the default `PERSISTED_PRIVATE_KEY_PATH`).
5. Returns the merged dictionary of overrides.

This is invoked by the `Settings` Pydantic model validator
`merge_persisted_runtime_config()`, which runs at model construction
time. It only applies persisted values when no `self_service_token` is
set (to avoid overriding a fresh provisioning with stale state).

## Precedence Order

Settings are resolved with the following priority (highest first):

1. **Environment variables** — `CODA_`-prefixed (e.g. `CODA_REDIS_URL`).
2. **Persisted config** — loaded from `/tmp/coda.config`.
3. **Hardcoded defaults** — defined on the `Settings` class.

A persisted value only fills in a field when the environment has not
already set it (i.e., the current value is empty, `None`, or `[]`).

## Security

- **File permissions**: Both files must have `0600` permissions on POSIX
  systems. `_read_secure_text()` raises `ConfigError` if the file exists
  but has wrong permissions.
- **Private key isolation**: The private key is stored in a separate
  file rather than inline in the JSON config, reducing the risk of
  accidental exposure through config file logging or debugging.

## Cleanup

`coda reset` removes all persisted state:

1. Stops the managed OpenVPN daemon.
2. Deletes `PERSISTED_CONFIG_PATH`, `PERSISTED_PRIVATE_KEY_PATH`,
   `OPENVPN_PID_PATH`, `OPENVPN_LOG_PATH`, the VPN profile, and any
   additional paths referenced in the config file.

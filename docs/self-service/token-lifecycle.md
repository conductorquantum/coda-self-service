# Self-Service Token Lifecycle

Self-service tokens are one-time-use credentials created by operators in
the Coda webapp. They carry QPU metadata and policy but no VPN
credentials — VPN provisioning happens at connect time.

## Token States

```
created → redeemed
       → revoked
       → expired
```

| State | Condition |
|---|---|
| **Active** | `redeemed_at IS NULL AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at > now())` |
| **Redeemed** | `redeemed_at IS NOT NULL` — consumed during a successful self-service provisioning. |
| **Revoked** | `revoked_at IS NOT NULL` — manually invalidated by an operator. |
| **Expired** | `expires_at <= now()` — past its time-to-live. |

Only active tokens can be used for self-service. The cloud returns
descriptive errors for each invalid state:

- `"QPU self-service token has already been used"` (redeemed)
- `"QPU self-service token has been revoked"` (revoked)
- `"QPU self-service token has expired"` (expired)

## Token Config

The token's `config` JSON object stores QPU policy set at creation time:

| Field | Type | Description |
|---|---|---|
| `display_name` | `string` | QPU display name (required). |
| `native_gate_set` | `string` | Hardware target (required). |
| `num_qubits` | `int` | Qubit count (required). |
| `vpn_required` | `bool` | Whether VPN is mandatory (default: `true`). |
| `vpn_interface_hint` | `string` | Specific TUN/TAP interface to look for. |
| `vpn_check_interval_sec` | `int` | Background health check interval (default: `10`). |

The `vpn_client_profile_ovpn` field is explicitly excluded from token
storage (`normalizeSelfServiceQPUTokenConfig`) and stripped from API
responses (`redactSelfServiceQPUToken`) as a defense-in-depth measure.

## Token Verification

On the cloud side, `verifyQpuSelfServiceToken()` in `self-service.ts`:

1. Extracts the bearer token from the `Authorization` header.
2. Computes `SHA-256(token)` and looks it up via the
   `lookup_bootstrap_token` database function (cloud-side naming).
3. If not found in the active view, queries `qpu_bootstrap_tokens` (cloud-side table)
   directly to determine the specific failure reason.
4. Returns the full token row (including `config` and `qpu_id`).

## Token Redemption

Tokens are redeemed atomically inside the cloud-side
`prepare_qpu_device_from_bootstrap_token` PostgreSQL function:

1. Locks the token row (`FOR UPDATE`).
2. Validates it is still active.
3. Creates or updates the `qpu_devices` row with identity, gate set,
   qubit count, JWT key reference, and machine fingerprint.
4. Sets `redeemed_at = now()` and stores `redeemed_fingerprint`.

The `ON CONFLICT (id) DO UPDATE` clause means re-provisioning the same
`qpu_id` with a new token overwrites the device metadata and rotates
the JWT key, while preserving the machine fingerprint if one was already
enrolled.

## Node-Side Token Usage

The node receives the self-service token via:

- CLI flag: `coda start --token <token>`
- Environment variable: `CODA_SELF_SERVICE_TOKEN`

When `Settings.self_service_token` is non-empty, the node calls
`fetch_self_service_bundle()` which POSTs the token as
`Authorization: Bearer <token>` together with the node's
`machine_fingerprint`.

After a successful first run, credentials are persisted to disk and the
token is no longer needed. Subsequent restarts use JWT reconnect
automatically.

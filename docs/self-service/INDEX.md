# Self-Service Provisioning & Reconnect

Self-service provisioning is the mechanism by which a QPU node obtains
its identity, JWT credentials, Redis connection, API paths, and
(optionally) a VPN profile from the Coda cloud. There are two auth modes:

- **Self-service** — first-run provisioning using a one-time token.
- **Reconnect** — subsequent starts using persisted JWT credentials.

Both modes use the same cloud endpoint (`POST /api/internal/qpu/connect`)
and receive the same response shape.

Additionally, the token's **connection mode** (`"vpn"` or `"https"`)
controls whether VPN infrastructure is provisioned:

- **VPN mode** (default): An OpenVPN profile is generated and the node
  routes traffic through an AWS Client VPN tunnel.
- **HTTPS mode**: VPN is skipped. The node connects directly over the
  public internet using TLS. Useful when VPN is blocked by network
  policy (e.g. university firewalls).

## Topics

| Document | Summary |
|---|---|
| [connect-protocol.md](connect-protocol.md) | The `/connect` handshake: request/response format, auth modes, and error handling. |
| [token-lifecycle.md](token-lifecycle.md) | Self-service token creation, redemption, expiry, and revocation on the cloud side. |
| [credential-persistence.md](credential-persistence.md) | How the node persists and reloads JWT credentials, VPN profiles, and runtime config across restarts. |

## Key Files

| File | Role |
|---|---|
| `src/self_service/vpn/service.py` | `connect_settings()`, `fetch_self_service_bundle()`, `fetch_reconnect_bundle()`, `apply_self_service_bundle()`, `ensure_persisted_vpn()` |
| `src/self_service/server/config.py` | `Settings`, `load_persisted_runtime_config()` |
| `src/self_service/server/auth.py` | `sign_token()` for JWT-authenticated reconnect |

## Cloud Counterparts

| Cloud File | Role |
|---|---|
| `coda-webapp/app/api/internal/qpu/connect/route.ts` | HTTP handler — dispatches self-service vs reconnect based on bearer token format. |
| `coda-webapp/lib/qpu/self-service.ts` | `buildSelfServiceResponse()` (first-run), `buildReconnectResponse()` (JWT reconnect). |

## Sequence Diagram

```
First run (self-service, VPN mode):

  Operator                  Node Runtime                  Coda Cloud
     │                           │                            │
     │── coda start --token ──►  │                            │
     │                           │── POST /connect ──────────►│
     │                           │   Authorization: Bearer <token>
     │                           │   { machine_fingerprint }  │
     │                           │                            │── verify token
     │                           │                            │── generate JWT keypair
     │                           │                            │── provision VPN cert
     │                           │                            │── redeem token
     │                           │◄── bundle response ────────│
     │                           │   { qpu_id, jwt_private_key, redis_url,
     │                           │     vpn: { required: true, client_profile_ovpn: "..." }, ... }
     │                           │── apply bundle             │
     │                           │── write /tmp/coda.config    │
     │                           │── start OpenVPN             │
     │                           │── start Redis consumer      │
     │                           │                            │

First run (self-service, HTTPS mode):

  Operator                  Node Runtime                  Coda Cloud
     │                           │                            │
     │── coda start --token ──►  │                            │
     │                           │── POST /connect ──────────►│
     │                           │   Authorization: Bearer <token>
     │                           │   { machine_fingerprint }  │
     │                           │                            │── verify token
     │                           │                            │── generate JWT keypair
     │                           │                            │── skip VPN provisioning
     │                           │                            │── redeem token
     │                           │◄── bundle response ────────│
     │                           │   { qpu_id, jwt_private_key, redis_url,
     │                           │     vpn: { required: false, client_profile_ovpn: null }, ... }
     │                           │── apply bundle             │
     │                           │── write /tmp/coda.config    │
     │                           │── start Redis consumer      │
     │                           │   (no OpenVPN)             │
     │                           │                            │

Subsequent run (reconnect):

  Node Runtime                  Coda Cloud
     │                            │
     │── POST /connect ──────────►│
     │   Authorization: Bearer <jwt>
     │   { machine_fingerprint }  │
     │                            │── verify JWT signature
     │                            │── verify fingerprint match
     │                            │── provision fresh VPN cert (VPN mode only)
     │◄── bundle response ────────│
     │   { qpu_id, redis_url,    │
     │     vpn: { ... }, ... }
     │   (no jwt_private_key on reconnect)
```

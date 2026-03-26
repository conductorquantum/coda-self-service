# Node Provisioning & Reconnect

Node provisioning is the mechanism by which a QPU node obtains
its identity, JWT credentials, Redis connection, API paths, and
(optionally) a VPN profile from the Coda cloud. There are two auth modes:

- **Node** — first-run provisioning using a one-time token.
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
| [CONNECT_PROTOCOL.md](CONNECT_PROTOCOL.md) | The `/connect` handshake: request/response format, auth modes, and error handling. |
| [TOKEN_LIFECYCLE.md](TOKEN_LIFECYCLE.md) | Node token creation, redemption, expiry, and revocation on the cloud side. |
| [CREDENTIAL_PERSISTENCE.md](CREDENTIAL_PERSISTENCE.md) | How the node persists and reloads JWT credentials, VPN profiles, and runtime config across restarts. |

## Key Files

| File | Role |
|---|---|
| `src/coda_node/vpn/service.py` | `connect_settings()`, `fetch_node_bundle()`, `fetch_reconnect_bundle()`, `apply_node_bundle()`, `ensure_persisted_vpn()` |
| `src/coda_node/server/config.py` | `Settings`, `load_persisted_runtime_config()` |
| `src/coda_node/server/auth.py` | `sign_token()` for JWT-authenticated reconnect |

## Cloud Counterparts

| Cloud File | Role |
|---|---|
| `coda-webapp/app/api/internal/qpu/connect/route.ts` | HTTP handler — dispatches node provisioning vs reconnect based on bearer token format. |
| `coda-webapp/lib/qpu/self-service.ts` | `buildNodeResponse()` (first-run), `buildReconnectResponse()` (JWT reconnect). |

## Sequence Diagram

```
First run (node provisioning, VPN mode):

  Operator                  Node Runtime                  Coda Cloud
     │                           │                            │
     │── coda start --token ──►  │                            │
     │                           │── POST /connect ──────────►│
     │                           │   Authorization: Bearer <token>
     │                           │   { machine_fingerprint }  │
     │                           │                            │── verify token
     │                           │                            │── generate JWT keypair
     │                           │                            │── provision VPN cert
     │                           │                            │── redeem node token
     │                           │◄── bundle response ────────│
     │                           │   { qpu_id, jwt_private_key, redis_url,
     │                           │     vpn: { required: true, client_profile_ovpn: "..." }, ... }
     │                           │── apply bundle             │
     │                           │── write /tmp/coda.config    │
     │                           │── start OpenVPN             │
     │                           │── start Redis consumer      │
     │                           │                            │

First run (node provisioning, HTTPS mode):

  Operator                  Node Runtime                  Coda Cloud
     │                           │                            │
     │── coda start --token ──►  │                            │
     │                           │── POST /connect ──────────►│
     │                           │   Authorization: Bearer <token>
     │                           │   { machine_fingerprint }  │
     │                           │                            │── verify token
     │                           │                            │── generate JWT keypair
     │                           │                            │── skip VPN provisioning
     │                           │                            │── redeem node token
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

# VPN Management

The VPN subsystem provides secure network connectivity between the
QPU node and the Coda cloud. It handles three concerns:

1. **Provisioning** — receiving an OpenVPN profile during node provisioning,
   validating it for safety, and launching a managed daemon.
2. **Health monitoring** — detecting the tunnel interface, probing
   cloud endpoints, and continuously evaluating VPN health.
3. **Lifecycle management** — starting, stopping, and restarting the
   OpenVPN daemon across node restarts.

> **Note:** The VPN subsystem is only active when the token's
> `connection_mode` is `"vpn"` (the default). When `connection_mode` is
> `"https"`, the cloud sets `vpn.required = false` and omits the VPN
> profile. The node skips OpenVPN entirely and VPNGuard passes preflight
> unconditionally. See [Connect Protocol](../node/CONNECT_PROTOCOL.md)
> for details on connection modes.

## Topics

| Document | Summary |
|---|---|
| [TUNNEL_LIFECYCLE.md](TUNNEL_LIFECYCLE.md) | OpenVPN profile handling, daemon management, and tunnel detection. |
| [HEALTH_MONITORING.md](HEALTH_MONITORING.md) | VPNGuard preflight checks and background watch loop. |
| [CLOUD_INFRASTRUCTURE.md](CLOUD_INFRASTRUCTURE.md) | AWS Client VPN architecture and per-QPU certificate issuance on the cloud side. |

## Key Files

| File | Role |
|---|---|
| `src/coda_node/vpn/guard.py` | `VPNGuard` class — preflight, watch loop, platform-specific interface detection. |
| `src/coda_node/vpn/service.py` | OpenVPN daemon management, profile validation, tunnel polling. |
| `src/coda_node/vpn/__init__.py` | Public API re-exports for the VPN package. |

## Cloud Counterparts

| Cloud File | Role |
|---|---|
| `coda-webapp/lib/qpu/vpn-cert.ts` | Per-QPU client certificate generation, ACM import, `.ovpn` profile assembly. |
| `scripts/setup_client_vpn.sh` | Idempotent AWS Client VPN endpoint provisioning. |
| `coda-webapp/app/api/internal/qpu/health/route.ts` | Unauthenticated health probe used by VPN guard. |

## Architecture Overview

```
QPU Node                                          Coda Cloud (AWS)
┌─────────────────────────┐                       ┌─────────────────────────┐
│  VPNGuard               │                       │  AWS Client VPN         │
│  ├─ preflight()         │                       │  ├─ Endpoint (mTLS)     │
│  │  ├─ detect interface │                       │  ├─ CA (Easy-RSA)       │
│  │  ├─ DNS resolution   │                       │  ├─ Server cert (ACM)   │
│  │  └─ HTTP probes ─────┼──── VPN tunnel ──────►│  └─ Client certs (ACM)  │
│  └─ watch()             │                       │                         │
│     └─ periodic recheck │                       │  VPN Cert Issuance      │
│                         │                       │  ├─ Per-init identity   │
│  OpenVPN daemon         │                       │  ├─ Atomic claim        │
│  ├─ .ovpn profile       │                       │  └─ node-forge signing  │
│  ├─ PID file            │                       │                         │
│  └─ Log file            │                       │  Health Probe           │
│                         │                       │  └─ GET /qpu/health     │
└─────────────────────────┘                       └─────────────────────────┘
```

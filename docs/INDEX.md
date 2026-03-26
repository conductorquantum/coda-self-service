# coda-node Documentation

Comprehensive documentation for the Coda node runtime.

## Feature Areas

| Area | Description | Directory |
|---|---|---|
| [Node & Reconnect](node/INDEX.md) | Node provisioning, connect protocol, token lifecycle, credential persistence. | `docs/node/` |
| [VPN Management](vpn/INDEX.md) | OpenVPN tunnel lifecycle, health monitoring, cloud VPN infrastructure. | `docs/vpn/` |
| [Hardware Frameworks](frameworks/INDEX.md) | Pluggable hardware control frameworks, device config, auto-detection. | `docs/frameworks/` |
| [Job Execution](jobs/INDEX.md) | Redis Streams consumer, NativeGateIR schema, custom execution backends. | `docs/jobs/` |
| [Webhooks](webhooks/INDEX.md) | Authenticated result delivery, retry logic, payload format. | `docs/webhooks/` |
| [JWT Authentication](auth/INDEX.md) | RS256 JWT signing and verification, keypair lifecycle. | `docs/auth/` |
| [Configuration](configuration/INDEX.md) | Settings reference, environment variables, persisted state. | `docs/configuration/` |
| [Operations](operations/INDEX.md) | Health endpoints, graceful shutdown, CLI, error handling. | `docs/operations/` |

## Architecture

The node supports two connection modes, configured per-token in the Coda webapp:

- **VPN mode** (default): traffic is routed through an AWS Client VPN tunnel (OpenVPN, mTLS).
- **HTTPS mode**: traffic flows directly over the public internet using TLS. No VPN software is required.

```
┌─────────────────────────────────────────────────────────────┐
│                        Coda Cloud                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ /qpu/connect │  │ /qpu/webhook │  │ Redis Streams    │  │
│  │ (node)       │  │  (results)   │  │  qpu:{id}:jobs   │  │
│  └──────┬───────┘  └──────▲───────┘  └────────┬─────────┘  │
│         │                 │                    │            │
│         │  VPN mode: AWS Client VPN (mTLS)     │            │
│         │  HTTPS mode: direct TLS              │            │
└─────────┼─────────────────┼────────────────────┼────────────┘
          │                 │                    │
    ┌─────▼─────────────────┼────────────────────▼────────┐
    │                  Node Runtime                        │
    │                                                      │
    │  ┌─────────────┐  ┌──────────────┐  ┌────────────┐  │
    │  │ Settings     │  │ VPNGuard     │  │ OpenVPN    │  │
    │  │ (config.py)  │  │ (guard.py)   │  │ (daemon)   │  │
    │  └──────┬───────┘  └──────┬───────┘  └────────────┘  │
    │         │                 │           (VPN mode only) │
    │  ┌──────▼───────┐  ┌─────▼────────┐                  │
    │  │ Provisioner  │  │ /health      │                  │
    │  │ (service.py) │  │ /ready       │                  │
    │  └──────────────┘  └──────────────┘                  │
    │                                                      │
    │  ┌──────────────┐  ┌──────────────┐  ┌────────────┐  │
    │  │ RedisConsumer │─►│ JobExecutor  │  │ Webhook    │  │
    │  │ (consumer.py)│  │ (executor.py)│──►│ Client     │  │
    │  └──────────────┘  └──────────────┘  └────────────┘  │
    └──────────────────────────────────────────────────────┘
```

In HTTPS mode, the OpenVPN daemon is not started and VPNGuard passes
preflight unconditionally (`vpn_required = false`). All other
components (Redis consumer, webhook client, heartbeat) function
identically in both modes.

## Cloud Repository

The Coda cloud service lives at
[conductorquantum/coda](https://github.com/conductorquantum/coda).
The VPN infrastructure and connect endpoint are introduced in
[PR #305](https://github.com/conductorquantum/coda/pull/305).

## Source Layout

```
src/coda_node/
├── __init__.py          # Package exports (CodaError, app, create_app)
├── errors.py            # Exception hierarchy
├── server/
│   ├── __init__.py      # Re-exports app, create_app
│   ├── app.py           # FastAPI app, lifespan, health endpoints
│   ├── auth.py          # JWT signing and verification
│   ├── cli.py           # CLI entry point (coda command)
│   ├── config.py        # Settings, persisted config, env vars
│   ├── consumer.py      # Redis Streams consumer
│   ├── daemon.py        # Background daemon management (start/stop/status)
│   ├── executor.py      # JobExecutor protocol, NoopExecutor, framework resolution
│   ├── ir.py            # NativeGateIR schema and validation
│   └── webhook.py       # Authenticated webhook delivery
└── vpn/
    ├── __init__.py      # Public API re-exports
    ├── guard.py         # VPN preflight and health monitoring
    └── service.py       # Node provisioning, OpenVPN management
```

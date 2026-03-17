# coda-self-service Documentation

Comprehensive documentation for the Coda self-service node runtime.

## Feature Areas

| Area | Description | Directory |
|---|---|---|
| [Self-Service & Reconnect](self-service/INDEX.md) | Self-service provisioning, connect protocol, token lifecycle, credential persistence. | `docs/self-service/` |
| [VPN Management](vpn/INDEX.md) | OpenVPN tunnel lifecycle, health monitoring, cloud VPN infrastructure. | `docs/vpn/` |
| [Hardware Frameworks](frameworks/INDEX.md) | Pluggable hardware control frameworks, device config, auto-detection. | `docs/frameworks/` |
| [Job Execution](jobs/INDEX.md) | Redis Streams consumer, NativeGateIR schema, custom execution backends. | `docs/jobs/` |
| [Webhooks](webhooks/INDEX.md) | Authenticated result delivery, retry logic, payload format. | `docs/webhooks/` |
| [JWT Authentication](auth/INDEX.md) | RS256 JWT signing and verification, keypair lifecycle. | `docs/auth/` |
| [Configuration](configuration/INDEX.md) | Settings reference, environment variables, persisted state. | `docs/configuration/` |
| [Operations](operations/INDEX.md) | Health endpoints, graceful shutdown, CLI, error handling. | `docs/operations/` |

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Coda Cloud                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ /qpu/connect │  │ /qpu/webhook │  │ Redis Streams    │  │
│  │ (self-svc)   │  │  (results)   │  │  qpu:{id}:jobs   │  │
│  └──────┬───────┘  └──────▲───────┘  └────────┬─────────┘  │
│         │                 │                    │            │
│         │    AWS Client VPN (mTLS)             │            │
└─────────┼─────────────────┼────────────────────┼────────────┘
          │                 │                    │
    ┌─────▼─────────────────┼────────────────────▼────────┐
    │                  Node Runtime                        │
    │                                                      │
    │  ┌─────────────┐  ┌──────────────┐  ┌────────────┐  │
    │  │ Settings     │  │ VPNGuard     │  │ OpenVPN    │  │
    │  │ (config.py)  │  │ (guard.py)   │  │ (daemon)   │  │
    │  └──────┬───────┘  └──────┬───────┘  └────────────┘  │
    │         │                 │                           │
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

## Cloud Repository

The Coda cloud service lives at
[conductorquantum/coda](https://github.com/conductorquantum/coda).
The VPN infrastructure and connect endpoint are introduced in
[PR #305](https://github.com/conductorquantum/coda/pull/305).

## Source Layout

```
src/self_service/
├── __init__.py          # Package exports (CodaError, app, create_app)
├── errors.py            # Exception hierarchy
├── frameworks/
│   ├── __init__.py      # Public API (DeviceConfig, Framework, FrameworkRegistry)
│   ├── base.py          # DeviceConfig model, Framework protocol
│   ├── registry.py      # FrameworkRegistry, default_registry(), entry-point discovery
│   ├── qua/
│   │   └── __init__.py  # QUAFramework — Quantum Machines OPX (stub)
│   └── qubic/
│       └── __init__.py  # QubiCFramework — LBNL QubiC (stub)
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
    └── service.py       # Self-service provisioning, OpenVPN management
```

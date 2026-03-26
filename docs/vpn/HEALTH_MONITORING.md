# VPN Health Monitoring

The `VPNGuard` class provides both a one-shot preflight check and
continuous background monitoring of VPN connectivity.

## Service States

```python
class ServiceState(Enum):
    BOOTING = "booting"
    VPN_UNAVAILABLE = "vpn_unavailable"
    READY = "ready"
    DEGRADED = "degraded"
```

| State | Meaning |
|---|---|
| `BOOTING` | Initial state before preflight completes. |
| `READY` | VPN interface detected, DNS resolves, HTTP probes succeed. |
| `VPN_UNAVAILABLE` | No tunnel interface, DNS failure, or probes failing. |
| `DEGRADED` | Was READY but health check now failing (transient issue). |

## Preflight Check

`VPNGuard.preflight()` runs three stages in order:

### 1. Interface Detection

Calls `detect_tun_interface()` to find an active TUN/TAP interface.
If no interface is found and `vpn_required` is `True`, returns
`VPN_UNAVAILABLE` immediately.

### 2. DNS Resolution

For each probe target URL, extracts the hostname and attempts DNS
resolution via `socket.getaddrinfo()`. If any hostname fails to
resolve and VPN is required, returns `VPN_UNAVAILABLE`.

### 3. HTTP Probes

Sends `HEAD` requests to each probe target with a 5-second timeout.
The default probe target is the cloud's unauthenticated health
endpoint:

```
GET /api/internal/qpu/health → { "ok": true }
```

This endpoint is intentionally unauthenticated and side-effect free
so it can be used purely for connectivity verification.

If any probe fails and VPN is required, returns `VPN_UNAVAILABLE`.

### VPN Not Required

When `vpn_required` is `False`, all three stages pass regardless of
actual results. This applies in two situations:

- **HTTPS connection mode**: The cloud sets `vpn.required = false` in
  the connect response when the token was created with
  `connection_mode: "https"`. The node operates without any VPN
  infrastructure.
- **Local development**: Operators can set `CODA_VPN_REQUIRED=false`
  manually to skip VPN checks during development.

## VPNStatus Result

Preflight returns a `VPNStatus` dataclass:

```python
@dataclass(frozen=True)
class VPNStatus:
    ok: bool
    interface_found: bool
    probes: list[ProbeResult]
    reason: str = ""
```

Each probe result includes:

```python
@dataclass(frozen=True)
class ProbeResult:
    target: str
    ok: bool
    latency_ms: float | None = None
    error: str | None = None
```

## Background Watch Loop

`VPNGuard.watch()` runs continuously after startup:

1. Sleeps for `check_interval_sec` seconds (default: 10).
2. Runs `preflight()`.
3. If the state transitions (e.g. READY → DEGRADED or vice versa),
   invokes the `on_change` callback.
4. Repeats until `stop()` is called.

The watch loop is started as an `asyncio.Task` in the FastAPI lifespan:

```python
watch_task = asyncio.create_task(guard.watch(_on_vpn_state_change))
```

State transitions are logged at WARNING level.

## Integration with /ready Endpoint

The `/ready` endpoint queries `guard.is_ready` (which checks
`state == ServiceState.READY`). When the VPN guard reports unhealthy,
the endpoint returns HTTP 503 with the current VPN state.

## Configuration

| Variable | Default | Effect on VPNGuard |
|---|---|---|
| `CODA_VPN_REQUIRED` | `true` | When `False`, preflight always passes. |
| `CODA_VPN_CHECK_INTERVAL_SEC` | `10` | Seconds between background checks. |
| `CODA_VPN_INTERFACE_HINT` | `null` | Specific interface name to look for. |
| `CODA_ALLOW_DEGRADED_STARTUP` | `false` | When `True`, the app starts even if preflight fails. |

## VPNGuard Constructor

```python
VPNGuard(
    probe_targets=settings.vpn_probe_urls,
    interface_hint=settings.vpn_interface_hint,
    check_interval_sec=settings.vpn_check_interval_sec,
    vpn_required=settings.vpn_required,
)
```

`vpn_probe_urls` is a computed property on `Settings` that falls back
to `[connect_url, heartbeat_url]` when no explicit probe targets are
configured. During node provisioning, the cloud sets `probe_targets` to
`["{cloud_base_url}/api/internal/qpu/health"]`.

## VPN Health vs QPU Heartbeat

These are two separate mechanisms:

| Concern | Component | Method | Endpoint | Authenticated | Side Effect |
|---|---|---|---|---|---|
| VPN connectivity | `VPNGuard` | `HEAD` | `/api/internal/qpu/health` | No | None |
| QPU liveness | `HeartbeatClient` | `POST` | `/api/internal/qpu/heartbeat` | Yes (JWT) | Updates QPU status to "online" |

The VPN guard verifies the network path is working. The heartbeat
client keeps the QPU device record marked as "online" in the Coda
database. If heartbeats stop (e.g. node crash), a server-side cron
job marks the QPU offline after ~90 seconds.

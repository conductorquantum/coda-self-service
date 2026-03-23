# Health Endpoints

The FastAPI app exposes two health endpoints suitable for Kubernetes
probes, load balancers, or manual monitoring.

## GET /health (Liveness)

Returns `200` with `{"status": "ok"}` if the process is running. No
component checks are performed — this is purely a liveness signal.

```json
{"status": "ok"}
```

Use as a Kubernetes `livenessProbe`:

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8080
  initialDelaySeconds: 5
  periodSeconds: 10
```

## GET /ready (Readiness)

Returns a composite health check covering VPN and Redis:

### Healthy (200)

```json
{
  "ready": true,
  "vpn_state": "ready",
  "redis_healthy": true,
  "current_job": null
}
```

### Unhealthy (503)

```json
{
  "ready": false,
  "vpn_state": "degraded",
  "redis_healthy": true,
  "current_job": "job-uuid"
}
```

### Timeout (503)

If the health check takes longer than 5 seconds:

```json
{
  "ready": false,
  "reason": "health check timeout"
}
```

### Readiness Criteria

The endpoint returns `200` only when **both**:

- `VPNGuard.is_ready` is `True` (state is `READY`).
- `RedisConsumer.redis_healthy` is `True`.

Otherwise it returns `503`.

### Response Fields

| Field | Type | Description |
|---|---|---|
| `ready` | `bool` | Overall readiness. |
| `vpn_state` | `string` | Current `ServiceState` value. |
| `redis_healthy` | `bool` | Whether the last Redis operation succeeded. |
| `current_job` | `string \| null` | ID of the in-flight job, if any. |

Use as a Kubernetes `readinessProbe`:

```yaml
readinessProbe:
  httpGet:
    path: /ready
    port: 8080
  initialDelaySeconds: 15
  periodSeconds: 10
  failureThreshold: 3
```

## Implementation

The readiness check is wrapped in `asyncio.wait_for()` with a
5-second timeout to prevent hung health checks from blocking the
HTTP server:

```python
result = await asyncio.wait_for(_check_readiness(), timeout=5.0)
```

# Graceful Shutdown

The FastAPI lifespan manages an orderly shutdown sequence that drains
in-flight work before tearing down resources.

## Shutdown Sequence

When the process receives `SIGTERM` or `SIGINT`, uvicorn triggers the
lifespan exit. The shutdown proceeds in this order:

```
1. Stop VPN watch loop
2. Cancel VPN watch task
3. Drain in-flight job (up to CODA_SHUTDOWN_DRAIN_TIMEOUT_SEC)
4. Cancel consumer task
5. Close webhook HTTP client
6. Close Redis connection
7. Kill OpenVPN daemon
```

## Drain Behavior

`consumer.drain(timeout)`:

1. Calls `stop()` to signal the consume loop to exit after the current
   iteration.
2. Waits up to `timeout` seconds for the `_idle_event` to be set
   (meaning no job is in progress).
3. Returns `True` if the consumer became idle within the timeout.
4. Returns `False` if the timeout expired with a job still running —
   the job is then forcibly cancelled.

### Configuration

| Variable | Default | Description |
|---|---|---|
| `CODA_SHUTDOWN_DRAIN_TIMEOUT_SEC` | `30` | Max seconds to wait for in-flight job. |

### What Happens to an In-Flight Job

- **Drain succeeds**: The job completes normally. Its result webhook
  is sent. The message is ACK'd.
- **Drain times out**: The consumer task is cancelled via
  `asyncio.CancelledError`. The message is **not** ACK'd and will be
  eligible for crash recovery on the next startup.

## Lifespan Code

```python
# Stop VPN monitoring
guard.stop()
watch_task.cancel()
with suppress(asyncio.CancelledError):
    await watch_task

# Drain in-flight work
drained = await consumer.drain(timeout=settings.shutdown_drain_timeout_sec)
if not drained:
    logger.warning("Drain timeout expired, cancelling in-flight job")
consumer_task.cancel()
with suppress(asyncio.CancelledError):
    await consumer_task

# Close connections
await webhook.close()
await redis_client.aclose()
kill_openvpn_daemon()
```

## Resource Cleanup

| Resource | Cleanup Method |
|---|---|
| VPN watch task | `guard.stop()` + task cancellation |
| Consumer loop | `consumer.drain()` + task cancellation |
| Webhook HTTP client | `webhook.close()` → `httpx.AsyncClient.aclose()` |
| Redis connection | `redis_client.aclose()` |
| OpenVPN daemon | `kill_openvpn_daemon()` → `SIGTERM` / `taskkill` |

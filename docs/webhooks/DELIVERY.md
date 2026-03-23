# Webhook Delivery

`WebhookClient` manages a long-lived `httpx.AsyncClient` for
connection pooling and handles JWT signing, serialization, and retry.

## Constructor

```python
WebhookClient(
    qpu_id="my-qpu",
    jwt_private_key="-----BEGIN PRIVATE KEY-----\n...",
    jwt_key_id="qpu-my-qpu-1710000000000",
    timeout=30.0,       # HTTP request timeout (default)
    max_retries=3,       # delivery attempts (default)
)
```

## Request Format

Each webhook POST carries:

```http
POST {callback_url}
Content-Type: application/json
Authorization: Bearer <jwt>

{
  "job_id": "uuid",
  "status": "completed",
  "counts": {"00": 512, "11": 488},
  "execution_time_ms": 42.5,
  "shots_completed": 1000
}
```

The JWT is freshly signed for each attempt using `sign_token()` with
the QPU's private key and key ID.

## Retry Logic

`_post_with_retry()` retries on transient failures:

| Error Type | Behavior |
|---|---|
| 5xx response | Retried with backoff. |
| `httpx.TransportError` | Retried with backoff. |
| 4xx response | Raised immediately (no retry). |

### Backoff Formula

```
delay = 1.0 × 2^(attempt - 1)
```

| Attempt | Delay |
|---|---|
| 1 | 1.0s |
| 2 | 2.0s |
| 3 | 4.0s |

After all `max_retries` attempts are exhausted, the last exception is
re-raised.

## Methods

### `send_result(callback_url, payload)`

Delivers a successful job result. Raises `httpx.HTTPStatusError` on
4xx or `httpx.TransportError` after retries.

### `send_error(callback_url, job_id, error)`

Convenience wrapper that constructs a failure payload and calls
`send_result()`.

### `close()`

Shuts down the underlying HTTP connection pool. Called during the
FastAPI lifespan shutdown.

## Connection Lifecycle

The `WebhookClient` is created during the FastAPI lifespan and stored
on `app.state.webhook`. It is closed during shutdown after the
consumer loop exits:

```python
await webhook.close()
```

## Error Handling in Consumer

The consumer wraps webhook calls in try/except:

- **Result webhook failure**: Logged but does not prevent job
  completion status from being recorded.
- **Error webhook failure**: Logged at exception level. The job is
  still marked as failed in Redis regardless.

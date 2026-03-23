# Webhook Payload Format

`WebhookPayload` is an immutable dataclass that represents either a
job result or a job failure.

## Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `job_id` | `string` | Yes | Unique job identifier from the stream message. |
| `status` | `string` | Yes | `"completed"` or `"failed"`. |
| `counts` | `dict[str, int]` | On success | Bitstring → observation count mapping. |
| `execution_time_ms` | `float` | On success | Wall-clock execution time in milliseconds. |
| `shots_completed` | `int` | On success | Actual number of shots executed. |
| `error` | `string` | On failure | Error message (truncated to 500 chars). |

## Serialization

`to_dict()` omits `None`-valued optional fields to keep the JSON
payload minimal:

### Success Payload

```json
{
  "job_id": "uuid",
  "status": "completed",
  "counts": {"000": 512, "111": 488},
  "execution_time_ms": 42.5,
  "shots_completed": 1000
}
```

### Failure Payload

```json
{
  "job_id": "uuid",
  "status": "failed",
  "error": "Qubit calibration timeout after 30s"
}
```

## Construction

### From Consumer (success)

```python
payload = WebhookPayload(
    job_id=job_id,
    status="completed",
    counts=result.counts,
    execution_time_ms=result.execution_time_ms,
    shots_completed=result.shots_completed,
)
```

### From Consumer (failure)

```python
payload = WebhookPayload(
    job_id=job_id,
    status="failed",
    error=str(exc)[:500],
)
```

The error message is truncated to 500 characters to prevent
excessively large payloads from stack traces.

## Type Alias

```python
WebhookPayloadValue = dict[str, int] | float | int | str
```

Used as the value type for the serialized dictionary.

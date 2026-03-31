# Redis Consumer

`RedisConsumer` reads jobs from a Redis Stream using consumer groups
and dispatches them to the configured executor.

The cloud can cancel a queued or already-running job by writing
`qpu:job:cancelled:{job_id}`. The consumer checks that key before
dispatch, continues polling it while the executor is running, and marks
the Redis job state as `cancelled` instead of emitting a terminal
webhook.

When `batch_size > 1` and the executor implements `batch_run()`, the
consumer reads up to that many new jobs per poll and executes them as a
single hardware batch. If the executor does not expose `batch_run()`,
the consumer logs a warning and stays in single-job mode.

## Consumer Group Setup

On startup, `setup()` creates the consumer group if it doesn't exist:

```python
await self._redis.xgroup_create(
    name="qpu:{qpu_id}:jobs",
    groupname="qpu:{qpu_id}:workers",
    id="0",
    mkstream=True,
)
```

`mkstream=True` creates the stream automatically so the consumer can
start before any jobs are enqueued. If the group already exists
(`BUSYGROUP` error), the error is silently suppressed.

## Crash Recovery

Before entering the main loop, `recover_pending()` reprocesses
messages that were claimed but never acknowledged (e.g. after an
unclean shutdown):

1. Queries `XPENDING` for messages assigned to **this consumer only**.
2. Re-fetches and reprocesses every pending message — no idle-time
   filter is applied because the query is already scoped to this
   consumer's own unacknowledged work.

In addition, the main consume loop periodically re-runs
`recover_pending()` every `_PENDING_RECHECK_SECS` (60 s) when no new
messages arrive.  This catches messages that become stuck mid-flight
without requiring a full restart.

## Main Consume Loop

`consume_loop()` blocks on `XREADGROUP` with a 5-second timeout:

```python
messages = await self._redis.xreadgroup(
    groupname=self._group,
    consumername=self._consumer_name,
    streams={self._stream: ">"},
    count=self._batch_size if self._can_batch else 1,
    block=5000,
)
```

When batching is enabled, the loop also waits for the previous batch's
background webhook/XACK delivery task before dispatching the next
hardware batch. This preserves in-order result delivery without holding
up the webhook fan-out itself.

### Redis Resilience

Connection errors trigger exponential backoff:

| Constant | Value | Purpose |
|---|---|---|
| `_BACKOFF_BASE` | `1.0` | Initial backoff in seconds. |
| `_BACKOFF_FACTOR` | `2.0` | Multiplier per consecutive failure. |
| `_BACKOFF_MAX` | `60.0` | Maximum backoff cap. |

The formula is `min(1.0 × 2^(failures-1), 60.0)`. On successful
reads, the failure counter resets to zero.

`redis_healthy` is set to `True` on success and `False` on connection
error. This flag drives the `/ready` endpoint's Redis health check.

### Safe Redis Operations

Mid-job Redis operations use `_safe_hset()` and `_safe_xack()` which
catch connection errors and log warnings instead of failing the job.
This ensures that a transient Redis outage during execution does not
prevent webhook delivery.

## Message Processing

`_process_message()` handles a single message:

1. **Normalise fields** — `_decode_fields()` converts any byte
   keys/values to strings (defensive against a Redis client that does
   not set `decode_responses=True`).  If required fields (`job_id`,
   `callback_url`) are missing, the message is ACK'd and skipped with
   an error log.
2. **Skip completed/cancelled jobs** — if `qpu:job:{job_id}:status`
   already shows `completed` or `cancelled`, the message is ACK'd and
   skipped. If the cloud-side cancel signal key
   `qpu:job:cancelled:{job_id}` exists, the consumer first marks the
   Redis status hash as `cancelled`, then ACKs and skips the message.
3. **Mark executing** — updates status hash with `state: executing`,
   `started_at`, `message_id`, `qpu_id`.
4. **Parse and execute** — deserializes `ir_json` into `NativeGateIR`,
   then runs the executor inside a cancellable task. While the task is
   in flight, the consumer polls `qpu:job:cancelled:{job_id}` every
   `_CANCEL_POLL_INTERVAL_SECS` seconds. When the key appears, the
   consumer:
   - calls the executor's optional `cancel_current_job()` hook if it
     exists,
   - cancels the in-process `runner.run(...)` task,
   - marks the Redis status hash as `cancelled`,
   - skips both success and error webhooks.
5. **On success** — if no cancel signal arrived, marks status as
   `completed`, builds a
   `WebhookPayload` with counts, sends via webhook.
6. **On failure** — if no cancel signal arrived, marks status as
   `failed` with error message
   (truncated to 500 chars), sends error webhook.
7. **Finally** — ACKs the message and clears `current_job_id`.

## Batch Processing

`_process_batch()` is used only when both conditions are true:

- `batch_size > 1`
- The executor exposes `batch_run(jobs)`

The batch path:

1. Decodes each message and skips malformed, completed, or already-cancelled jobs.
2. Marks the remaining jobs as `executing`.
3. Calls `executor.batch_run([(ir, shots), ...])`.
4. On batch-level failure, falls back to `_process_message()` for each message.
5. On success, fans out completion status updates, webhooks, and ACKs in a background task.

Each `batch_run()` result must correspond to the input jobs in order and
return one `ExecutionResult` per job.

## Graceful Drain

`drain(timeout)` allows in-flight work to complete before shutdown:

1. Calls `stop()` to signal the loop to exit.
2. Waits up to `timeout` seconds for the `_idle_event` to be set
   (indicating no job is in progress).
3. Waits for any pending batch webhook/XACK delivery task to finish.
4. Returns `True` if drained cleanly, `False` if the timeout expired.

The idle event is cleared when a job starts processing and set when
processing finishes (in the `finally` block).

## Constructor Parameters

```python
RedisConsumer(
    redis=redis_client,
    runner=executor,
    webhook=webhook_client,
    qpu_id="my-qpu",
    consumer_name="worker-0",           # default
    crash_recovery_threshold_ms=60_000,  # default
    batch_size=1,                        # default
)
```

## Observable State

| Attribute | Type | Description |
|---|---|---|
| `current_job_id` | `str \| None` | ID of the in-flight job, or `None`. |
| `last_job_at` | `str \| None` | ISO timestamp of last successful job. |
| `redis_healthy` | `bool` | Whether the last Redis operation succeeded. |

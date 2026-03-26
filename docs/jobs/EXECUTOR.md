# Execution Backends

The `JobExecutor` protocol defines the interface that all execution
backends must implement. The consumer is backend-agnostic -- it only
calls `executor.run(ir, shots)`.

## JobExecutor Protocol

```python
class JobExecutor(Protocol):
    async def run(self, ir: NativeGateIR, shots: int) -> ExecutionResult:
        ...
```

### ExecutionResult

```python
@dataclass(frozen=True, slots=True)
class ExecutionResult:
    counts: dict[str, int]      # bitstring -> count
    execution_time_ms: float    # wall-clock time
    shots_completed: int        # actual shots executed
```

The `counts` dictionary maps bitstrings (e.g. `"010"`) to the number
of times that outcome was observed. `shots_completed` may differ from
the requested `shots` if the backend applies shot budgeting.

## NoopExecutor

The built-in `NoopExecutor` returns a deterministic all-zeros result:

```python
class NoopExecutor:
    async def run(self, ir: NativeGateIR, shots: int) -> ExecutionResult:
        bitstring = "0" * len(ir.measurements)
        return ExecutionResult(
            counts={bitstring: shots},
            execution_time_ms=0.0,
            shots_completed=shots,
        )
```

Used when no executor factory is configured or discovered, allowing the
service to boot for integration testing without hardware.

## Resolution Order

`load_executor()` checks three sources in priority order:

1. **`CODA_EXECUTOR_FACTORY`** -- explicit `module:attribute` import
   path (see [Custom Executor](#custom-executor) below).
2. **`executor_factory` in `CODA_DEVICE_CONFIG`** -- optional top-level
   YAML fallback when the env var is unset.
3. **Convention-based auto-discovery** -- scan installed packages for
   `<pkg>.executor_factory:create_executor`.  If exactly one match is
   found, use it.  If multiple match, warn and fall back to noop.
4. **`NoopExecutor`** fallback -- deterministic all-zeros results.

## Auto-Discovery

When neither `CODA_EXECUTOR_FACTORY` nor the device config's
`executor_factory` key is set, the runtime scans all installed top-level
Python packages for the naming convention:

```
<package>.executor_factory:create_executor
```

For example, if `coda-acme` is installed, the runtime finds
`coda_acme.executor_factory:create_executor` and uses it
automatically.

If multiple packages match the convention, the runtime logs a warning
listing all candidates and falls back to `NoopExecutor`.  Set
`CODA_EXECUTOR_FACTORY` explicitly to resolve the ambiguity.

## Custom Executor

### Configuration

Set `CODA_EXECUTOR_FACTORY` to a `module:attribute` import path:

```bash
export CODA_EXECUTOR_FACTORY="my_project.executor_factory:create_executor"
```

### Factory Resolution

When `CODA_EXECUTOR_FACTORY` is set (or a factory is auto-discovered),
`load_executor()` resolves the target:

1. Import the dotted module path and retrieve the named attribute.
2. If the target has a `.run` method, use it directly as an executor.
3. If the target is callable, call it as a factory:
   - If the factory accepts parameters, pass `settings`.
   - If the factory accepts no parameters, call with no args.
4. Validate the result has a `.run` method.

### Example: Simple Executor

```python
from coda_node.server.executor import ExecutionResult
from coda_node.server.ir import NativeGateIR


class MyExecutor:
    async def run(self, ir: NativeGateIR, shots: int) -> ExecutionResult:
        counts = await run_on_hardware(ir, shots)
        return ExecutionResult(
            counts=counts,
            execution_time_ms=42.0,
            shots_completed=shots,
        )
```

```bash
export CODA_EXECUTOR_FACTORY="my_project:MyExecutor"
```

### Example: Factory with Settings

```python
from coda_node.server.config import Settings
from coda_node.server.executor import ExecutionResult
from coda_node.server.ir import NativeGateIR


class HardwareExecutor:
    def __init__(self, device_config_path: str) -> None:
        self.device_config_path = device_config_path

    async def run(self, ir: NativeGateIR, shots: int) -> ExecutionResult:
        ...


def create_executor(settings: Settings) -> HardwareExecutor:
    return HardwareExecutor(device_config_path=settings.device_config)
```

```bash
export CODA_EXECUTOR_FACTORY="my_project.executor_factory:create_executor"
```

## Error Handling

- `ExecutorError` is raised for invalid import paths, non-callable
  targets, and factories that don't return a valid runner.
- Exceptions thrown during `executor.run()` are caught by the consumer,
  logged, and reported as failed jobs via webhook.

## Cross-References

- [Executor Factory Convention](../frameworks/INDEX.md) -- naming
  convention and auto-discovery details.
- [Settings Reference](../configuration/SETTINGS_REFERENCE.md) --
  `executor_factory` and `device_config` fields.
- [Environment Variables](../configuration/ENVIRONMENT_VARIABLES.md) --
  `CODA_EXECUTOR_FACTORY` and `CODA_DEVICE_CONFIG`.

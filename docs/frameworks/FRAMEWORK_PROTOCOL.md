# Executor Factory Convention

Backend packages integrate with `coda-node` by exposing a
factory function at a conventional module path.  This replaces the
older `Framework` protocol and entry-point discovery system.

## Convention

Place a `create_executor` callable in `<package>/executor_factory.py`:

```
<package>.executor_factory:create_executor
```

The callable must accept either:

- A single `Settings` argument (most common -- gives access to
  `settings.device_config` and other runtime config).
- No arguments (for simple executors that don't need settings).

It must return an object with an async `run(ir, shots)` method that
satisfies the `JobExecutor` protocol.

## Complete Example

### 1. Define a config model

```python
# my_backend/config.py
from pathlib import Path
from pydantic import BaseModel
import yaml


class MyConfig(BaseModel):
    target: str
    num_qubits: int
    host: str
    port: int = 8080

    @classmethod
    def from_yaml(cls, path: str | Path) -> "MyConfig":
        raw = yaml.safe_load(Path(path).read_text())
        return cls.model_validate(raw)
```

### 2. Implement the executor

```python
# my_backend/runner.py
from coda_node.server.executor import ExecutionResult
from coda_node.server.ir import NativeGateIR


class MyRunner:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port

    async def run(self, ir: NativeGateIR, shots: int) -> ExecutionResult:
        counts = await self._execute(ir, shots)
        return ExecutionResult(
            counts=counts,
            execution_time_ms=50.0,
            shots_completed=shots,
        )
```

### 3. Write the factory

```python
# my_backend/executor_factory.py
from coda_node.errors import ExecutorError
from my_backend.config import MyConfig
from my_backend.runner import MyRunner


def create_executor(settings):
    """Build executor from settings.device_config."""
    if not settings.device_config:
        raise ExecutorError(
            "CODA_DEVICE_CONFIG must be set for my_backend"
        )
    config = MyConfig.from_yaml(settings.device_config)
    return MyRunner(host=config.host, port=config.port)
```

### 4. Create a device YAML

```yaml
# site/device.yaml
target: my_target
num_qubits: 5
host: 10.0.0.42
port: 9090
```

### 5. Run

If `my_backend` is the only backend package installed:

```bash
uv run coda-node start --token <token>
```

The runtime auto-discovers `my_backend.executor_factory:create_executor`
and uses it.  The default `CODA_DEVICE_CONFIG` path `./site/device.yaml`
is picked up automatically.

To be explicit:

```bash
CODA_EXECUTOR_FACTORY=my_backend.executor_factory:create_executor \
CODA_DEVICE_CONFIG=./site/device.yaml \
uv run coda-node start --token <token>
```

## Key Points

- `coda-node` never imports or depends on your backend package
  directly.
- The `NativeGateIR` schema in `coda_node.server.ir` is the shared
  contract between the cloud and all backends.
- Device config schemas are owned by each backend, not by
  `coda-node`.
- Auto-discovery uses `importlib.metadata.packages_distributions()` and
  `importlib.util.find_spec()` -- it does not require entry points or
  any registration step beyond following the naming convention.

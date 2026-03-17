# Framework Protocol

The `Framework` protocol defines the interface that hardware control
frameworks must implement.  It is a `runtime_checkable` Python
`Protocol`, so framework authors do not need to inherit from a base
class — structural subtyping is sufficient.

## Protocol Definition

```python
class Framework(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def supported_targets(self) -> frozenset[str]: ...

    def validate_config(self, device_config: DeviceConfig) -> list[str]: ...

    def create_executor(
        self, device_config: DeviceConfig, settings: Settings
    ) -> JobExecutor: ...
```

### `name`

A short, unique identifier for the framework (e.g. `"qua"`,
`"qiskit_pulse"`).  Used in the device config's `framework` field and
in registry lookups.

### `supported_targets`

The set of `NativeGateIR` target strings that this framework can
execute (e.g. `{"superconducting_cz", "superconducting_iswap"}`).
Used by the registry for auto-detection when the device config omits
the `framework` field.

### `validate_config(device_config) → list[str]`

Returns a list of human-readable validation errors (empty list means
valid).  Frameworks should check:

- The `target` is in `supported_targets`.
- Required framework-specific options are present (e.g. `opx_host`).
- The calibration file exists and can be parsed.
- Required third-party packages are installed.

All errors are accumulated — do not raise on the first failure.

### `create_executor(device_config, settings) → JobExecutor`

Constructs and returns a `JobExecutor` wired to the physical hardware.
This is called once at startup by `load_executor()`.  The method
receives the validated `DeviceConfig` and the runtime `Settings`
(which contains cloud-provisioned fields like `qpu_id`, `redis_url`,
etc.).

Raise `ExecutorError` if the executor cannot be created.

## Implementing a Framework

### Step 1: Create the Framework Class

```python
# my_package/framework.py
from self_service.frameworks.base import DeviceConfig
from self_service.server.config import Settings
from self_service.server.executor import ExecutionResult, JobExecutor

_TARGETS = frozenset({"trapped_ion"})


class MyExecutor:
    def __init__(self, host: str, cal_path: str) -> None:
        self.host = host
        self.cal_path = cal_path

    async def run(self, ir, shots: int) -> ExecutionResult:
        counts = await talk_to_hardware(self.host, ir, shots)
        return ExecutionResult(
            counts=counts,
            execution_time_ms=100.0,
            shots_completed=shots,
        )


class MyFramework:
    @property
    def name(self) -> str:
        return "my_framework"

    @property
    def supported_targets(self) -> frozenset[str]:
        return _TARGETS

    def validate_config(self, device_config: DeviceConfig) -> list[str]:
        errors: list[str] = []
        if device_config.target not in _TARGETS:
            errors.append(f"Unsupported target: {device_config.target!r}")
        if not device_config.get_option("host"):
            errors.append("'host' is required in device config")
        cal = device_config.resolved_calibration_path
        if cal is None:
            errors.append("calibration_path is required")
        elif not cal.exists():
            errors.append(f"Calibration file not found: {cal}")
        return errors

    def create_executor(
        self, device_config: DeviceConfig, settings: Settings
    ) -> JobExecutor:
        return MyExecutor(
            host=device_config.get_option("host"),
            cal_path=str(device_config.resolved_calibration_path),
        )
```

### Step 2: Register via Entry Point

Add a `coda.frameworks` entry point in your package's `pyproject.toml`:

```toml
[project.entry-points."coda.frameworks"]
my_framework = "my_package.framework:MyFramework"
```

The registry will discover your framework automatically when
`pip install my_package` is run alongside `coda-self-service`.

### Step 3: Create a Device Config

```yaml
# device.yaml
framework: my_framework       # or omit to auto-detect from target
target: trapped_ion
num_qubits: 5
calibration_path: ./calibration.yaml
host: 10.0.0.42
```

### Step 4: Run

```bash
export CODA_SELF_SERVICE_TOKEN="..."
export CODA_DEVICE_CONFIG="./device.yaml"
coda start
```

## Built-in Frameworks

### QUA (Quantum Machines OPX)

| Property | Value |
|---|---|
| Name | `qua` |
| Targets | `superconducting_cz`, `superconducting_iswap` |
| Required options | `opx_host`, `calibration_path` |
| Optional options | `opx_port`, `cluster_name`, `topology` |
| Package | Built-in (no extra install needed) |

The QUA framework is currently a stub — `create_executor()` raises
`NotImplementedError`.  The full pipeline (pulse mapper, OPX config
builder, shot collector) will be integrated in a subsequent commit.

### QubiC (LBNL)

| Property | Value |
|---|---|
| Name | `qubic` |
| Targets | `superconducting_cz`, `superconducting_cnot` |
| Required options | `classifier_path`, `calibration_path` (qubitcfg.json) |
| RPC mode options | `rpc_host`, `rpc_port` |
| Local mode options | `runner_mode: local`, `xsa_commit` (or `use_sim: true`) |
| Package | Built-in (no extra install needed) |

The QubiC framework is currently a stub.  The full pipeline (device
derivation from qubitcfg.json, ZXZXZ decomposition, QubiC RPC runner)
will be integrated from `stanza-private`.

Example device config for QubiC:

```yaml
framework: qubic
target: superconducting_cnot
num_qubits: 3
calibration_path: ./qubitcfg.json
classifier_path: ./classifiers/
rpc_host: 10.0.0.42
rpc_port: 9095
```

### Target Overlap

Both QUA and QubiC support the `superconducting_cz` target.  When
both frameworks are registered and the device config specifies
`target: superconducting_cz` without an explicit `framework` field,
the registry raises a `ConfigError` asking the user to disambiguate.

Targets with unique ownership auto-detect without ambiguity:

| Target | Framework |
|---|---|
| `superconducting_iswap` | QUA (auto-detected) |
| `superconducting_cnot` | QubiC (auto-detected) |
| `superconducting_cz` | Ambiguous — set `framework: qua` or `framework: qubic` |

## Entry-Point Discovery

Third-party frameworks are discovered via Python's standard
`importlib.metadata.entry_points` mechanism using the
`coda.frameworks` group.  Discovery is lazy — entry points are only
scanned on the first registry lookup or detect call.

The entry point value should be either:

- A **class** → instantiated with no arguments.
- A **pre-built instance** → used directly.

## Verifying Protocol Compliance

Use `isinstance` to verify a class satisfies the `Framework` protocol
at runtime (it is `runtime_checkable`):

```python
from self_service.frameworks.base import Framework

assert isinstance(MyFramework(), Framework)
```

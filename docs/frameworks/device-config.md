# Device Configuration

The `DeviceConfig` model is the user's single entry point for hardware
setup.  It is a YAML file that declares which framework and hardware
target to use, points to a calibration file, and carries
framework-specific connection parameters.

## YAML Schema

```yaml
# Required
target: superconducting_cz      # NativeGateIR target string
num_qubits: 3                    # qubit count (1–50)

# Optional
framework: qua                   # explicit framework name (auto-detected if omitted)
calibration_path: ./calibration.yaml  # path to calibration data

# Framework-specific (passed through as extra fields)
opx_host: 192.168.1.100
opx_port: 80
cluster_name: my-cluster
topology: single
```

### Standard Fields

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `target` | `str` | Yes | — | Hardware target (must be non-empty). Matches `NativeGateIR.target`. |
| `num_qubits` | `int` | Yes | — | Number of qubits (1–50). |
| `framework` | `str` | No | `""` | Framework name. When empty, auto-detected from `target`. |
| `calibration_path` | `str` | No | `""` | Path to calibration data file. Relative paths are resolved against the YAML file's directory. |

### Framework-Specific Fields

Any additional keys in the YAML are preserved as framework-specific
options.  Access them via:

```python
config.get_option("opx_host")          # single key with optional default
config.get_option("opx_port", 80)
config.get_options()                    # dict of all extra fields
```

Each framework defines which extra fields it requires in its
`validate_config()` method.

## Loading

Point `CODA_DEVICE_CONFIG` at the file:

```bash
export CODA_DEVICE_CONFIG="./device.yaml"
```

Or load programmatically:

```python
from self_service.frameworks.base import DeviceConfig

config = DeviceConfig.from_yaml("./device.yaml")
```

## Path Resolution

`calibration_path` supports three modes:

| Input | Resolution |
|---|---|
| Empty string | `resolved_calibration_path` returns `None`. |
| Absolute path (`/etc/cal.yaml`) | Used as-is. |
| Relative path (`cal.yaml`) | Resolved relative to the YAML file's parent directory (set by `from_yaml`), or `cwd` for programmatic construction. |

## Validation

`DeviceConfig` validates standard fields via Pydantic:

- `target` must be non-empty (enforced by `min_length=1`).
- `num_qubits` must be in `[1, 50]`.
- Extra fields are preserved (not rejected).

Framework-specific validation (e.g. "opx_host is required") is
performed by the framework's `validate_config()` method, not by
`DeviceConfig` itself.

## Error Handling

| Exception | When |
|---|---|
| `FileNotFoundError` | YAML file does not exist. |
| `ValueError` | File content is not a YAML mapping. |
| `pydantic.ValidationError` | Standard fields fail schema validation. |
| `ImportError` | PyYAML is not installed. |

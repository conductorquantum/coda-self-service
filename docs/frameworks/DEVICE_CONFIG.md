# Device Configuration

`CODA_DEVICE_CONFIG` points to a YAML file that describes the hardware
setup.  The file's schema and validation are owned entirely by the backend
package, not by `coda-node`.

## How It Works

`coda-node` stores `CODA_DEVICE_CONFIG` on `Settings.device_config`.
It still leaves schema validation to the backend package, but it now
recognizes one optional top-level key itself:

- `executor_factory` -- fallback `module:attribute` import path used when
  `CODA_EXECUTOR_FACTORY` is unset.

All other keys remain backend-owned. The executor factory reads
`settings.device_config`, loads the YAML, and builds the executor from it.

### Default Path

If `CODA_DEVICE_CONFIG` is not set and `./site/device.yaml` exists in
the working directory, the runtime uses it automatically and logs an
info message.  Explicit `CODA_DEVICE_CONFIG` always takes precedence.

## Example

### Sample device config (`site/device.yaml`)

```yaml
executor_factory: coda_qubic.executor_factory:create_executor
target: cz
num_qubits: 5
host: 192.168.1.120
port: 9095
```

The schema is defined by the backend package, not by `coda-node`.
Each backend defines its own YAML schema and Pydantic model.

### Running

```bash
CODA_DEVICE_CONFIG=./site/device.yaml \
uv run coda-node start --token <your-token>
```

Or, if `./site/device.yaml` exists, simply:

```bash
uv run coda-node start --token <your-token>
```

To keep the executor choice with the device config instead of the shell
environment:

```yaml
executor_factory: my_project.executor_factory:create_executor
```

## Path Resolution

Paths inside the YAML file (e.g. `calibration_path`) are resolved by
the backend package, not by `coda-node`.  Typically they are
relative to the YAML file's parent directory.

## Writing a Device Config for a New Backend

Each backend package defines its own Pydantic model for the device
config.  The factory function reads `settings.device_config`, loads
the file, validates it against the model, and builds the executor.

See [FRAMEWORK_PROTOCOL.md](FRAMEWORK_PROTOCOL.md) for a complete
example.

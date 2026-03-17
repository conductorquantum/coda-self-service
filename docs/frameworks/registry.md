# Framework Registry

The `FrameworkRegistry` maps framework names to `Framework` instances
and provides auto-detection from a `DeviceConfig`.

## Registration

### Built-in Frameworks

Built-in frameworks (e.g. QUA) are registered eagerly by
`default_registry()`.  The import is guarded with `try/except` so
that missing optional dependencies (like `qm-qua`) do not prevent
the service from booting.

### Third-Party Frameworks

Third-party frameworks are discovered lazily from `coda.frameworks`
entry points on the first `get()`, `detect()`, or `registered_names`
call.

```toml
# Third-party package's pyproject.toml
[project.entry-points."coda.frameworks"]
my_framework = "my_package.framework:MyFramework"
```

### Programmatic Registration

```python
from self_service.frameworks.registry import FrameworkRegistry

registry = FrameworkRegistry()
registry.register(MyFramework())
```

Duplicate names raise `ValueError`.

## Auto-Detection

`registry.detect(device_config)` resolves the framework in priority
order:

1. **Explicit name** — if `device_config.framework` is set, look it
   up by name.  Raises `ConfigError` if not found.
2. **Target matching** — find all frameworks whose
   `supported_targets` contain `device_config.target`.
3. **Single match** — return the one matching framework.
4. **No match** — raise `ConfigError` listing registered frameworks.
5. **Multiple matches** — raise `ConfigError` asking the user to set
   `framework` explicitly.

## `default_registry()`

Returns a fresh `FrameworkRegistry` pre-populated with built-in
frameworks.  Called by `load_executor()` when `CODA_DEVICE_CONFIG` is
set.

```python
from self_service.frameworks.registry import default_registry

registry = default_registry()
print(registry.registered_names)  # ['qua']

config = DeviceConfig(target="superconducting_cz", num_qubits=3)
fw = registry.detect(config)      # → QUAFramework
```

## Error Handling

| Exception | When |
|---|---|
| `ValueError` | Registering a framework with a duplicate name. |
| `ConfigError` | Looking up an unknown framework name, no framework supports the target, or multiple frameworks match the target. |

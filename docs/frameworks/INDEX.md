# Executor Factory Convention

`coda-node` is completely framework-agnostic.  It does not know
about any specific hardware control system.  Backend
integration is achieved through a simple executor factory convention.

## Topics

| Document | Summary |
|---|---|
| [DEVICE_CONFIG.md](DEVICE_CONFIG.md) | How `CODA_DEVICE_CONFIG` passes device configuration to executor factories. |
| [FRAMEWORK_PROTOCOL.md](FRAMEWORK_PROTOCOL.md) | How to implement a backend package with the factory convention. |
| [REGISTRY.md](REGISTRY.md) | Auto-discovery: how the runtime finds executor factories at startup. |

## How It Fits Together

```
Backend package (e.g. coda-acme)
exposes: <pkg>.executor_factory:create_executor
        |
        v
+------------------+
| load_executor()  |  <-- coda-node startup
| (executor.py)    |
+--------+---------+
         |
         v
+------------------+
|  JobExecutor     |  <-- used by RedisConsumer to run circuits
|  (executor.py)   |
+------------------+
```

## Executor Resolution Order

`load_executor()` checks three sources in priority order:

1. **`CODA_EXECUTOR_FACTORY`** -- explicit `module:attribute` import
   path (takes precedence over everything).
2. **`executor_factory` in `CODA_DEVICE_CONFIG`** -- optional top-level
   YAML fallback when the env var is unset.
3. **Convention-based auto-discovery** -- scan installed packages for
   `<pkg>.executor_factory:create_executor`.  Use the factory if
   exactly one match is found.
4. **`NoopExecutor`** fallback -- deterministic all-zeros results for
   testing without hardware.

## Cross-References

- [Executor backends](../jobs/EXECUTOR.md) -- `JobExecutor` protocol
  and `ExecutionResult` format.
- [IR schema](../jobs/IR_SCHEMA.md) -- `NativeGateIR` targets and gate
  sets.
- [Settings reference](../configuration/SETTINGS_REFERENCE.md) --
  `executor_factory` and `device_config` fields.
- [Environment variables](../configuration/ENVIRONMENT_VARIABLES.md)
  -- `CODA_EXECUTOR_FACTORY` and `CODA_DEVICE_CONFIG`.

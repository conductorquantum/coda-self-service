# Hardware Frameworks

The framework subsystem bridges the gap between the hardware-agnostic
`NativeGateIR` circuit format and specific control systems (e.g. QUA
for Quantum Machines OPX).  It provides pluggable hardware support
so that users can point the node at a device config file and have the
right executor created automatically.

## Topics

| Document | Summary |
|---|---|
| [device-config.md](device-config.md) | `DeviceConfig` YAML schema, path resolution, framework-specific options. |
| [framework-protocol.md](framework-protocol.md) | `Framework` protocol, how to implement a new framework, entry-point discovery. |
| [registry.md](registry.md) | `FrameworkRegistry`, auto-detection logic, built-in vs third-party frameworks. |

## Key Files

| File | Role |
|---|---|
| `src/self_service/frameworks/__init__.py` | Public API re-exports. |
| `src/self_service/frameworks/base.py` | `Framework` protocol, `DeviceConfig` model. |
| `src/self_service/frameworks/registry.py` | `FrameworkRegistry`, `default_registry()`, entry-point discovery. |
| `src/self_service/frameworks/qua/__init__.py` | `QUAFramework` — built-in QUA/OPX framework (stub). |
| `src/self_service/frameworks/qubic/__init__.py` | `QubiCFramework` — built-in QubiC/LBNL framework (stub). |

## How It Fits Together

```
User creates device.yaml
        │
        ▼
┌──────────────────┐
│  DeviceConfig     │  ← YAML with target, calibration, framework options
│  (base.py)        │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ FrameworkRegistry │  ← auto-detects framework from target or explicit name
│  (registry.py)    │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  Framework        │  ← validates config, creates executor
│  (e.g. QUA)       │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  JobExecutor      │  ← used by RedisConsumer to run circuits
│  (executor.py)    │
└──────────────────┘
```

## Executor Resolution Order

`load_executor()` checks three sources in priority order:

1. **`CODA_EXECUTOR_FACTORY`** — explicit `module:attribute` import
   path (existing mechanism, takes precedence).
2. **`CODA_DEVICE_CONFIG`** — YAML file path → auto-detect framework
   → validate → create executor.
3. **`NoopExecutor`** fallback — deterministic all-zeros results for
   testing without hardware.

## Cross-References

- [Executor backends](../jobs/executor.md) — `JobExecutor` protocol
  and `ExecutionResult` format.
- [IR schema](../jobs/ir-schema.md) — `NativeGateIR` targets and gate
  sets.
- [Settings reference](../configuration/settings-reference.md) —
  `device_config` field.
- [Environment variables](../configuration/environment-variables.md)
  — `CODA_DEVICE_CONFIG`.

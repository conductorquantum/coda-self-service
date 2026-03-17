# IR Schema

Jobs carry a JSON-serialized quantum circuit in the Native Gate IR
format. The IR is target-aware — each hardware target defines a legal
gate set, and validation rejects programs that use illegal gates or
reference out-of-range qubits.

## Schema (Version 1.0)

```json
{
  "version": "1.0",
  "target": "superconducting_cz",
  "num_qubits": 5,
  "gates": [
    {"gate": "rx", "qubits": [0], "params": [1.5708]},
    {"gate": "cz", "qubits": [0, 1], "params": []},
    {"gate": "rz", "qubits": [1], "params": [0.7854]}
  ],
  "measurements": [0, 1],
  "metadata": {
    "source_hash": "abc123",
    "compiled_at": "2026-01-01T00:00:00Z",
    "compiler_version": "0.1.0",
    "optimization_level": 2
  }
}
```

## Fields

### Top-Level

| Field | Type | Constraints | Description |
|---|---|---|---|
| `version` | `Literal["1.0"]` | Must be `"1.0"` | Schema version. |
| `target` | `string` | Must be a key in `LEGAL_GATES` | Hardware target. |
| `num_qubits` | `int` | 1–50 | Number of qubits on the device. |
| `gates` | `list[GateOp]` | — | Ordered list of gate operations. |
| `measurements` | `list[int]` | Each in `[0, num_qubits)` | Qubits to measure. |
| `metadata` | `IRMetadata` | — | Compilation provenance. |

### GateOp

| Field | Type | Description |
|---|---|---|
| `gate` | `NativeGate` | Gate identifier (e.g. `rx`, `cz`). |
| `qubits` | `list[int]` | Target qubit indices. |
| `params` | `list[float]` | Gate parameters (e.g. rotation angles). |

### IRMetadata

| Field | Type | Default | Description |
|---|---|---|---|
| `source_hash` | `string` | — | Hash of the original circuit source. |
| `compiled_at` | `string` | — | ISO timestamp of compilation. |
| `compiler_version` | `string` | `"0.1.0"` | Compiler version string. |
| `optimization_level` | `int` | `2` | Optimization level (0–3). |

## Supported Gates

```python
class NativeGate(StrEnum):
    RX = "rx"               # Single-qubit X rotation
    RY = "ry"               # Single-qubit Y rotation
    RZ = "rz"               # Single-qubit Z rotation
    CZ = "cz"               # Two-qubit controlled-Z
    ISWAP = "iswap"         # Two-qubit iSWAP
    CP = "cp"               # Two-qubit controlled-phase
    RXX = "rxx"             # Two-qubit XX rotation
    ID = "id"               # Identity (single-qubit, 1 param)
    X90 = "x90"             # Fixed π/2 X rotation (QubiC native)
    Y_MINUS_90 = "y_minus_90"  # Fixed −π/2 Y rotation (QubiC native)
    VIRTUAL_Z = "virtual_z" # Virtual Z rotation (QubiC native)
    CNOT = "cnot"           # Two-qubit CNOT (QubiC native)
```

## Gate Specifications

| Gate | Qubits | Parameters |
|---|---|---|
| `rx` | 1 | 1 (angle) |
| `ry` | 1 | 1 (angle) |
| `rz` | 1 | 1 (angle) |
| `cz` | 2 | 0 |
| `iswap` | 2 | 0 |
| `cp` | 2 | 1 (angle) |
| `rxx` | 2 | 1 (angle) |
| `id` | 1 | 1 |
| `x90` | 1 | 0 |
| `y_minus_90` | 1 | 0 |
| `virtual_z` | 1 | 1 (phase) |
| `cnot` | 2 | 0 |

## Hardware Targets

Each target defines which gates are legal:

| Target | Legal Gates |
|---|---|
| `superconducting_cz` | `rx`, `ry`, `rz`, `cz`, `id` |
| `superconducting_iswap` | `rx`, `ry`, `rz`, `iswap`, `cp`, `id` |
| `superconducting_cnot` | `x90`, `y_minus_90`, `virtual_z`, `cnot`, `id` |
| `trapped_ion` | `rx`, `ry`, `rz`, `rxx`, `id` |
| `silicon_spin_cz` | `rx`, `ry`, `rz`, `cz`, `id` |

## Validation

`NativeGateIR` performs three levels of validation:

### 1. Target Validation (`validate_target`)

Rejects unknown targets not present in `LEGAL_GATES`.

### 2. Gate Shape Validation (`GateOp.validate_gate_shape`)

For each gate operation, checks that the number of qubits and
parameters matches `GATE_SPECS`.

### 3. Consistency Validation (`validate_consistency`)

- Every gate must be legal for the declared target.
- Every qubit index must be in `[0, num_qubits)`.
- Every measurement qubit must be in `[0, num_qubits)`.

## Serialization

```python
# Deserialize and validate from JSON
ir = NativeGateIR.from_json(json_string)

# Serialize to pretty-printed JSON
json_string = ir.to_json()
```

`from_json()` raises `pydantic.ValidationError` if the JSON is
malformed or violates any constraint.

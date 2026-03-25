"""OpenQASM 3.0 <-> NativeGateIR round-trip helpers.

These helpers support a deliberately small OpenQASM subset so tests can
round-trip circuits through text and keep validating that ``NativeGateIR``
remains a valid, stable IR representation going forward. They are not meant
to define a broader OpenQASM compatibility surface.

Supports the ``cz`` and ``cnot`` IR targets for the OpenQASM round-trip subset.
Only the QASM subset needed by these targets is handled; symbolic parameter
expressions (for example ``pi/2``) are not supported, so callers must use
numeric literals.

Known limitation: the ``id`` gate carries a duration parameter in the IR
(nanoseconds) that has no OpenQASM counterpart. ``ir_to_openqasm`` drops
the duration, and ``openqasm_to_ir`` fills it with ``0.0``.
"""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime

from self_service.server.ir import GateOp, IRMetadata, NativeGate, NativeGateIR


class QASMConversionError(Exception):
    """Raised when an OpenQASM program cannot be converted."""


_HALF_PI = math.pi / 2

# ---------------------------------------------------------------------------
# Regex patterns for the supported QASM subset
# TODO: Replace regex parsing with a proper AST parser if the supported QASM
# subset grows (e.g. multi-register circuits, barrier instructions, or new gates).
# ---------------------------------------------------------------------------

_HEADER_RE = re.compile(r"OPENQASM\s+[\d.]+\s*;")
_INCLUDE_RE = re.compile(r'include\s+"[^"]+"\s*;')
_QUBIT_DECL_RE = re.compile(r"qubit\[(\d+)]\s+\w+\s*;")
_BIT_DECL_RE = re.compile(r"bit\[(\d+)]\s+\w+\s*;")
_MEASURE_RE = re.compile(r"\w+\[(\d+)]\s*=\s*measure\s+\w+\[(\d+)]\s*;")
_GATE_RE = re.compile(
    r"(\w+)"
    r"(?:\(([^)]*)\))?"
    r"\s+"
    r"((?:\w+\[\d+])(?:\s*,\s*\w+\[\d+])*)"
    r"\s*;"
)
_QUBIT_REF_RE = re.compile(r"\w+\[(\d+)]")


def _format_float(value: float) -> str:
    """Format a numeric parameter for stable QASM output.

    Args:
        value: Numeric value to serialize.

    Returns:
        String form with enough precision for round-trip comparisons.
    """
    return f"{value:.15g}"


# ---------------------------------------------------------------------------
# OpenQASM → NativeGateIR
# ---------------------------------------------------------------------------


def openqasm_to_ir(
    qasm: str,
    *,
    target: str,
    metadata: IRMetadata | None = None,
) -> NativeGateIR:
    """Parse supported OpenQASM text into ``NativeGateIR``.

    This parser exists primarily to support round-trip validation of the IR.
    It accepts only the subset of OpenQASM needed to confirm that the current
    ``NativeGateIR`` encoding can be serialized and reconstructed reliably.

    Args:
        qasm: OpenQASM 3.0 source text.
        target: Native gate target to validate against.
        metadata: Optional metadata to attach to the returned IR. When omitted,
            placeholder metadata is generated.

    Returns:
        Parsed native-gate IR object.

    Raises:
        QASMConversionError: If the QASM text uses unsupported syntax, gates,
            or targets, or if the resulting IR fails validation.
    """
    num_qubits: int | None = None
    gates: list[GateOp] = []
    measurements: list[int] = []

    for raw in qasm.strip().splitlines():
        line = raw.strip()
        if (
            not line
            or line.startswith("//")
            or _HEADER_RE.match(line)
            or _INCLUDE_RE.match(line)
        ):
            continue
        if _BIT_DECL_RE.match(line):
            continue

        m_q = _QUBIT_DECL_RE.match(line)
        if m_q:
            if num_qubits is not None:
                raise QASMConversionError(
                    "Multiple qubit register declarations are not supported"
                )
            num_qubits = int(m_q.group(1))
            continue

        m_m = _MEASURE_RE.match(line)
        if m_m:
            measurements.append(int(m_m.group(2)))
            continue

        m_g = _GATE_RE.match(line)
        if m_g:
            gate_name = m_g.group(1)
            params = (
                [float(p.strip()) for p in m_g.group(2).split(",")]
                if m_g.group(2)
                else []
            )
            qubits = [int(q) for q in _QUBIT_REF_RE.findall(m_g.group(3))]
            gates.append(_openqasm_gate_to_ir(gate_name, params, qubits, target))
            continue

        raise QASMConversionError(f"Unsupported QASM line: {line!r}")

    if num_qubits is None:
        raise QASMConversionError("No qubit register declaration found")

    if metadata is None:
        metadata = IRMetadata(
            source_hash="sha256:from-qasm",
            compiled_at=datetime.now(UTC).isoformat(),
        )

    try:
        return NativeGateIR(
            target=target,
            num_qubits=num_qubits,
            gates=gates,
            measurements=measurements,
            metadata=metadata,
        )
    except Exception as exc:
        raise QASMConversionError(str(exc)) from exc


# ---------------------------------------------------------------------------
# NativeGateIR → OpenQASM
# ---------------------------------------------------------------------------


def ir_to_openqasm(ir: NativeGateIR) -> str:
    """Serialize ``NativeGateIR`` into the supported OpenQASM subset.

    The output is intentionally limited to the subset understood by
    :func:`openqasm_to_ir` so tests can round-trip circuits through QASM and
    keep treating ``NativeGateIR`` as the durable representation. The only
    known lossy case is the ``id`` gate duration.

    Args:
        ir: Native-gate IR to serialize.

    Returns:
        OpenQASM 3.0 source text.

    Raises:
        QASMConversionError: If the IR contains a gate that has no supported
            mapping for the selected target.
    """
    lines: list[str] = [
        "OPENQASM 3.0;",
        'include "stdgates.inc";',
        f"qubit[{ir.num_qubits}] q;",
    ]
    if ir.measurements:
        lines.append(f"bit[{len(ir.measurements)}] c;")

    for op in ir.gates:
        lines.append(_ir_gate_to_openqasm(op, ir.target))

    for i, qubit in enumerate(ir.measurements):
        lines.append(f"c[{i}] = measure q[{qubit}];")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Internal gate mapping helpers
# ---------------------------------------------------------------------------


def _openqasm_gate_to_ir(
    name: str, params: list[float], qubits: list[int], target: str
) -> GateOp:
    """Map a parsed OpenQASM gate into a target-specific IR operation.

    Args:
        name: Parsed OpenQASM gate name.
        params: Parsed numeric gate parameters.
        qubits: Parsed qubit indices referenced by the gate.
        target: Native gate target that determines the mapping rules.

    Returns:
        Corresponding native-gate operation.

    Raises:
        QASMConversionError: If the target is unsupported.
    """
    if target == "cz":
        return _openqasm_gate_to_ir_cz(name, params, qubits)
    if target == "cnot":
        return _openqasm_gate_to_ir_cnot(name, params, qubits)
    raise QASMConversionError(f"Unsupported target: {target}")


def _openqasm_gate_to_ir_cz(
    name: str, params: list[float], qubits: list[int]
) -> GateOp:
    """Map an OpenQASM gate into the ``cz`` gate set.

    Args:
        name: Parsed OpenQASM gate name.
        params: Parsed numeric gate parameters.
        qubits: Parsed qubit indices referenced by the gate.

    Returns:
        Corresponding native-gate operation.

    Raises:
        QASMConversionError: If the gate is not representable for this target.
    """
    _map: dict[str, tuple[NativeGate, bool]] = {
        "rx": (NativeGate.RX, True),
        "ry": (NativeGate.RY, True),
        "rz": (NativeGate.RZ, True),
        "cz": (NativeGate.CZ, False),
        "id": (NativeGate.ID, False),
    }
    if name not in _map:
        raise QASMConversionError(f"Gate '{name}' not supported for cz")
    ir_gate, has_params = _map[name]
    if ir_gate == NativeGate.ID:
        return GateOp(gate=ir_gate, qubits=qubits, params=[0.0])
    return GateOp(gate=ir_gate, qubits=qubits, params=params if has_params else [])


def _openqasm_gate_to_ir_cnot(
    name: str, params: list[float], qubits: list[int]
) -> GateOp:
    """Map an OpenQASM gate into the ``cnot`` gate set.

    Args:
        name: Parsed QASM gate name.
        params: Parsed numeric gate parameters.
        qubits: Parsed qubit indices referenced by the gate.

    Returns:
        Corresponding native-gate operation.

    Raises:
        QASMConversionError: If the gate is not representable for this target.
    """
    _simple: dict[str, tuple[NativeGate, bool]] = {
        "sx": (NativeGate.X90, False),
        "rz": (NativeGate.VIRTUAL_Z, True),
        "cx": (NativeGate.CNOT, False),
        "id": (NativeGate.ID, False),
    }
    if name in _simple:
        ir_gate, has_params = _simple[name]
        if ir_gate == NativeGate.ID:
            return GateOp(gate=ir_gate, qubits=qubits, params=[0.0])
        return GateOp(gate=ir_gate, qubits=qubits, params=params if has_params else [])

    if name == "ry" and len(params) == 1:
        if math.isclose(params[0], -_HALF_PI, rel_tol=1e-12, abs_tol=1e-12):
            return GateOp(gate=NativeGate.Y_MINUS_90, qubits=qubits, params=[])
        raise QASMConversionError(
            f"ry({params[0]}) not representable in cnot "
            f"(only ry(-π/2) maps to y_minus_90)"
        )

    raise QASMConversionError(f"Gate '{name}' not supported for cnot")


def _ir_gate_to_openqasm(op: GateOp, target: str) -> str:
    """Map an IR operation into target-specific OpenQASM text.

    Args:
        op: IR gate operation to serialize.
        target: Native gate target that determines the mapping rules.

    Returns:
        Single OpenQASM instruction line.

    Raises:
        QASMConversionError: If the target is unsupported.
    """
    name = op.gate.value
    qubits_str = ", ".join(f"q[{q}]" for q in op.qubits)

    if target == "cz":
        return _ir_gate_to_openqasm_cz(name, op.params, qubits_str)
    if target == "cnot":
        return _ir_gate_to_openqasm_cnot(name, op.params, qubits_str)
    raise QASMConversionError(f"Unsupported target: {target}")


def _ir_gate_to_openqasm_cz(name: str, params: list[float], qubits_str: str) -> str:
    """Serialize a ``cz`` IR gate into OpenQASM text.

    Args:
        name: Native gate name.
        params: Gate parameters to emit.
        qubits_str: Preformatted OpenQASM qubit operand list.

    Returns:
        Single OpenQASM instruction line.

    Raises:
        QASMConversionError: If the gate has no supported OpenQASM mapping.
    """
    _parameterized = {"rx", "ry", "rz"}
    _parameterless = {"cz", "id"}
    if name in _parameterized:
        ps = ", ".join(_format_float(p) for p in params)
        return f"{name}({ps}) {qubits_str};"
    if name == "virtual_z":
        if not params:
            raise QASMConversionError(
                "IR gate 'virtual_z' requires exactly one parameter"
            )
        return f"rz({_format_float(params[0])}) {qubits_str};"
    if name in _parameterless:
        return f"{name} {qubits_str};"
    raise QASMConversionError(
        f"IR gate '{name}' has no OpenQASM mapping for cz"
    )


def _ir_gate_to_openqasm_cnot(name: str, params: list[float], qubits_str: str) -> str:
    """Serialize a ``cnot`` IR gate into OpenQASM text.

    Args:
        name: Native gate name.
        params: Gate parameters to emit.
        qubits_str: Preformatted OpenQASM qubit operand list.

    Returns:
        Single OpenQASM instruction line.

    Raises:
        QASMConversionError: If the gate has no supported OpenQASM mapping.
    """
    if name == "x90":
        return f"sx {qubits_str};"
    if name == "y_minus_90":
        return f"ry({_format_float(-_HALF_PI)}) {qubits_str};"
    if name == "virtual_z":
        return f"rz({_format_float(params[0])}) {qubits_str};"
    if name == "cnot":
        return f"cx {qubits_str};"
    if name == "id":
        return f"id {qubits_str};"
    raise QASMConversionError(
        f"IR gate '{name}' has no OpenQASM mapping for cnot"
    )

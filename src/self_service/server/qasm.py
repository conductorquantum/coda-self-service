"""OpenQASM 3.0 ↔ NativeGateIR round-trip conversion.

Supports the ``superconducting_cz`` and ``superconducting_cnot`` IR targets.
Only the QASM subset needed by these targets is handled; symbolic parameter
expressions (e.g. ``pi/2``) are not supported — use numeric literals.

Known limitation: the ``id`` gate carries a duration parameter in the IR
(nanoseconds) that has no OpenQASM counterpart.  ``ir_to_openqasm`` drops
the duration, and ``openqasm_to_ir`` fills it with ``0.0``.
"""

from __future__ import annotations

import math
import re

from self_service.server.ir import GateOp, IRMetadata, NativeGate, NativeGateIR


class QASMConversionError(Exception):
    """Raised when an OpenQASM program cannot be converted."""


_HP = math.pi / 2

# ---------------------------------------------------------------------------
# Regex patterns for the supported QASM subset
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
    """Format with enough precision for lossless round-trip."""
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
    """Parse a minimal OpenQASM 3.0 program into a ``NativeGateIR``.

    Parameters
    ----------
    qasm:
        OpenQASM 3.0 source text.
    target:
        IR target, e.g. ``"superconducting_cz"`` or ``"superconducting_cnot"``.
    metadata:
        Optional provenance metadata; a default is used if omitted.
    """
    num_qubits: int | None = None
    gates: list[GateOp] = []
    measurements: list[int] = []

    for raw in qasm.strip().splitlines():
        line = raw.strip()
        if not line or _HEADER_RE.match(line) or _INCLUDE_RE.match(line):
            continue
        if _BIT_DECL_RE.match(line):
            continue

        m_q = _QUBIT_DECL_RE.match(line)
        if m_q:
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
            gates.append(_qasm_gate_to_ir(gate_name, params, qubits, target))
            continue

        raise QASMConversionError(f"Unsupported QASM line: {line!r}")

    if num_qubits is None:
        raise QASMConversionError("No qubit register declaration found")

    if metadata is None:
        metadata = IRMetadata(
            source_hash="sha256:from-qasm",
            compiled_at="2026-01-01T00:00:00Z",
        )

    return NativeGateIR(
        target=target,
        num_qubits=num_qubits,
        gates=gates,
        measurements=measurements,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# NativeGateIR → OpenQASM
# ---------------------------------------------------------------------------


def ir_to_openqasm(ir: NativeGateIR) -> str:
    """Serialize a ``NativeGateIR`` to an OpenQASM 3.0 string.

    The output only uses the gate subset understood by :func:`openqasm_to_ir`,
    ensuring a lossless round-trip (except for ``id`` gate durations).
    """
    lines: list[str] = [
        "OPENQASM 3.0;",
        'include "stdgates.inc";',
        f"qubit[{ir.num_qubits}] q;",
    ]
    if ir.measurements:
        lines.append(f"bit[{len(ir.measurements)}] c;")

    for op in ir.gates:
        lines.append(_ir_gate_to_qasm(op, ir.target))

    for i, qubit in enumerate(ir.measurements):
        lines.append(f"c[{i}] = measure q[{qubit}];")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Internal gate mapping helpers
# ---------------------------------------------------------------------------


def _qasm_gate_to_ir(
    name: str, params: list[float], qubits: list[int], target: str
) -> GateOp:
    if target == "superconducting_cz":
        return _qasm_gate_to_ir_cz(name, params, qubits)
    if target == "superconducting_cnot":
        return _qasm_gate_to_ir_cnot(name, params, qubits)
    raise QASMConversionError(f"Unsupported target: {target}")


def _qasm_gate_to_ir_cz(
    name: str, params: list[float], qubits: list[int]
) -> GateOp:
    _map: dict[str, tuple[NativeGate, bool]] = {
        "rx": (NativeGate.RX, True),
        "ry": (NativeGate.RY, True),
        "rz": (NativeGate.RZ, True),
        "cz": (NativeGate.CZ, False),
        "id": (NativeGate.ID, False),
    }
    if name not in _map:
        raise QASMConversionError(
            f"Gate '{name}' not supported for superconducting_cz"
        )
    ir_gate, has_params = _map[name]
    if ir_gate == NativeGate.ID:
        return GateOp(gate=ir_gate, qubits=qubits, params=[0.0])
    return GateOp(
        gate=ir_gate, qubits=qubits, params=params if has_params else []
    )


def _qasm_gate_to_ir_cnot(
    name: str, params: list[float], qubits: list[int]
) -> GateOp:
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
        return GateOp(
            gate=ir_gate, qubits=qubits, params=params if has_params else []
        )

    if name == "ry" and len(params) == 1:
        if math.isclose(params[0], -_HP, rel_tol=1e-12, abs_tol=1e-12):
            return GateOp(
                gate=NativeGate.Y_MINUS_90, qubits=qubits, params=[]
            )
        raise QASMConversionError(
            f"ry({params[0]}) not representable in superconducting_cnot "
            f"(only ry(-π/2) maps to y_minus_90)"
        )

    raise QASMConversionError(
        f"Gate '{name}' not supported for superconducting_cnot"
    )


def _ir_gate_to_qasm(op: GateOp, target: str) -> str:
    name = op.gate.value
    qubits_str = ", ".join(f"q[{q}]" for q in op.qubits)

    if target == "superconducting_cz":
        return _ir_gate_to_qasm_cz(name, op.params, qubits_str)
    if target == "superconducting_cnot":
        return _ir_gate_to_qasm_cnot(name, op.params, qubits_str)
    raise QASMConversionError(f"Unsupported target: {target}")


def _ir_gate_to_qasm_cz(
    name: str, params: list[float], qubits_str: str
) -> str:
    _parameterized = {"rx", "ry", "rz"}
    _parameterless = {"cz", "id"}
    if name in _parameterized:
        ps = ", ".join(_format_float(p) for p in params)
        return f"{name}({ps}) {qubits_str};"
    if name in _parameterless:
        return f"{name} {qubits_str};"
    raise QASMConversionError(
        f"IR gate '{name}' has no QASM mapping for superconducting_cz"
    )


def _ir_gate_to_qasm_cnot(
    name: str, params: list[float], qubits_str: str
) -> str:
    if name == "x90":
        return f"sx {qubits_str};"
    if name == "y_minus_90":
        return f"ry({_format_float(-_HP)}) {qubits_str};"
    if name == "virtual_z":
        return f"rz({_format_float(params[0])}) {qubits_str};"
    if name == "cnot":
        return f"cx {qubits_str};"
    if name == "id":
        return f"id {qubits_str};"
    raise QASMConversionError(
        f"IR gate '{name}' has no QASM mapping for superconducting_cnot"
    )

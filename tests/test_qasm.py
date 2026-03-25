"""Tests for OpenQASM 3.0 <-> NativeGateIR round-trip conversion.

The QASM round-trip exists as a test harness for ``NativeGateIR``. These tests
verify that the IR can be serialized and reconstructed consistently so it
remains a valid representation going forward.
"""

from __future__ import annotations

import math

import pytest

from self_service.server.ir import GateOp, IRMetadata, NativeGate, NativeGateIR
from self_service.server.qasm import (
    QASMConversionError,
    ir_to_openqasm,
    openqasm_to_ir,
)


def _metadata() -> IRMetadata:
    """Build deterministic metadata for round-trip assertions.

    Returns:
        Stable metadata object shared across tests.
    """
    return IRMetadata(
        source_hash="sha256:qasm-test", compiled_at="2026-03-17T00:00:00Z"
    )


# ===================================================================
# cz: QASM → IR → QASM
# ===================================================================


class TestCZQASMRoundTrip:
    """Round-trip coverage for the ``cz`` target."""

    def test_full_circuit(self) -> None:
        """Preserve a full CZ-target circuit through QASM round-trip."""
        qasm = (
            "OPENQASM 3.0;\n"
            'include "stdgates.inc";\n'
            "qubit[3] q;\n"
            "bit[2] c;\n"
            "rx(1.5707963267949) q[0];\n"
            "ry(0.3) q[1];\n"
            "rz(0.4) q[2];\n"
            "cz q[0], q[1];\n"
            "c[0] = measure q[0];\n"
            "c[1] = measure q[1];\n"
        )
        ir = openqasm_to_ir(qasm, target="cz")
        roundtripped = ir_to_openqasm(ir)
        ir2 = openqasm_to_ir(
            roundtripped, target="cz", metadata=ir.metadata
        )
        assert ir.gates == ir2.gates
        assert ir.measurements == ir2.measurements
        assert ir.num_qubits == ir2.num_qubits

    def test_single_gate_roundtrips(self) -> None:
        """Round-trip each supported CZ-target gate independently."""
        for gate_line, expected_gate in [
            ("rx(0.123) q[0];", "rx"),
            ("ry(-0.456) q[1];", "ry"),
            ("rz(3.14159265358979) q[2];", "rz"),
            ("cz q[0], q[1];", "cz"),
        ]:
            qasm = (
                "OPENQASM 3.0;\n"
                'include "stdgates.inc";\n'
                "qubit[3] q;\n"
                "bit[1] c;\n"
                f"{gate_line}\n"
                "c[0] = measure q[0];\n"
            )
            ir = openqasm_to_ir(qasm, target="cz")
            assert ir.gates[0].gate.value == expected_gate
            roundtripped = ir_to_openqasm(ir)
            ir2 = openqasm_to_ir(
                roundtripped,
                target="cz",
                metadata=ir.metadata,
            )
            assert ir.gates == ir2.gates

    def test_ir_roundtrip(self) -> None:
        """Rebuild the original CZ-target IR from serialized QASM."""
        ir = NativeGateIR(
            target="cz",
            num_qubits=3,
            gates=[
                GateOp(gate=NativeGate.RX, qubits=[0], params=[0.5]),
                GateOp(gate=NativeGate.RY, qubits=[1], params=[-1.2]),
                GateOp(gate=NativeGate.RZ, qubits=[2], params=[3.0]),
                GateOp(gate=NativeGate.CZ, qubits=[0, 1], params=[]),
            ],
            measurements=[0, 1],
            metadata=_metadata(),
        )
        qasm = ir_to_openqasm(ir)
        ir2 = openqasm_to_ir(qasm, target="cz", metadata=ir.metadata)
        assert ir.gates == ir2.gates
        assert ir.measurements == ir2.measurements
        assert ir.num_qubits == ir2.num_qubits

    def test_text_stability(self) -> None:
        """Keep stable input QASM byte-identical after round-trip."""
        qasm = (
            "OPENQASM 3.0;\n"
            'include "stdgates.inc";\n'
            "qubit[2] q;\n"
            "bit[1] c;\n"
            "rx(0.5) q[0];\n"
            "cz q[0], q[1];\n"
            "c[0] = measure q[0];\n"
        )
        ir = openqasm_to_ir(qasm, target="cz")
        assert ir_to_openqasm(ir) == qasm


# ===================================================================
# cnot: QASM → IR → QASM
# ===================================================================


class TestCNOTQASMRoundTrip:
    """Round-trip coverage for the ``cnot`` target."""

    def test_full_circuit(self) -> None:
        """Preserve a full CNOT-target circuit through QASM round-trip."""
        qasm = (
            "OPENQASM 3.0;\n"
            'include "stdgates.inc";\n'
            "qubit[4] q;\n"
            "bit[2] c;\n"
            "sx q[0];\n"
            f"ry({-math.pi / 2:.15g}) q[1];\n"
            "rz(0.789) q[2];\n"
            "cx q[0], q[1];\n"
            "c[0] = measure q[0];\n"
            "c[1] = measure q[1];\n"
        )
        ir = openqasm_to_ir(qasm, target="cnot")
        roundtripped = ir_to_openqasm(ir)
        ir2 = openqasm_to_ir(
            roundtripped, target="cnot", metadata=ir.metadata
        )
        assert ir.gates == ir2.gates
        assert ir.measurements == ir2.measurements

    def test_gate_mapping(self) -> None:
        """Map each supported CNOT-target QASM gate into the expected IR."""
        qasm = (
            "OPENQASM 3.0;\n"
            'include "stdgates.inc";\n'
            "qubit[2] q;\n"
            "bit[1] c;\n"
            "sx q[0];\n"
            f"ry({-math.pi / 2:.15g}) q[1];\n"
            "rz(1.23) q[0];\n"
            "cx q[0], q[1];\n"
            "c[0] = measure q[0];\n"
        )
        ir = openqasm_to_ir(qasm, target="cnot")
        assert ir.gates[0].gate == NativeGate.X90
        assert ir.gates[1].gate == NativeGate.Y_MINUS_90
        assert ir.gates[2].gate == NativeGate.VIRTUAL_Z
        assert ir.gates[2].params == [1.23]
        assert ir.gates[3].gate == NativeGate.CNOT

    def test_ir_roundtrip(self) -> None:
        """Rebuild the original CNOT-target IR from serialized QASM."""
        ir = NativeGateIR(
            target="cnot",
            num_qubits=4,
            gates=[
                GateOp(gate=NativeGate.X90, qubits=[0], params=[]),
                GateOp(gate=NativeGate.Y_MINUS_90, qubits=[1], params=[]),
                GateOp(gate=NativeGate.VIRTUAL_Z, qubits=[2], params=[0.789]),
                GateOp(gate=NativeGate.CNOT, qubits=[0, 1], params=[]),
            ],
            measurements=[0, 1],
            metadata=_metadata(),
        )
        qasm = ir_to_openqasm(ir)
        ir2 = openqasm_to_ir(qasm, target="cnot", metadata=ir.metadata)
        assert ir.gates == ir2.gates
        assert ir.measurements == ir2.measurements

    def test_text_stability(self) -> None:
        """Keep stable CNOT-target QASM byte-identical after round-trip."""
        qasm = (
            "OPENQASM 3.0;\n"
            'include "stdgates.inc";\n'
            "qubit[2] q;\n"
            "bit[1] c;\n"
            "sx q[0];\n"
            "cx q[0], q[1];\n"
            "c[0] = measure q[0];\n"
        )
        ir = openqasm_to_ir(qasm, target="cnot")
        assert ir_to_openqasm(ir) == qasm


# ===================================================================
# Complex multi-gate circuit
# ===================================================================


class TestComplexCircuitRoundTrip:
    """Coverage for larger circuits that stress parameter preservation."""

    def test_multi_gate_circuit_preserves_params(self) -> None:
        """Preserve gate ordering, operands, and parameters across round-trip."""
        ir = NativeGateIR(
            target="cz",
            num_qubits=5,
            gates=[
                GateOp(gate=NativeGate.RX, qubits=[0], params=[math.pi / 4]),
                GateOp(gate=NativeGate.RY, qubits=[1], params=[math.pi / 3]),
                GateOp(gate=NativeGate.CZ, qubits=[0, 1], params=[]),
                GateOp(gate=NativeGate.RZ, qubits=[0], params=[-0.5]),
                GateOp(gate=NativeGate.RX, qubits=[2], params=[1.0]),
                GateOp(gate=NativeGate.CZ, qubits=[2, 3], params=[]),
                GateOp(gate=NativeGate.RY, qubits=[4], params=[2.0]),
            ],
            measurements=[0, 1, 2, 3, 4],
            metadata=_metadata(),
        )
        qasm = ir_to_openqasm(ir)
        ir2 = openqasm_to_ir(qasm, target="cz", metadata=ir.metadata)
        assert len(ir.gates) == len(ir2.gates)
        for g1, g2 in zip(ir.gates, ir2.gates, strict=True):
            assert g1.gate == g2.gate
            assert g1.qubits == g2.qubits
            for p1, p2 in zip(g1.params, g2.params, strict=True):
                assert math.isclose(p1, p2, rel_tol=1e-12)


# ===================================================================
# Error cases
# ===================================================================


class TestQASMConversionErrors:
    """Error handling coverage for unsupported or invalid QASM."""

    def test_unsupported_gate_raises(self) -> None:
        """Reject gates that are outside the supported subset."""
        qasm = 'OPENQASM 3.0;\ninclude "stdgates.inc";\nqubit[2] q;\nh q[0];\n'
        with pytest.raises(QASMConversionError, match="not supported"):
            openqasm_to_ir(qasm, target="cz")

    def test_bad_ry_angle_for_cnot_raises(self) -> None:
        """Reject CNOT-target ``ry`` angles that have no IR mapping."""
        qasm = 'OPENQASM 3.0;\ninclude "stdgates.inc";\nqubit[2] q;\nry(0.5) q[0];\n'
        with pytest.raises(QASMConversionError, match="not representable"):
            openqasm_to_ir(qasm, target="cnot")

    def test_missing_qubit_register_raises(self) -> None:
        """Require an explicit qubit register declaration."""
        qasm = "OPENQASM 3.0;\nrx(0.5) q[0];\n"
        with pytest.raises(QASMConversionError, match="No qubit register"):
            openqasm_to_ir(qasm, target="cz")

    def test_unsupported_target_raises(self) -> None:
        """Reject targets that the round-trip helper does not support."""
        qasm = 'OPENQASM 3.0;\ninclude "stdgates.inc";\nqubit[2] q;\nrx(0.5) q[0];\n'
        with pytest.raises(QASMConversionError, match="Unsupported target"):
            openqasm_to_ir(qasm, target="iswap")

    def test_comment_lines_are_skipped(self) -> None:
        """Ignore comment lines while parsing supported QASM."""
        qasm = (
            "OPENQASM 3.0;\n"
            "// generated by compiler v2\n"
            'include "stdgates.inc";\n'
            "qubit[2] q;\n"
            "bit[1] c;\n"
            "// apply rotation\n"
            "rx(0.5) q[0];\n"
            "c[0] = measure q[0];\n"
        )
        ir = openqasm_to_ir(qasm, target="cz")
        assert ir.gates[0].gate == NativeGate.RX

    def test_multiple_qubit_registers_raises(self) -> None:
        """Reject programs that declare more than one qubit register."""
        qasm = (
            "OPENQASM 3.0;\n"
            'include "stdgates.inc";\n'
            "qubit[3] q;\n"
            "qubit[5] r;\n"
            "rx(0.5) q[0];\n"
        )
        with pytest.raises(QASMConversionError, match="Multiple qubit register"):
            openqasm_to_ir(qasm, target="cz")

    def test_out_of_range_qubit_raises_conversion_error(self) -> None:
        """Surface IR validation errors for invalid qubit indices."""
        qasm = 'OPENQASM 3.0;\ninclude "stdgates.inc";\nqubit[2] q;\nrx(0.5) q[9];\n'
        with pytest.raises(QASMConversionError):
            openqasm_to_ir(qasm, target="cz")

    def test_default_metadata_uses_current_time(self) -> None:
        """Generate placeholder metadata when callers do not supply any."""
        from datetime import UTC, datetime

        before = datetime.now(UTC)
        qasm = 'OPENQASM 3.0;\ninclude "stdgates.inc";\nqubit[2] q;\nrx(0.5) q[0];\n'
        ir = openqasm_to_ir(qasm, target="cz")
        after = datetime.now(UTC)
        compiled = datetime.fromisoformat(ir.metadata.compiled_at)
        assert before <= compiled <= after

    def test_id_gate_roundtrip_lossy(self) -> None:
        """Document that ``id`` duration is intentionally lost through QASM."""
        ir = NativeGateIR(
            target="cz",
            num_qubits=1,
            gates=[GateOp(gate=NativeGate.ID, qubits=[0], params=[100.0])],
            measurements=[0],
            metadata=_metadata(),
        )
        qasm = ir_to_openqasm(ir)
        assert "id q[0];" in qasm
        ir2 = openqasm_to_ir(qasm, target="cz", metadata=ir.metadata)
        assert ir2.gates[0].gate == NativeGate.ID
        assert ir2.gates[0].params == [0.0]

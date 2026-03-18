"""Tests for OpenQASM 3.0 ↔ NativeGateIR round-trip conversion."""

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
    return IRMetadata(
        source_hash="sha256:qasm-test", compiled_at="2026-03-17T00:00:00Z"
    )


# ===================================================================
# superconducting_cz: QASM → IR → QASM
# ===================================================================


class TestCZQASMRoundTrip:
    """Round-trip tests for the superconducting_cz target."""

    def test_full_circuit(self) -> None:
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
        ir = openqasm_to_ir(qasm, target="superconducting_cz")
        roundtripped = ir_to_openqasm(ir)
        ir2 = openqasm_to_ir(
            roundtripped, target="superconducting_cz", metadata=ir.metadata
        )
        assert ir.gates == ir2.gates
        assert ir.measurements == ir2.measurements
        assert ir.num_qubits == ir2.num_qubits

    def test_single_gate_roundtrips(self) -> None:
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
            ir = openqasm_to_ir(qasm, target="superconducting_cz")
            assert ir.gates[0].gate.value == expected_gate
            roundtripped = ir_to_openqasm(ir)
            ir2 = openqasm_to_ir(
                roundtripped,
                target="superconducting_cz",
                metadata=ir.metadata,
            )
            assert ir.gates == ir2.gates

    def test_ir_roundtrip(self) -> None:
        ir = NativeGateIR(
            target="superconducting_cz",
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
        ir2 = openqasm_to_ir(
            qasm, target="superconducting_cz", metadata=ir.metadata
        )
        assert ir.gates == ir2.gates
        assert ir.measurements == ir2.measurements
        assert ir.num_qubits == ir2.num_qubits

    def test_text_stability(self) -> None:
        """QASM → IR → QASM produces byte-identical output."""
        qasm = (
            "OPENQASM 3.0;\n"
            'include "stdgates.inc";\n'
            "qubit[2] q;\n"
            "bit[1] c;\n"
            "rx(0.5) q[0];\n"
            "cz q[0], q[1];\n"
            "c[0] = measure q[0];\n"
        )
        ir = openqasm_to_ir(qasm, target="superconducting_cz")
        assert ir_to_openqasm(ir) == qasm


# ===================================================================
# superconducting_cnot: QASM → IR → QASM
# ===================================================================


class TestCNOTQASMRoundTrip:
    """Round-trip tests for the superconducting_cnot target."""

    def test_full_circuit(self) -> None:
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
        ir = openqasm_to_ir(qasm, target="superconducting_cnot")
        roundtripped = ir_to_openqasm(ir)
        ir2 = openqasm_to_ir(
            roundtripped, target="superconducting_cnot", metadata=ir.metadata
        )
        assert ir.gates == ir2.gates
        assert ir.measurements == ir2.measurements

    def test_gate_mapping(self) -> None:
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
        ir = openqasm_to_ir(qasm, target="superconducting_cnot")
        assert ir.gates[0].gate == NativeGate.X90
        assert ir.gates[1].gate == NativeGate.Y_MINUS_90
        assert ir.gates[2].gate == NativeGate.VIRTUAL_Z
        assert ir.gates[2].params == [1.23]
        assert ir.gates[3].gate == NativeGate.CNOT

    def test_ir_roundtrip(self) -> None:
        ir = NativeGateIR(
            target="superconducting_cnot",
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
        ir2 = openqasm_to_ir(
            qasm, target="superconducting_cnot", metadata=ir.metadata
        )
        assert ir.gates == ir2.gates
        assert ir.measurements == ir2.measurements

    def test_text_stability(self) -> None:
        qasm = (
            "OPENQASM 3.0;\n"
            'include "stdgates.inc";\n'
            "qubit[2] q;\n"
            "bit[1] c;\n"
            "sx q[0];\n"
            "cx q[0], q[1];\n"
            "c[0] = measure q[0];\n"
        )
        ir = openqasm_to_ir(qasm, target="superconducting_cnot")
        assert ir_to_openqasm(ir) == qasm


# ===================================================================
# Complex multi-gate circuit
# ===================================================================


class TestComplexCircuitRoundTrip:
    def test_multi_gate_circuit_preserves_params(self) -> None:
        ir = NativeGateIR(
            target="superconducting_cz",
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
        ir2 = openqasm_to_ir(
            qasm, target="superconducting_cz", metadata=ir.metadata
        )
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
    def test_unsupported_gate_raises(self) -> None:
        qasm = (
            "OPENQASM 3.0;\n"
            'include "stdgates.inc";\n'
            "qubit[2] q;\n"
            "h q[0];\n"
        )
        with pytest.raises(QASMConversionError, match="not supported"):
            openqasm_to_ir(qasm, target="superconducting_cz")

    def test_bad_ry_angle_for_cnot_raises(self) -> None:
        qasm = (
            "OPENQASM 3.0;\n"
            'include "stdgates.inc";\n'
            "qubit[2] q;\n"
            "ry(0.5) q[0];\n"
        )
        with pytest.raises(QASMConversionError, match="not representable"):
            openqasm_to_ir(qasm, target="superconducting_cnot")

    def test_missing_qubit_register_raises(self) -> None:
        qasm = "OPENQASM 3.0;\nrx(0.5) q[0];\n"
        with pytest.raises(QASMConversionError, match="No qubit register"):
            openqasm_to_ir(qasm, target="superconducting_cz")

    def test_unsupported_target_raises(self) -> None:
        qasm = (
            "OPENQASM 3.0;\n"
            'include "stdgates.inc";\n'
            "qubit[2] q;\n"
            "rx(0.5) q[0];\n"
        )
        with pytest.raises(QASMConversionError, match="Unsupported target"):
            openqasm_to_ir(qasm, target="trapped_ion")

    def test_id_gate_roundtrip_lossy(self) -> None:
        """id duration is lost through QASM; round-trip yields 0.0."""
        ir = NativeGateIR(
            target="superconducting_cz",
            num_qubits=1,
            gates=[GateOp(gate=NativeGate.ID, qubits=[0], params=[100.0])],
            measurements=[0],
            metadata=_metadata(),
        )
        qasm = ir_to_openqasm(ir)
        assert "id q[0];" in qasm
        ir2 = openqasm_to_ir(
            qasm, target="superconducting_cz", metadata=ir.metadata
        )
        assert ir2.gates[0].gate == NativeGate.ID
        assert ir2.gates[0].params == [0.0]

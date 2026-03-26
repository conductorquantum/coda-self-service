"""Tests for NativeGateIR schema validation across all targets.

Covers gate legality, parameter/qubit shape validation, target rejection,
JSON round-trips, and cross-target isolation for every supported gateset
including the parametric CZ (pcz) target.
"""

from __future__ import annotations

import math

import pytest

from coda_node.server.ir import (
    LEGAL_GATES,
    GateOp,
    IRMetadata,
    NativeGate,
    NativeGateIR,
)


def _metadata() -> IRMetadata:
    return IRMetadata(source_hash="sha256:test-ir", compiled_at="2026-03-26T00:00:00Z")


# ===================================================================
# pcz target
# ===================================================================


class TestPczTarget:
    """Validation for the ``pcz`` target (native two-qubit gate: ``cp``)."""

    def test_accepts_cp_gate(self) -> None:
        ir = NativeGateIR(
            target="pcz",
            num_qubits=2,
            gates=[
                GateOp(gate=NativeGate.RY, qubits=[0], params=[math.pi / 2]),
                GateOp(gate=NativeGate.CP, qubits=[0, 1], params=[math.pi]),
            ],
            measurements=[0, 1],
            metadata=_metadata(),
        )
        assert ir.target == "pcz"
        assert len(ir.gates) == 2

    def test_accepts_all_legal_single_qubit_gates(self) -> None:
        ir = NativeGateIR(
            target="pcz",
            num_qubits=2,
            gates=[
                GateOp(gate=NativeGate.RX, qubits=[0], params=[0.5]),
                GateOp(gate=NativeGate.RY, qubits=[1], params=[1.0]),
                GateOp(gate=NativeGate.RZ, qubits=[0], params=[2.0]),
                GateOp(gate=NativeGate.ID, qubits=[1], params=[100.0]),
            ],
            measurements=[0, 1],
            metadata=_metadata(),
        )
        assert len(ir.gates) == 4

    def test_accepts_multiple_cp_gates(self) -> None:
        ir = NativeGateIR(
            target="pcz",
            num_qubits=3,
            gates=[
                GateOp(gate=NativeGate.RY, qubits=[0], params=[math.pi / 2]),
                GateOp(gate=NativeGate.CP, qubits=[0, 1], params=[math.pi]),
                GateOp(gate=NativeGate.RY, qubits=[1], params=[math.pi / 2]),
                GateOp(gate=NativeGate.CP, qubits=[1, 2], params=[math.pi / 2]),
            ],
            measurements=[0, 1, 2],
            metadata=_metadata(),
        )
        cp_count = sum(1 for g in ir.gates if g.gate == NativeGate.CP)
        assert cp_count == 2

    def test_rejects_cz_gate(self) -> None:
        with pytest.raises(Exception, match="not legal"):
            NativeGateIR(
                target="pcz",
                num_qubits=2,
                gates=[GateOp(gate=NativeGate.CZ, qubits=[0, 1], params=[])],
                measurements=[0, 1],
                metadata=_metadata(),
            )

    def test_rejects_iswap_gate(self) -> None:
        with pytest.raises(Exception, match="not legal"):
            NativeGateIR(
                target="pcz",
                num_qubits=2,
                gates=[GateOp(gate=NativeGate.ISWAP, qubits=[0, 1], params=[])],
                measurements=[0, 1],
                metadata=_metadata(),
            )

    def test_rejects_cnot_gate(self) -> None:
        with pytest.raises(Exception, match="not legal"):
            NativeGateIR(
                target="pcz",
                num_qubits=2,
                gates=[GateOp(gate=NativeGate.CNOT, qubits=[0, 1], params=[])],
                measurements=[0, 1],
                metadata=_metadata(),
            )

    def test_json_round_trip(self) -> None:
        ir = NativeGateIR(
            target="pcz",
            num_qubits=2,
            gates=[
                GateOp(gate=NativeGate.RX, qubits=[0], params=[0.5]),
                GateOp(gate=NativeGate.CP, qubits=[0, 1], params=[math.pi]),
                GateOp(gate=NativeGate.RZ, qubits=[1], params=[0.3]),
            ],
            measurements=[0, 1],
            metadata=_metadata(),
        )
        restored = NativeGateIR.from_json(ir.to_json())
        assert restored == ir

    def test_cp_requires_one_param(self) -> None:
        with pytest.raises(Exception, match="param"):
            GateOp(gate=NativeGate.CP, qubits=[0, 1], params=[])

    def test_cp_requires_two_qubits(self) -> None:
        with pytest.raises(Exception, match="qubit"):
            GateOp(gate=NativeGate.CP, qubits=[0], params=[1.0])


# ===================================================================
# Cross-target isolation: each target rejects the others' 2Q gates
# ===================================================================


class TestCrossTargetIsolation:
    """Verify each gateset only accepts its own two-qubit gate."""

    def test_cz_rejects_cp(self) -> None:
        with pytest.raises(Exception, match="not legal"):
            NativeGateIR(
                target="cz",
                num_qubits=2,
                gates=[GateOp(gate=NativeGate.CP, qubits=[0, 1], params=[1.0])],
                measurements=[0, 1],
                metadata=_metadata(),
            )

    def test_cz_rejects_iswap(self) -> None:
        with pytest.raises(Exception, match="not legal"):
            NativeGateIR(
                target="cz",
                num_qubits=2,
                gates=[GateOp(gate=NativeGate.ISWAP, qubits=[0, 1], params=[])],
                measurements=[0, 1],
                metadata=_metadata(),
            )

    def test_iswap_rejects_cp(self) -> None:
        with pytest.raises(Exception, match="not legal"):
            NativeGateIR(
                target="iswap",
                num_qubits=2,
                gates=[GateOp(gate=NativeGate.CP, qubits=[0, 1], params=[1.0])],
                measurements=[0, 1],
                metadata=_metadata(),
            )

    def test_iswap_rejects_cz(self) -> None:
        with pytest.raises(Exception, match="not legal"):
            NativeGateIR(
                target="iswap",
                num_qubits=2,
                gates=[GateOp(gate=NativeGate.CZ, qubits=[0, 1], params=[])],
                measurements=[0, 1],
                metadata=_metadata(),
            )

    def test_pcz_rejects_cz(self) -> None:
        with pytest.raises(Exception, match="not legal"):
            NativeGateIR(
                target="pcz",
                num_qubits=2,
                gates=[GateOp(gate=NativeGate.CZ, qubits=[0, 1], params=[])],
                measurements=[0, 1],
                metadata=_metadata(),
            )

    def test_pcz_rejects_iswap(self) -> None:
        with pytest.raises(Exception, match="not legal"):
            NativeGateIR(
                target="pcz",
                num_qubits=2,
                gates=[GateOp(gate=NativeGate.ISWAP, qubits=[0, 1], params=[])],
                measurements=[0, 1],
                metadata=_metadata(),
            )


# ===================================================================
# Target validation
# ===================================================================


class TestTargetValidation:
    """Every entry in LEGAL_GATES is accepted; unknown targets are rejected."""

    @pytest.mark.parametrize("target", list(LEGAL_GATES.keys()))
    def test_all_known_targets_are_accepted(self, target: str) -> None:
        ir = NativeGateIR(
            target=target,
            num_qubits=1,
            gates=[],
            measurements=[0],
            metadata=_metadata(),
        )
        assert ir.target == target

    def test_unknown_target_rejected(self) -> None:
        with pytest.raises(Exception, match="Unknown target"):
            NativeGateIR(
                target="nonexistent",
                num_qubits=2,
                gates=[],
                measurements=[0, 1],
                metadata=_metadata(),
            )

    def test_pcz_is_in_legal_gates(self) -> None:
        assert "pcz" in LEGAL_GATES

    def test_pcz_legal_gates_set(self) -> None:
        assert LEGAL_GATES["pcz"] == {"rx", "ry", "rz", "cp", "id"}


# ===================================================================
# Gate shape validation
# ===================================================================


class TestGateShapeValidation:
    """Verify qubit and param counts for key gates."""

    def test_rx_requires_one_param(self) -> None:
        with pytest.raises(Exception, match="param"):
            GateOp(gate=NativeGate.RX, qubits=[0], params=[])

    def test_cz_zero_params(self) -> None:
        with pytest.raises(Exception, match="param"):
            GateOp(gate=NativeGate.CZ, qubits=[0, 1], params=[1.0])

    def test_iswap_zero_params(self) -> None:
        with pytest.raises(Exception, match="param"):
            GateOp(gate=NativeGate.ISWAP, qubits=[0, 1], params=[1.0])

    def test_cp_one_param(self) -> None:
        op = GateOp(gate=NativeGate.CP, qubits=[0, 1], params=[3.14])
        assert op.params == [3.14]

    def test_cp_two_params_rejected(self) -> None:
        with pytest.raises(Exception, match="param"):
            GateOp(gate=NativeGate.CP, qubits=[0, 1], params=[1.0, 2.0])

    def test_qubit_out_of_range(self) -> None:
        with pytest.raises(Exception, match="out of range"):
            NativeGateIR(
                target="pcz",
                num_qubits=2,
                gates=[GateOp(gate=NativeGate.CP, qubits=[0, 5], params=[1.0])],
                measurements=[0],
                metadata=_metadata(),
            )


# ===================================================================
# JSON round-trip for each target
# ===================================================================


class TestJsonRoundTrips:
    """JSON serialization preserves IR for every target."""

    def test_cz_round_trip(self) -> None:
        ir = NativeGateIR(
            target="cz",
            num_qubits=2,
            gates=[
                GateOp(gate=NativeGate.RX, qubits=[0], params=[0.5]),
                GateOp(gate=NativeGate.CZ, qubits=[0, 1], params=[]),
            ],
            measurements=[0, 1],
            metadata=_metadata(),
        )
        assert NativeGateIR.from_json(ir.to_json()) == ir

    def test_pcz_round_trip(self) -> None:
        ir = NativeGateIR(
            target="pcz",
            num_qubits=2,
            gates=[
                GateOp(gate=NativeGate.RY, qubits=[0], params=[math.pi / 2]),
                GateOp(gate=NativeGate.CP, qubits=[0, 1], params=[math.pi]),
            ],
            measurements=[0, 1],
            metadata=_metadata(),
        )
        assert NativeGateIR.from_json(ir.to_json()) == ir

    def test_iswap_round_trip(self) -> None:
        ir = NativeGateIR(
            target="iswap",
            num_qubits=2,
            gates=[
                GateOp(gate=NativeGate.RX, qubits=[0], params=[0.5]),
                GateOp(gate=NativeGate.ISWAP, qubits=[0, 1], params=[]),
            ],
            measurements=[0, 1],
            metadata=_metadata(),
        )
        assert NativeGateIR.from_json(ir.to_json()) == ir

    def test_gate_order_preserved(self) -> None:
        ir = NativeGateIR(
            target="pcz",
            num_qubits=3,
            gates=[
                GateOp(gate=NativeGate.RX, qubits=[0], params=[0.1]),
                GateOp(gate=NativeGate.RY, qubits=[1], params=[0.2]),
                GateOp(gate=NativeGate.CP, qubits=[0, 1], params=[0.3]),
                GateOp(gate=NativeGate.RZ, qubits=[2], params=[0.4]),
                GateOp(gate=NativeGate.CP, qubits=[1, 2], params=[0.5]),
            ],
            measurements=[0, 1, 2],
            metadata=_metadata(),
        )
        restored = NativeGateIR.from_json(ir.to_json())
        for orig, rest in zip(ir.gates, restored.gates, strict=True):
            assert orig.gate == rest.gate
            assert orig.qubits == rest.qubits
            for p1, p2 in zip(orig.params, rest.params, strict=True):
                assert math.isclose(p1, p2, rel_tol=1e-12)

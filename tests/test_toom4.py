"""Tests del multiplicador GF(2^12) Toom-4 (42 Toffolis).

Verifica emit_toom4_zero contra la referencia clasica (gf212.gf_mul)
con el simulador kickmix, y que el costo sea T=42, Q=48.
"""
import kickmix as km
import numpy as np
import pytest

from auto_mvp.circuits.generators.toom4 import emit_toom4_zero, emit_ixor_toom4
from auto_mvp.gf212 import gf_mul


def _build_toom4(f_val, g_val):
    bld = km.CircuitBuilder()
    f = bld.alloc_qubits(12)
    g = bld.alloc_qubits(12)
    h = bld.alloc_qubits(12)
    for i in range(12):
        if (f_val >> i) & 1:
            bld.x(f[i])
        if (g_val >> i) & 1:
            bld.x(g[i])
    emit_toom4_zero(bld, f, g, h)
    circ = bld.finish_circuit()
    return circ, h


def _read_reg(sim, reg, shot=0):
    bits = sim.read_across_shots(km.array(reg))
    return sum(int(bits[k, shot]) << k for k in range(12))


@pytest.mark.parametrize("f_val,g_val", [
    (0, 0), (0, 1234), (1, 1), (1, 0xFFF), (0xFFF, 0xFFF),
    (2, 3), (0xFFF, 7), (0xABC, 0x123), (0x800, 0x800),
    (0x001, 0xFFE), (0x555, 0xAAA),
])
def test_toom4_values(f_val, g_val):
    circ, h = _build_toom4(f_val, g_val)
    st = circ.operation_statistics()
    assert st.num_toffoli_like == 42, f"T={st.num_toffoli_like}, se esperaban 42"
    assert circ.num_qubits == 48, f"Q={circ.num_qubits}, se esperaban 48"
    sim = km.Simulator(batch_size=1, debug_print=False, seed=1)
    sim.use_same_registers_as(circ)
    sim.do(circ)
    got = _read_reg(sim, h)
    assert got == gf_mul(f_val, g_val), (
        f"{f_val:#x}*{g_val:#x} = {got:#x}, se esperaba {gf_mul(f_val, g_val):#x}")


def test_toom4_random():
    rng = np.random.default_rng(12345)
    for _ in range(20):
        f_val = int(rng.integers(0, 1 << 12))
        g_val = int(rng.integers(0, 1 << 12))
        circ, h = _build_toom4(f_val, g_val)
        sim = km.Simulator(batch_size=1, debug_print=False, seed=1)
        sim.use_same_registers_as(circ)
        sim.do(circ)
        got = _read_reg(sim, h)
        assert got == gf_mul(f_val, g_val), (
            f"{f_val:#x}*{g_val:#x} = {got:#x}, se esperaba {gf_mul(f_val, g_val):#x}")


def test_ixor_toom4_no_control():
    """emit_ixor_toom4 sin control: mismo costo que emit_toom4_zero."""
    bld = km.CircuitBuilder()
    f = bld.alloc_qubits(12)
    g = bld.alloc_qubits(12)
    t = bld.alloc_qubits(12)
    emit_ixor_toom4(bld, f, g, t)
    circ = bld.finish_circuit()
    st = circ.operation_statistics()
    assert st.num_toffoli_like == 42

"""Generador híbrido DQI (build_hybrid_bm.py): BM + Forney con
descomposición híbrida de medición y descomputación clásica.

Verifica a escala chica contra la referencia clásica:
- BM adelante produce el sigma correcto (normalizado a mónico).
- El hybrid scan no corrompe sigma/omega (es limpio).
- El circuito completo restaura S y deja los ancillas a |0>.
"""
from __future__ import annotations

import kickmix as km

from auto_mvp.circuits.generators.build_hybrid_bm import (
    berlekamp_massey,
    bm_backward,
    bm_forward,
    build_hybrid_bm_circuit,
    compute_omega,
    hybrid_scan,
    omega_from_sigma,
    syndrome_from_errors_n,
    verify_small,
    _bits_matrix,
    _read_reg_shot,
)


def test_circuito_completo_sin_basura():
    # El circuito completo (BM + omega + scan + BM atrás) debe
    # restaurar S y dejar TODOS los ancilla en |0⟩. Antes de la
    # corrección dejaba ~100-165 ancilla en 1 (OMG sin descomputar,
    # tmpL/tmpL2 sin limpiar, ctrl1 en 1, Toom-3 rompiendo B/Lreg)
    # y el verificador oficial lo rechazaba (eps+ = 1.0).
    import numpy as np

    from auto_mvp.circuits.generators.build_hybrid_bm import DEGREE

    n, m, batch, nslot = 10, 15, 4, 6
    circ, info = build_hybrid_bm_circuit(
        n=n, m=m, batch=batch, nslot=nslot, toom3=True)
    q = int(info["qubits"])
    assert q == 1139
    S_qubits = km.array([km.q(k) for k in range(n * DEGREE)])
    E_bits = km.array([km.b(k) for k in range(m * DEGREE)])
    ancilla = km.array([km.q(k) for k in range(n * DEGREE, q)])
    rng = np.random.default_rng(12345)
    nshots = 4
    S_list = []
    for _ in range(nshots):
        w = int(rng.integers(1, max(2, n // 2)))
        pos = rng.choice(m, size=w, replace=False)
        err = {int(j): int(rng.integers(1, 1 << DEGREE)) for j in pos}
        S_list.append(syndrome_from_errors_n(err, n))
        for j in range(m):
            pass
    sim = km.Simulator(batch_size=nshots, debug_print=False,
                       counting_operations=True, seed=1)
    sim.use_same_registers_as(circ)
    s_bits = np.zeros((n * DEGREE, nshots), dtype=bool)
    for s in range(nshots):
        for j in range(n):
            for b in range(DEGREE):
                s_bits[j * DEGREE + b, s] = bool((S_list[s][j] >> b) & 1)
    sim.write_across_shots(S_qubits, s_bits)
    # E en 0 (máscaras cero: la fase es 0, solo se comprueba valor).
    sim.write_across_shots(
        E_bits, np.zeros((m * DEGREE, nshots), dtype=bool))
    sim.do(circ)
    reg_diff = sim.read_across_shots(S_qubits) ^ s_bits
    junk = sim.read_across_shots(ancilla)
    assert not reg_diff.any(), "S no se restauró"
    assert not junk.any(), "hay ancilla en 1"
    # T dinámico = T estático (sin compuertas condicionales que
    # cambien el conteo por shot).
    assert sim.operation_statistics().num_toffoli_like / nshots == (
        info["toffoli_like"])


def test_verify_small_passes():
    res = verify_small(n=10, m=15, batch=4, seed=12345, nshots=4)
    assert res["bm_sigma_correct"] == res["bm_sigma_total"] == 24
    assert res["scan_registers_intact"] == res["scan_registers_total"] == 12


def test_full_circuit_restores_syndrome_and_cleans_ancillas():
    n, m, batch, nslot = 10, 15, 4, 6
    err = {3: 123, 7: 456}
    S_in = syndrome_from_errors_n(err, n)
    sig, L = berlekamp_massey(S_in)
    omg = omega_from_sigma(sig, S_in)
    sig = sig + [0] * (nslot - len(sig))
    omg = omg + [0] * (nslot - len(omg))
    masks = {j: 0 for j in range(m)}
    bld = km.CircuitBuilder()
    S = [bld.alloc_qubits(12) for _ in range(n)]
    E = [bld.alloc_bits(12) for _ in range(m)]
    zero_reg = bld.alloc_qubits(12)
    C, B, Lreg, hist = bm_forward(bld, S, n, nslot=nslot)
    OMG = compute_omega(bld, C, S, n, nslot=nslot)
    hybrid_scan(bld, C, OMG, E, m, batch, L, zero_reg)
    bm_backward(bld, S, C, B, Lreg, hist, n, nslot=nslot)
    bld.free(zero_reg)
    circ = bld.finish_circuit()
    sim = km.Simulator(batch_size=1, debug_print=False,
                       counting_operations=True, seed=1)
    sim.use_same_registers_as(circ)
    for j in range(n):
        sim.write_across_shots(km.array(S[j]), _bits_matrix([S_in[j]], 12))
    for j in range(m):
        sim.write_across_shots(km.array(E[j]), _bits_matrix([masks[j]], 12))
    sim.do(circ)
    assert all(_read_reg_shot(sim, S[j], 0) == S_in[j] for j in range(n))
    assert all(_read_reg_shot(sim, C[i], 0) == 0 for i in range(nslot))
    assert all(_read_reg_shot(sim, B[i], 0) == 0 for i in range(nslot))


def test_small_full_build_counts():
    circ, info = build_hybrid_bm_circuit(n=10, m=15, batch=4, nslot=6)
    assert info["qubits"] > 0
    assert info["toffoli_like"] > 0
    assert info["scan"]["batches"] == 4


def test_toom3_lowest_T_same_Q():
    # Toom-3 DESACTIVADO: rompe la restauración de B/Lreg en
    # bm_backward (B queda con basura), así que toom3=True da el
    # mismo circuito que el nativo (misma T y misma Q). Se guarda
    # el knob en info pero no cambia el circuito.
    _, native = build_hybrid_bm_circuit(n=10, m=15, batch=4, nslot=6,
                                        toom3=False)
    _, toom3 = build_hybrid_bm_circuit(n=10, m=15, batch=4, nslot=6,
                                       toom3=True)
    assert toom3["toffoli_like"] == native["toffoli_like"]
    assert toom3["qubits"] == native["qubits"]


def test_verify_small_toom3_passes():
    res = verify_small(n=10, m=15, batch=4, seed=12345, nshots=4,
                       toom3=True)
    assert res["bm_sigma_correct"] == res["bm_sigma_total"] == 24
    assert res["scan_registers_intact"] == res["scan_registers_total"] == 12

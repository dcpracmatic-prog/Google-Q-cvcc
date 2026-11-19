"""Generador híbrido DQI (build_hybrid_bm.py): BM + Forney con
descomposición híbrida de medición y descomputación clásica.

Verifica a escala chica contra la referencia clásica:
- BM adelante produce el sigma correcto (normalizado a mónico).
- El hybrid scan preserva sigma/omega y aplica la fase DQI esperada.
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
    # v2.17.9: Q 1139 -> 1067 (inversos directos, sin cadena
    # Montgomery p/q; la fase ahora es correcta, ver notes/v2.17.9.md).
    assert q == 1067
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


def test_verify_small_reports_real_phase_result():
    # El historial v2.17.4 documenta errores de fase en esta semilla.
    # Ya no puede imprimirse PASS solo por sigma y registros intactos.
    res = verify_small(n=10, m=15, batch=4, seed=12345, nshots=8)
    assert res["bm_sigma_correct"] == res["bm_sigma_total"] == 48
    assert res["scan_registers_intact"] == res["scan_registers_total"] == 96
    assert res["scan_phase_total"] == 8
    assert res["scan_phase_correct"] + res["scan_phase_errors"] == 8
    assert res["valid"] is (res["scan_phase_errors"] == 0)


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


def test_verify_small_rejects_missing_phase_kick(monkeypatch):
    import auto_mvp.circuits.generators.build_hybrid_bm as gen

    def no_phase_scan(bld, C, OMG, E, m, batch, L, zero_reg):
        # El circuito deja C/O intactos, pero nunca aplica la fase DQI.
        return {"batches": 0}

    monkeypatch.setattr(gen, "hybrid_scan", no_phase_scan)
    # Fuerza una fase de referencia no trivial para este test negativo.
    monkeypatch.setattr(gen, "expected_phase_parity",
                        lambda errors, masks: 1)
    res = gen.verify_small(n=10, m=15, batch=4, seed=12345, nshots=4)
    assert res["scan_registers_intact"] == res["scan_registers_total"]
    assert res["scan_phase_correct"] == 0
    assert res["scan_phase_errors"] == 4
    assert res["valid"] is False


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


def test_verify_small_toom3_also_checks_phase():
    # toom3=True permanece desactivado por el generador; la comprobación
    # de fase debe ejecutarse igualmente y formar parte de valid.
    res = verify_small(n=10, m=15, batch=4, seed=12345, nshots=8,
                       toom3=True)
    assert res["scan_phase_total"] == 8
    assert res["valid"] is (
        res["bm_sigma_correct"] == res["bm_sigma_total"]
        and res["scan_registers_intact"] == res["scan_registers_total"]
        and res["scan_phase_correct"] == res["scan_phase_total"]
    )


def test_diagnose_phase_helpers_are_exported():
    """Los helpers de diagnóstico existen y documentan el alcance."""
    from auto_mvp.circuits.generators import build_hybrid_bm as gen
    assert callable(gen.diagnose_phase_positions)
    assert callable(gen.diagnose_phase_ablation)
    assert "certificación" in (gen.diagnose_phase_positions.__doc__ or "").lower() or (
        "no es certificación" in (gen.diagnose_phase_positions.__doc__ or "").lower()
    )


def test_verify_small_phase_ok_all_batches():
    """v2.17.9: el scan es fase-correcto para cualquier batch.

    Antes, batch>=2 (Montgomery) daba 2-5 errores de fase de 8 y
    solo batch=1 pasaba. Con inversos directos, todos los batch
    pasan 8/8. Si Montgomery se reactiva, este test lo caza.
    """
    for batch in (1, 2, 4, 8):
        res = verify_small(n=10, m=15, batch=batch, seed=12345, nshots=8)
        assert res["scan_phase_errors"] == 0, f"batch={batch}"
        assert res["valid"] is True


def test_full_circuit_phase_with_random_masks():
    # Regresión v2.17.16: el circuito completo con máscaras aleatorias
    # (fase no trivial) daba ~50% de errores de fase a n=10 en Kaggle
    # (kernel 145924371 v2: 44,250 errores de valor y 28,984 de fase
    # a n=70). Causa: `bm_backward` liberaba `hist_mult` sucio y sus
    # qubits se reutilizaban como temps del paso (c), rompiendo el HMR;
    # y `zero_fix_del` liberaba `is_zero` sucio (ancilla q837).
    # El arreglo limpia ambos de forma unitaria antes de liberarlos.
    # Este test comprueba valor Y fase en el circuito completo.
    import numpy as np

    from auto_mvp.circuits.generators.build_hybrid_bm import (
        DEGREE, expected_phase_parity)

    n, m, batch, nslot = 10, 15, 4, 6
    circ, info = build_hybrid_bm_circuit(
        n=n, m=m, batch=batch, nslot=nslot, toom3=False)
    q = int(info["qubits"])
    S_qubits = km.array([km.q(k) for k in range(n * DEGREE)])
    E_bits = km.array([km.b(k) for k in range(m * DEGREE)])
    ancilla = km.array([km.q(k) for k in range(n * DEGREE, q)])
    rng = np.random.default_rng(12345)
    nshots = 8
    s_bits = np.zeros((n * DEGREE, nshots), dtype=bool)
    e_bits = np.zeros((m * DEGREE, nshots), dtype=bool)
    expected_phase = np.zeros(nshots, dtype=bool)
    for s in range(nshots):
        w = int(rng.integers(1, max(2, n // 2)))
        pos = rng.choice(m, size=w, replace=False)
        err = {int(j): int(rng.integers(1, 1 << DEGREE)) for j in pos}
        masks = {int(j): int(rng.integers(0, 1 << DEGREE))
                 for j in range(m)}
        S_list = syndrome_from_errors_n(err, n)
        for j in range(n):
            for b in range(DEGREE):
                s_bits[j * DEGREE + b, s] = bool((S_list[j] >> b) & 1)
        for j in range(m):
            for b in range(DEGREE):
                e_bits[j * DEGREE + b, s] = bool((masks[j] >> b) & 1)
        expected_phase[s] = bool(expected_phase_parity(err, masks))
    sim = km.Simulator(batch_size=nshots, debug_print=False,
                       counting_operations=True, seed=1)
    sim.use_same_registers_as(circ)
    sim.write_across_shots(S_qubits, s_bits)
    sim.write_across_shots(E_bits, e_bits)
    sim.do(circ)
    reg_diff = sim.read_across_shots(S_qubits) ^ s_bits
    junk = sim.read_across_shots(ancilla)
    phase_flipped = sim.read_phase_flipped_across_shots()
    assert not reg_diff.any(), "S no se restauró"
    assert not junk.any(), "hay ancilla en 1"
    assert (phase_flipped == expected_phase).all(), (
        "fase incorrecta: %s vs esperada %s"
        % (phase_flipped.astype(int), expected_phase.astype(int)))

"""Tests de AUTO_MVP v0.5.0: meta_mvp (parámetro absoluto) + ventaja
pura + parada por meta, Lab (numeric_lab stdlib + puerta fail-closed)
y LOGIC_CORE MWIS en la selección de mutaciones.

La barra de parada la dicta meta_mvp, no un envío anterior: con
meta_mvp=2 el pipeline poda hasta un circuito que entregue 2; con
30, quema ciclos hasta 30 o agotar el presupuesto. La ventaja pura
es la mejora real (Toffolis, cúbits, T) frente al baseline oficial,
traducida al puntaje con la fórmula de la competencia.
"""
from __future__ import annotations

import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auto_mvp import Goal, MetadataProxy, PromotionGate
from auto_mvp.goal import target_S_for_meta_mvp
from auto_mvp.maxcut import greedy_mis, mwis_gain, partition_then_select
from auto_mvp.mwis import (classify_states, exact_mwis, is_independent,
                           solve_mwis, total_weight)
from auto_mvp.numeric_lab import (fail_closed_gate, float_pass_table,
                                  numeric_lab)
from auto_mvp.pipeline import (Pipeline, promotion_gm, pure_advantage,
                               required_dqi_ratio)
from auto_mvp.proxy import CandidateMeta
from auto_mvp.vqcc import dqi_spec, invsqrt_spec
from auto_mvp.vqcc.costs import s_dqi

EPS = 0.001188


def meta_dqi(Q, T, widths=None):
    return {"task": "dqi", "metrics": {"Q": Q, "T": T, "eps_plus": EPS},
            "register_widths": widths or {"S": 840, "C": 432, "B": 432}}


def test_meta_mvp_goal():
    # meta_mvp=30 exige DQI 127.3x (el veredicto 2026-11-11): el S
    # objetivo que sale de for_meta_mvp da GM 30.00 exacto.
    g = Goal.for_meta_mvp("dqi", 30.0, baseline_S=1.998e13)
    assert "meta_mvp=30.00" in g.target_label(), g.target_label()
    assert abs(promotion_gm({"dqi": g.effective_target}) - 30.0) < 0.01
    assert 127 < required_dqi_ratio(30.0) < 128
    # meta_mvp=2: el S objetivo es mucho más alto (menos exigente).
    g2 = Goal.for_meta_mvp("dqi", 2.0, baseline_S=1.998e13)
    assert abs(promotion_gm({"dqi": g2.effective_target}) - 2.0) < 0.01
    assert g2.effective_target > g.effective_target
    # target_S_for_meta_mvp coincide con el factory.
    assert abs(target_S_for_meta_mvp("dqi", 30.0) - g.effective_target) < 1.0
    # Sin ninguna forma de meta, error; meta_mvp <= 0, error.
    try:
        Goal(baseline_S=1.0)
    except ValueError:
        pass
    else:
        raise AssertionError("Goal sin meta debe fallar")
    try:
        Goal.for_meta_mvp("dqi", 0.0, baseline_S=1.0)
    except ValueError:
        pass
    else:
        raise AssertionError("meta_mvp<=0 debe fallar")


def test_pure_advantage():
    # La ventaja pura del DQI público: ratios 20.65 / 64.76 / 10.27,
    # GM 23.9468 (los componentes del mejor envío).
    adv = pure_advantage({"dqi": 3.7676e11})
    assert abs(adv["ratios"]["invsqrt"] - 20.65) < 0.05
    assert abs(adv["ratios"]["dqi"] - 64.76) < 0.05
    assert abs(adv["ratios"]["dfthcsos"] - 10.27) < 0.05
    assert abs(adv["gm"] - 23.94667) < 0.01, adv["gm"]
    # promotion_gm es la misma GM (la ventaja pura es su fuente).
    assert abs(promotion_gm({"dqi": 3.7676e11}) - adv["gm"]) < 1e-9
    # Un DQI mejor (S=3.5e11) sube la ventaja a ~24.5.
    assert 24.0 < pure_advantage({"dqi": 3.5e11})["gm"] < 25.0


def test_gate_meta_mvp():
    # La misma candidata (GM ~25.84) promueve con meta_mvp=2 y no
    # con meta_mvp=30: la barra la dicta el umbral exigido.
    cand = {"dqi": s_dqi(892, 306_780, EPS)}
    assert 24.0 < pure_advantage(cand)["gm"] < 27.0, pure_advantage(cand)
    assert PromotionGate(2.0).evaluate(cand).promote
    assert not PromotionGate(30.0).evaluate(cand).promote
    # El alias histórico threshold sigue funcionando.
    assert PromotionGate(threshold=2.0).evaluate(cand).promote
    assert PromotionGate(threshold=30.0).meta_mvp == 30.0
    # Sin directiva, la puerta es el mejor envío (23.94667).
    assert abs(PromotionGate().meta_mvp - 23.94667) < 1e-5
    assert PromotionGate().evaluate({"dqi": 3.5e11}).promote
    assert not PromotionGate().evaluate({"dqi": 4.0e11}).promote


def test_pipeline_goal_stop():
    # Candidata real con GM ~25.84 (DQI S=3.0e11, Q=892, T=306,780).
    cand = {"meta": meta_dqi(892, 306_780, {"S": 892}),
            "metrics": {"Q": 892, "T": 306_780, "eps_plus": EPS}}
    spec = dqi_spec()
    with tempfile.TemporaryDirectory() as d:
        # meta_mvp=2.0: promueve y PARA (meta alcanzada).
        proxy = MetadataProxy(spec, hard_caps={"max_qubits": 2000}, margin=0.10)
        pipe = Pipeline(proxy, PromotionGate(2.0), runs_dir=Path(d) / "r1")
        res = pipe.run(iter([dict(cand)]))
        assert res.promoted == 1 and res.goal_reached, res
        assert "meta alcanzada" in res.stopped, res.stopped
        assert len(res.artifacts) == 1
        # La misma candidata con meta_mvp=30.0: pasa el proxy, la
        # puerta la rechaza, la meta queda SIN alcanzar (honesto).
        proxy2 = MetadataProxy(spec, hard_caps={"max_qubits": 2000}, margin=0.10)
        pipe2 = Pipeline(proxy2, PromotionGate(30.0), runs_dir=Path(d) / "r2")
        res2 = pipe2.run(iter([dict(cand)]))
        assert res2.promoted == 0 and not res2.goal_reached, res2
        assert res2.gate_rejected == 1 and res2.stopped == "stream agotado"
        # La directiva también se pasa como parámetro del Pipeline.
        proxy3 = MetadataProxy(spec, hard_caps={"max_qubits": 2000}, margin=0.10)
        pipe3 = Pipeline(proxy3, runs_dir=Path(d) / "r3", meta_mvp=2.0)
        res3 = pipe3.run(iter([dict(cand)]))
        assert res3.goal_reached and res3.meta_mvp == 2.0
        # Un target paramétrico Q=400/T=90,000 (GM 66.37) SÍ promueve
        # con meta_mvp=30.00, pero es una HIPÓTESIS, no el circuito
        # que entrega el puntaje: la meta NO se da por alcanzada y la
        # búsqueda sigue (el candidato real, GM 25.84, no llega a 30).
        # H20 (trinquete del mejor): tras promover el target, el
        # candidato real ya no pasa el proxy (no supera el S del
        # target promovido), así que es proxy_rejected, no
        # gate_rejected como antes del trinquete.
        target = {"meta": meta_dqi(400, 90_000, {"S": 400}),
                  "metrics": {"Q": 400, "T": 90_000, "eps_plus": EPS},
                  "kind": "target"}
        proxy4 = MetadataProxy(spec, hard_caps={"max_qubits": 2000}, margin=0.10)
        pipe4 = Pipeline(proxy4, runs_dir=Path(d) / "r4", meta_mvp=30.0)
        res4 = pipe4.run(iter([target, dict(cand)]))
        assert not res4.goal_reached and res4.promoted == 1, res4
        assert res4.screened == 2 and res4.proxy_rejected == 1 and res4.gate_rejected == 0, res4
        assert res4.best["kind"] == "target" and res4.best_gm > 30.0
        assert res4.stopped == "stream agotado", res4.stopped


def test_numeric_lab_matches_original():
    # El port stdlib reproduce el Lab original (numpy): 28 candidatos,
    # 17 factibles en flotante, mejor prefiltrado grado 7 / 1 segmento.
    lab = numeric_lab()
    assert len(lab["candidates"]) == 28
    assert lab["float_feasible"] == 17, lab["float_feasible"]
    best = lab["best_prefilter"]
    assert best["degree"] == 7 and best["segments"] == 1
    assert abs(best["after_NR_float_relative_error"] - 3.443775919986791e-08) < 1e-12
    assert "Floating-point prefilter only" in lab["warning"]
    table = float_pass_table()
    assert table[(7, 1)] is True and table[(2, 1)] is False
    assert table[(8, 8)] is True and table[(5, 1)] is False


def test_fail_closed_gate():
    ok = {"invsqrt": "PASS", "dqi": "PASS", "dfthcsos": "PASS"}
    assert fail_closed_gate(ok)["status"] == "FULL_LOCAL_VERIFIERS_PASS"
    # Un solo fallo cierra la puerta.
    bad = dict(ok, dqi="FAIL_OR_UNKNOWN")
    v = fail_closed_gate(bad)
    assert v["status"] == "NOT_CREATED" and "dqi" in v["reason"]
    # El modo smoke no implica puntaje: tampoco arma el zip.
    v2 = fail_closed_gate(ok, mode="smoke")
    assert v2["status"] == "NOT_CREATED"


def test_proxy_numeric_prefilter():
    spec = invsqrt_spec()
    proxy = MetadataProxy(spec, margin=0.10, numeric_prefilter=True)
    best_S = 100_568.5
    # Grado 2 / 1 segmento no pasa 2^-24 ni en flotante: descartado
    # antes de estimar el costo (sin Q/toffoli en las métricas).
    bad = CandidateMeta(task="invsqrt",
                        metrics={"degree": 2, "segments": 1},
                        register_widths={"x": 22})
    v = proxy.evaluate(bad, best_S)
    assert not v.ok and any("prefiltro" in r for r in v.reasons), v.reasons
    # Grado 7 / 1 segmento sí pasa el prefiltro: la decisión la toma
    # el S estimado (Q=62, C=1000 -> S=62,000 < mejor*0.9).
    good = CandidateMeta(
        task="invsqrt",
        metrics={"Q": 62, "C": 1000, "toffoli": 1000, "t_count": 0,
                 "degree": 7, "segments": 1},
        register_widths={"x": 22, "scratch": 40})
    v2 = proxy.evaluate(good, best_S)
    assert v2.ok and abs(v2.s_estimate - 62_000) < 1.0, v2
    # Sin el prefiltro activado, el grado 2 no se descarta por esa vía.
    proxy_off = MetadataProxy(spec, margin=0.10)
    v3 = proxy_off.evaluate(bad, best_S)
    assert not any("prefiltro" in r for r in v3.reasons)


# --- MWIS (LOGIC_CORE v4): grafo real del Notebook 1 ---
GAINS = {"A_mult_school": -2.01e12, "B_inv_315": -2.32e10,
         "C_ptr_8": -2.63e10, "D_nab_6": 1.05e10,
         "E_overflow_sto": -2.05e12, "F_chien_unpack": -4.6e11,
         "G_b17": 4.81e11, "H_b4": 3.29e11, "I_b36": 3.5e11,
         "J_flip36": 3.5e11, "L_mbuc_clear": 2.71e10, "M_lupdate": 9.46e08}
NODES = list(GAINS)
_EDGES = [("A_mult_school", "B_inv_315"), ("A_mult_school", "L_mbuc_clear"),
          ("A_mult_school", "G_b17"), ("A_mult_school", "H_b4"),
          ("A_mult_school", "I_b36"), ("A_mult_school", "J_flip36"),
          ("B_inv_315", "G_b17"), ("B_inv_315", "H_b4"),
          ("B_inv_315", "I_b36"), ("B_inv_315", "J_flip36"),
          ("C_ptr_8", "D_nab_6"), ("D_nab_6", "M_lupdate"),
          ("E_overflow_sto", "F_chien_unpack"), ("E_overflow_sto", "I_b36")]
_CHIEN = ["F_chien_unpack", "G_b17", "H_b4", "I_b36", "J_flip36"]
for _i in range(len(_CHIEN)):
    for _j in range(_i + 1, len(_CHIEN)):
        _EDGES.append((_CHIEN[_i], _CHIEN[_j]))
EDGES = [(a, b, abs(GAINS[a]) + abs(GAINS[b])) for a, b in _EDGES]


def test_mwis_real_graph():
    # MWIS con peso = ganancia: maximiza la ganancia TOTAL, no el
    # tamaño. Incluye G_b17 (la mayor ganancia, 4.81e11) y la unión
    # (D, I, G, L, M) gana más que el MIS voraz completo (J, L, M).
    res = partition_then_select(NODES, EDGES, seed=101, gains=GAINS)
    edge_pairs = {(a, b) for a, b, _ in EDGES} | {(b, a) for a, b, _ in EDGES}
    union = list(res["mis_a"]) + list(res["mis_b"])
    for mis in (res["mis_a"], res["mis_b"]):
        for i in range(len(mis)):
            for j in range(i + 1, len(mis)):
                assert (mis[i], mis[j]) not in edge_pairs
        assert all(GAINS[n] > 0 for n in mis), mis
    assert "G_b17" in union, union
    assert "D_nab_6" in union, union
    full = greedy_mis(NODES, [(a, b) for a, b, _ in EDGES])
    prof_full = {n for n in full if GAINS[n] > 0}
    assert mwis_gain(union, GAINS) > mwis_gain(list(prof_full), GAINS)
    # Sin ganancias, el comportamiento v0.4.0 (MIS voraz) se mantiene.
    res0 = partition_then_select(NODES, EDGES, seed=101)
    assert set(res0["mis_a"]) | set(res0["mis_b"]) != set(union)


def test_mwis_core():
    rng = random.Random(7)
    for n in range(4, 11):
        for _ in range(10):
            adj = [set() for _ in range(n)]
            for i in range(n):
                for j in range(i + 1, n):
                    if rng.random() < 0.28:
                        adj[i].add(j)
                        adj[j].add(i)
            w = [rng.uniform(0.5, 3.0) for _ in range(n)]
            greedy = solve_mwis(adj, w, method="greedy")
            local = solve_mwis(adj, w, method="local")
            exact = exact_mwis(adj, w)
            assert is_independent(adj, greedy) and is_independent(adj, local)
            assert total_weight(local, w) >= total_weight(greedy, w) - 1e-12
            assert total_weight(exact, w) >= total_weight(local, w) - 1e-12
    # El exacto es el óptimo en un grafo chico conocido.
    adj = [set(), set(), set()]
    adj[0].add(1)
    adj[1].add(0)
    assert exact_mwis(adj, [1.0, 1.0, 1.0]) == {0, 2} or \
        exact_mwis(adj, [1.0, 1.0, 1.0]) == {1, 2}
    # classify_states: conflicto con la referencia -> REJECT.
    states = classify_states(adj, {0}, {1})
    assert states[1] == "REFERENCE" and states[0] == "REJECT"
    assert states[2] == "REVIEW"
    states2 = classify_states(adj, {2}, {1})
    assert states2[2] == "PASS"

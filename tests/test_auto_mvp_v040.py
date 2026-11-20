"""Tests de AUTO_MVP v0.4.0: MaxCut (port fiel del C++ de Arturo),
calibración DCP en el pipeline, Observer con régimen derivado
(sin parámetro condition, sin veto) y modo AUTO->PROPOSE->SHADOW.

El grafo de conflictos es el REAL del Notebook 1 (13 nodos, 31
aristas; K_b36_nofix excluido porque el contrato lo rechaza: 12
nodos, 24 aristas). Los pesos son |ganancia_a| + |ganancia_b| con
las dS de la tabla de un solo nodo del notebook.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auto_mvp import (MetadataProxy, Observer, Pipeline, PromotionGate,
                      observe_trials, partition_conflict_graph,
                      partition_then_select)
from auto_mvp.maxcut import cut_value, exact, make_graph, morph
from auto_mvp.vqcc import dqi_spec
from auto_mvp.vqcc.costs import s_dqi
from auto_mvp.vqcc.verify import LocalVerifier

EPS = 0.001188

# Grafo real del Notebook 1 (celda 7). Ganancias dS (S_BASE 3.714e12).
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
assert len(NODES) == 12 and len(EDGES) == 24


def meta_dqi(Q, T, widths=None):
    return {"task": "dqi", "metrics": {"Q": Q, "T": T, "eps_plus": EPS},
            "register_widths": widths or {"S": 840, "C": 432, "B": 432}}


def test_maxcut_cpp_reference():
    src = Path(__file__).resolve().parents[1] / "examples" / "maxcut_reference.cpp"
    assert src.exists()
    with tempfile.TemporaryDirectory() as d:
        exe = str(Path(d) / "maxcut")
        r = subprocess.run(["g++", "-O2", "-o", exe, str(src)],
                           capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, r.stderr[-500:]
        out = subprocess.run([exe], capture_output=True, text=True, timeout=120)
        assert out.returncode == 0
        assert "certificate_exact=PASS" in out.stdout
        assert "exact_best=76.3397044423" in out.stdout, out.stdout
        assert "edges=100" in out.stdout


def test_maxcut_port():
    # El exacto coincide con el corte ingenuo en la mejor asignación.
    for seed in (101, 7, 42):
        w = make_graph(16, seed=seed)
        best_e, xe = exact(w)
        assert abs(best_e - cut_value(w, xe)) < 1e-9
        best_m, xm, evals = morph(w, seed=seed)
        assert abs(best_e - best_m) < 1e-9, (seed, best_e, best_m)
        assert evals < (1 << 16)  # el heurístico evalúa mucho menos
    # n=12: morph == exact en varios grafos.
    for seed in (1, 2, 3):
        w = make_graph(12, seed=seed)
        assert abs(exact(w)[0] - morph(w, seed=seed)[0]) < 1e-9


def test_maxcut_partition_real_graph():
    part = partition_conflict_graph(NODES, EDGES, seed=101)
    assert part.certificate == "EXACT", part
    assert part.gap < 1e-9
    assert set(part.side_a) | set(part.side_b) == set(NODES)
    assert not (set(part.side_a) & set(part.side_b))
    assert 0 < part.cut_weight <= part.total_weight
    # MIS por lado: sin aristas internas. Y la partición rinde: los dos
    # MIS juntos tienen MÁS nodos rentables (4: D, J, L, M) que el MIS
    # voraz del grafo completo (3: J, L, M) — D_nab_6 solo aparece
    # gracias a la partición.
    res = partition_then_select(NODES, EDGES, seed=101)
    edge_pairs = {(a, b) for a, b, _ in EDGES} | {(b, a) for a, b, _ in EDGES}
    for mis in (res["mis_a"], res["mis_b"]):
        assert mis, "un lado no puede quedar vacío"
        for i in range(len(mis)):
            for j in range(i + 1, len(mis)):
                assert (mis[i], mis[j]) not in edge_pairs
    from auto_mvp.maxcut import greedy_mis
    full = greedy_mis(NODES, [(a, b) for a, b, _ in EDGES])
    prof = lambda ms: {n for n in ms if GAINS[n] > 0}
    assert prof(res["mis_a"]) | prof(res["mis_b"]) >= prof(full)
    assert len(prof(res["mis_a"]) | prof(res["mis_b"])) > len(prof(full))
    assert "D_nab_6" in res["mis_a"] or "D_nab_6" in res["mis_b"]


def _trial(S, passed=True, veto=False, kind="candidate"):
    return {"S": S, "passed": passed, "accepted": False,
            "integrity_veto": veto, "kind": kind, "compile_failed": False}


def test_observer_derived_regime():
    stable = [_trial(3.714e12 - i * 1e10) for i in range(10)]
    obs = observe_trials(stable)
    assert obs["regime"] == "ESTABLE", obs
    # La trampa de v0.7: un campo "condition" extra NO cambia el régimen.
    trapped = [dict(t, condition="CONFLICT") for t in stable]
    assert observe_trials(trapped)["regime"] == obs["regime"]
    assert observe_trials(trapped) == obs
    # 7/10 vetos -> CONFLICTO (derivado de los datos).
    vetoed = [_trial(3.7e12, veto=True) for _ in range(7)] + [_trial(3.7e12) for _ in range(3)]
    assert observe_trials(vetoed)["regime"] == "CONFLICTO"
    # Solo 3/10 usables -> INSUFICIENTE. Los 7 no usables son targets
    # sintéticos cribados (no fallos reales: no cuentan en conflict).
    few = [_trial(3.7e12) for _ in range(3)] + [
        _trial(None, passed=False, kind="target") for _ in range(7)]
    assert observe_trials(few)["regime"] == "INSUFICIENTE", observe_trials(few)
    # Sin trials no se inventa un régimen.
    assert observe_trials([])["regime"] == "SIN_DATOS"
    # El Observer escribe su bitácora con gobernanza desactivada.
    with tempfile.TemporaryDirectory() as d:
        ob = Observer(d)
        o = ob.observe(stable, 10)
        assert o["governance"] == {"enabled": False, "veto": False,
                                   "decision": "OBSERVE_ONLY"}
        assert (Path(d) / "observations.jsonl").exists()
        rows = [json.loads(l) for l in (Path(d) / "observations.jsonl").read_text().splitlines()]
        assert all(r["governance"]["decision"] == "OBSERVE_ONLY" for r in rows)


def test_pipeline_dcp_calibration():
    # La sonda varía alrededor de la base BM+Forney (3.714e12): el
    # baseline del spec ES esa base (regla v0.2.1: la sonda debe
    # parecerse a la carga). Con el baseline del ensamble (1.998e13)
    # la sonda quedaría a 82% y el margen caparía en 0.25.
    from dataclasses import replace as _replace
    spec = _replace(dqi_spec(), baseline_S=3.714e12)
    verifier = LocalVerifier(spec)
    probe = [
        {"mutation": "base", "metrics": {"Q": 1414, "T": 1_511_522, "eps_plus": EPS}},
        {"mutation": "b17", "metrics": {"Q": 1414, "T": 1_315_731, "eps_plus": EPS}},
        {"mutation": "mis", "metrics": {"Q": 1412, "T": 1_304_706, "eps_plus": EPS}},
    ]
    proxy = MetadataProxy(spec, hard_caps={"max_qubits": 2000}, margin=0.10)
    with tempfile.TemporaryDirectory() as d:
        pipe = Pipeline(proxy, PromotionGate(30.0), runs_dir=Path(d) / "runs",
                        probe=probe, verifier=verifier)
        # El margen ya no es el 0.10 a mano: es el calibrado (~0.139).
        assert 0.12 < pipe.proxy.margin < 0.15, pipe.proxy.margin
        assert pipe.calibration is not None
        assert pipe.max_trials_default == pipe.calibration.max_trials
        # Micro-mejora del 12% contra el mejor ENVÍO (DQI público
        # 3.7676e11): con margen 0.10 pasaría el proxy, con el
        # calibrado (~0.138) no. (La sonda calibra alrededor de su
        # base 3.714e12; el proxy compara contra el mejor envío. El
        # margen es el ruido de la sonda, no la distancia a la base.)
        cand12 = {"meta": meta_dqi(892, 339_000,
                                    {"S": 840, "C": 26, "B": 26}),
                  "metrics": {"Q": 892, "T": 339_000, "eps_plus": EPS},
                  "kind": "candidate", "name": "micro12"}
        assert abs(s_dqi(892, 339_000, EPS) / 3.7676e11 - 0.88) < 0.01
        res = pipe.run(iter([cand12]))
        assert res.proxy_rejected == 1, res
        assert res.screened == 1
        # Sin calibrar, el mismo candidato pasa el proxy (la puerta lo
        # rechaza después: GM ~5.9, no es el proxy quien lo para).
        proxy2 = MetadataProxy(spec, hard_caps={"max_qubits": 2000}, margin=0.10)
        pipe2 = Pipeline(proxy2, PromotionGate(30.0), runs_dir=Path(d) / "runs2")
        res2 = pipe2.run(iter([cand12]))
        assert res2.proxy_rejected == 0 and res2.gate_rejected == 1, res2


def test_pipeline_mode_drop_and_observer_neutral():
    spec = dqi_spec()
    # Modo: 4 promociones, compilación siempre FAIL -> tras 3 fallos
    # baja a PROPOSE (la 4a se guarda sin compilar).
    calls = {"n": 0}

    def failing_compile(record):
        calls["n"] += 1
        return {"official_pass": False, "S_measured": 1.0e10}

    # H20 (trinquete del mejor): el proxy compara cada candidato contra
    # el mejor encontrado en la corrida, no contra el mejor inicial.
    # Por eso los 4 targets deben ser estrictamente mejores uno que
    # otro (cada T >10% menor que el anterior, con el margen 0.10):
    # 4 targets idénticos ya no promueven 4 veces (el 2º-4º empatan
    # con el mejor y el proxy los rechaza por margen).
    targets = [
        {"meta": meta_dqi(400, t), "metrics": {"Q": 400, "T": t,
         "eps_plus": EPS}, "kind": "target", "name": f"Q400-T{t}"}
        for t in (90_000, 75_000, 60_000, 45_000)
    ]
    with tempfile.TemporaryDirectory() as d:
        proxy = MetadataProxy(spec, hard_caps={"max_qubits": 2000}, margin=0.10)
        pipe = Pipeline(proxy, PromotionGate(30.0), runs_dir=Path(d) / "runs",
                        compile_fn=failing_compile)
        res = pipe.run(iter(targets))
        assert res.promoted == 4, res
        assert calls["n"] == 3, calls  # la 4a ya no compila (PROPOSE)
        assert res.mode == "propose", res.mode
        assert len(res.mode_transitions) == 1
        assert res.mode_transitions[0]["from"] == "auto"
        assert res.mode_transitions[0]["to"] == "propose"
        assert len(res.artifacts) == 4
    # Observer neutro: mismo flujo con y sin observer da lo mismo.
    with tempfile.TemporaryDirectory() as d:
        def stream():
            for _ in range(3):
                yield {"meta": meta_dqi(1412, 1_304_706),
                       "metrics": {"Q": 1412, "T": 1_304_706, "eps_plus": EPS},
                       "kind": "candidate", "name": "MIS"}
            yield dict(targets[0])
        p1 = Pipeline(MetadataProxy(spec, hard_caps={"max_qubits": 2000}, margin=0.10),
                      PromotionGate(30.0), runs_dir=Path(d) / "r1")
        r1 = p1.run(stream())
        ob = Observer(Path(d) / "r2")
        p2 = Pipeline(MetadataProxy(spec, hard_caps={"max_qubits": 2000}, margin=0.10),
                      PromotionGate(30.0), runs_dir=Path(d) / "r2",
                      observer=ob, observe_every=2)
        r2 = p2.run(stream())
        # Mismo flujo con y sin observer: mismos números (las rutas
        # difieren porque cada corrida tiene su propio runs_dir).
        assert (r1.screened, r1.promoted, len(r1.artifacts)) == \
               (r2.screened, r2.promoted, len(r2.artifacts))
        assert [Path(a).name for a in r1.artifacts] == \
               [Path(a).name for a in r2.artifacts]
        assert r2.last_observation is not None
        assert r2.last_observation["governance"]["decision"] == "OBSERVE_ONLY"
        assert (Path(d) / "r2" / "observations.jsonl").exists()


def test_pipeline_observer_regime_drops_mode():
    spec = dqi_spec()
    # 7 módulos reales que rompen el contrato (eps+ > 1/16) de 10:
    # el Observer deriva CONFLICTO y el lazo baja un escalón.
    bad = {"meta": {"task": "dqi", "metrics": {"Q": 1414, "T": 1_511_522,
             "eps_plus": 0.20}, "register_widths": {"S": 840, "C": 432, "B": 432}},
           "metrics": {"Q": 1414, "T": 1_511_522, "eps_plus": 0.20},
           "kind": "candidate", "name": "bad"}
    good = {"meta": meta_dqi(1412, 1_304_706),
            "metrics": {"Q": 1412, "T": 1_304_706, "eps_plus": EPS},
            "kind": "candidate", "name": "MIS"}
    with tempfile.TemporaryDirectory() as d:
        ob = Observer(Path(d) / "runs")
        pipe = Pipeline(MetadataProxy(spec, hard_caps={"max_qubits": 2000}, margin=0.10),
                        PromotionGate(30.0), runs_dir=Path(d) / "runs",
                        observer=ob, observe_every=3)
        stream = [dict(bad) for _ in range(7)] + [dict(good) for _ in range(3)]
        res = pipe.run(iter(stream))
        assert res.last_observation is not None
        assert res.last_observation["regime"] == "CONFLICTO", res.last_observation
        assert res.mode in ("propose", "shadow"), res.mode
        assert len(res.mode_transitions) >= 1
        assert any("observer" in t["reason"] for t in res.mode_transitions)


if __name__ == "__main__":
    test_maxcut_cpp_reference()
    print("maxcut cpp ok")
    test_maxcut_port()
    print("maxcut port ok")
    test_maxcut_partition_real_graph()
    print("maxcut partition ok")
    test_observer_derived_regime()
    print("observer ok")
    test_pipeline_dcp_calibration()
    print("dcp calibration ok")
    test_pipeline_mode_drop_and_observer_neutral()
    print("mode + observer neutral ok")
    test_pipeline_observer_regime_drops_mode()
    print("observer regime drop ok")
    print("ALL v0.4.0 TESTS PASSED")

"""Tests de AUTO_MVP v0.3.0: integridad, CVV, checkpoint, meta, proxy
y orquestador de extremo a extremo (sintético, solo stdlib).

Los números DQI son los del Notebook 1 (BM+Forney base S=3.714e12,
mejora MIS S=3.197e12) y la regresión con forma de paso 51 (mejor S
proyectado, sigma roto).
"""
from __future__ import annotations

import json
import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auto_mvp import (
    AutoMvp, CandidateMeta, Checkpoint, CircuitConstructionGuard, CvvChain,
    CvvRecord, Goal, IntegrityEvidence, IntegrityFilter, IntegrityViolation,
    MetadataProxy, canonical_hash, calibrate_proxy,
)
from auto_mvp.vqcc import dqi_spec
from auto_mvp.vqcc.costs import s_dqi
from auto_mvp.vqcc.verify import LocalVerifier

EPS = 0.001188
BASE_S = 3.714e12  # BM+Forney base, Q=1414 T=1511522
MIS_S = s_dqi(1412, 1_304_706, EPS)  # ~3.197e12


def good_evidence() -> dict:
    sigma = [2314, 1897, 1246, 3162]
    return {
        "kind": "circuit",
        "sigma": sigma,
        "sigma_ref_hash": canonical_hash(sigma),
        "c_restored": 180, "b_restored": 180, "total_coef": 180,
        "dreg_zero": True, "alpha_zero": True,
        "temporaries_zero": 0, "temporaries_total": 0,
        "allowed_dirty": {},
        "shots": 5, "verified_by": "gu_trace",
    }


def test_cvv_chain_and_tamper():
    chain = CvvChain()
    r1 = chain.append(CvvRecord(
        cycle=1, phase="INGEST_BASELINE", target_goal="+50%",
        algebraic_state_hash="a" * 64, score=1.99836e13, logic_verified=True,
        status="LOCKED_BASE", verified_by="official",
        logic_integrity="PASSED_STRICT"))
    assert r1.prev_hash == "0" * 64
    assert len(r1.checksum) == 64
    r2 = chain.append(CvvRecord(
        cycle=2, phase="AUTO_OPTIMIZE", target_goal="+50%",
        algebraic_state_hash="b" * 64, score=1.2e13, logic_verified=True,
        status="CERTIFIED", delta_improvement="-39.9%",
        best_found_so_far=True, verified_by="official"))
    assert r2.prev_hash == r1.checksum
    ok, bad = chain.verify()
    assert ok and bad is None
    # Manipular un récord rompe la cadena en ese índice.
    chain.records[0].score = 1.0
    ok, bad = chain.verify()
    assert not ok and bad == 0
    # Serialización JSONL: ida y vuelta conserva la cadena.
    chain.records[0].score = 1.99836e13
    ok, _ = chain.verify()
    assert ok
    chain2 = CvvChain.from_jsonl(chain.to_jsonl())
    ok, _ = chain2.verify()
    assert ok and len(chain2) == 2


def test_checkpoint_atomic_and_history():
    with tempfile.TemporaryDirectory() as d:
        cp = Checkpoint(d)
        assert cp.load() is None
        snap = cp.save({"task": "dqi", "S": 3.197e12, "verified_by": "official"})
        assert snap.exists()
        assert cp.load()["S"] == 3.197e12
        # Guardar otro mejor: best.json cambia, el historial crece.
        cp.save({"task": "dqi", "S": 3.1e12, "verified_by": "official"})
        assert cp.load()["S"] == 3.1e12
        assert len(cp.load_history()) == 2
        # best.json siempre es JSON válido (escritura atómica).
        json.loads(Path(d, "best.json").read_text())


def test_integrity_filter():
    f = IntegrityFilter()
    ok, reasons = f.check(good_evidence())
    assert ok and reasons == []
    # Excepción documentada (tmpD2 del paso 51 v3) pasa con motivo.
    ev = good_evidence()
    ev["temporaries_zero"] = 0
    ev["temporaries_total"] = 1
    ev["allowed_dirty"] = {"tmpD2": "ciclo de limpiezas paso 51, +840q"}
    ok, _ = f.check(ev)
    assert ok
    # Temporal sucio sin documentar: falla.
    ev["allowed_dirty"] = {}
    ok, reasons = f.check(ev)
    assert not ok and any("sin documentar" in r for r in reasons)
    # Sigma distinto de la referencia: la forma del paso 51.
    ev = good_evidence()
    ev["sigma"] = [9999, 1897, 1246, 3162]
    ok, reasons = f.check(ev)
    assert not ok and any("SIGMA_DIVERGENCE" in r for r in reasons)
    # C restaurado incompleto: falla.
    ev = good_evidence()
    ev["c_restored"] = 179
    ok, _ = f.check(ev)
    assert not ok
    # Sin evidencia: falla. Proyección: nunca pasa este filtro.
    ok, _ = f.check(None)
    assert not ok
    ok, _ = f.check({"kind": "projection"})
    assert not ok
    # require() lanza con los motivos.
    try:
        f.require({"kind": "projection"})
    except IntegrityViolation as e:
        assert e.reasons
    else:
        raise AssertionError("require debió lanzar")


def test_construction_guard():
    guard = CircuitConstructionGuard()

    @guard
    def build_ok():
        return "circuito", good_evidence()

    artifact, _ = build_ok()
    assert artifact == "circuito"

    @guard
    def build_roto():
        ev = good_evidence()
        ev["sigma"] = [1, 2, 3, 4]
        return "circuito-roto", ev

    try:
        build_roto()
    except IntegrityViolation as e:
        assert any("SIGMA_DIVERGENCE" in r for r in e.reasons)
    else:
        raise AssertionError("el guardia debió rechazar el circuito roto")


def test_goal_stops():
    g = Goal(baseline_S=100.0, improvement_pct=50.0, base_trials=4,
             max_trials=10, growth_per_hit=2, patience=2)
    assert abs(g.effective_target - 100.0 / 1.5) < 1e-9
    from auto_mvp.goal import GoalTracker
    tr = GoalTracker(g)
    stop, _ = tr.should_stop()
    assert not stop
    tr.observe(90.0, True)  # mejora: presupuesto crece 4 -> 6
    assert tr.state.budget == 6
    assert tr.state.best_S == 90.0
    tr.observe(95.0, False)
    tr.observe(95.0, False)  # paciencia 2 agotada
    stop, reason = tr.should_stop()
    assert stop and "paciencia" in reason
    # Meta alcanzada.
    tr2 = GoalTracker(g)
    tr2.observe(60.0, True)
    stop, reason = tr2.should_stop()
    assert stop and "meta alcanzada" in reason


def test_proxy_hard_caps_and_calibration():
    spec = dqi_spec()
    proxy = MetadataProxy(spec, hard_caps={"max_qubits": 2000}, margin=0.10)
    best_S = BASE_S
    # Variante que viola el tope: rechazada sin construir nada.
    meta = CandidateMeta(task="dqi", metrics={"Q": 1412, "T": 1_304_706, "eps_plus": EPS},
                         register_widths={"S": 840, "C": 432, "B": 432, "extra": 500})
    v = proxy.evaluate(meta, best_S)
    assert not v.ok and any("tope" in r for r in v.reasons)
    # Variante válida con mejor S estimado: pasa.
    meta2 = CandidateMeta(task="dqi", metrics={"Q": 1412, "T": 1_304_706, "eps_plus": EPS},
                          register_widths={"S": 840, "C": 432, "B": 432})
    v2 = proxy.evaluate(meta2, best_S)
    assert v2.ok and abs(v2.s_estimate - MIS_S) < 1.0
    # eps+ fuera de contrato: rechazada por el validador.
    meta3 = CandidateMeta(task="dqi", metrics={"Q": 1412, "T": 1_304_706, "eps_plus": 0.2},
                          register_widths={"S": 840})
    assert not proxy.evaluate(meta3, best_S).ok
    # Calibración: margen p95 acotado a 0.25.
    assert calibrate_proxy([(100.0, 100.0), (110.0, 100.0), (90.0, 100.0)]) <= 0.25
    assert calibrate_proxy([]) == 0.25
    # Ranking: la que pasa va primero.
    ranked = proxy.rank([meta, meta2], best_S)
    assert ranked[0][0] is meta2 and ranked[0][1].ok


class ScriptedMutator:
    def __init__(self, candidates):
        self.candidates = list(candidates)
        self.i = 0

    def propose(self, spec, best, evidence):
        if self.i < len(self.candidates):
            c = self.candidates[self.i]
        else:
            c = {"mutation": "peor", "metrics": {"Q": 5000, "T": 5_000_000,
                                                 "eps_plus": EPS}, "params": {}}
        self.i += 1
        return c


class CountingVerifier(LocalVerifier):
    def __init__(self, spec):
        super().__init__(spec)
        self.calls = 0
        self.names: list[str] = []

    def verify(self, candidate):
        self.calls += 1
        self.names.append(str(candidate.get("mutation", "?")))
        return super().verify(candidate)


def test_orchestrator_end_to_end():
    from dataclasses import replace as _replace
    spec = _replace(dqi_spec(), baseline_S=BASE_S)
    mis = {"mutation": "L+D+G_b17", "metrics": {"Q": 1412, "T": 1_304_706, "eps_plus": EPS},
           "params": {"combo": "L+D+G_b17"}, "integrity": good_evidence()}
    # Regresión con forma de paso 51: mejor S, sigma roto.
    reg = {"mutation": "paso51-roto", "metrics": {"Q": 1400, "T": 1_200_000, "eps_plus": EPS},
           "params": {"combo": "roto"}}
    ev_bad = good_evidence()
    ev_bad["sigma"] = [9999, 1897, 1246, 3162]
    reg["integrity"] = ev_bad
    assert s_dqi(1400, 1_200_000, EPS) < MIS_S  # mejor S, lógica rota
    # Variante que el proxy rechaza por tope de qubits (sin construir).
    big = {"mutation": "demasiado-grande",
           "metrics": {"Q": 1412, "T": 1_304_706, "eps_plus": EPS},
           "params": {},
           "meta": {"task": "dqi", "metrics": {"Q": 1412, "T": 1_304_706, "eps_plus": EPS},
                    "register_widths": {"S": 840, "C": 432, "B": 432, "extra": 500}}}
    # Aceptación verificada oficial con integridad válida -> checkpoint.
    off = {"mutation": "oficial", "metrics": {"Q": 1400, "T": 1_100_000, "eps_plus": EPS},
           "params": {"combo": "oficial"}, "integrity": good_evidence(),
           "verified_by": "official", "S": s_dqi(1400, 1_100_000, EPS)}
    assert off["S"] < MIS_S
    verifier = CountingVerifier(spec)
    proxy = MetadataProxy(spec, hard_caps={"max_qubits": 2000}, margin=0.10)
    goal = Goal(baseline_S=BASE_S, improvement_pct=50.0, base_trials=10,
                max_trials=10, patience=5)
    with tempfile.TemporaryDirectory() as d:
        mvp = AutoMvp(spec, ScriptedMutator([mis, reg, big, off]),
                      goal, verifier=verifier, proxy=proxy, workdir=d)
        res = mvp.run()
        # El checkpoint se lee DENTRO del directorio temporal (se borra al salir).
        assert res.checkpoint_path is not None
        saved = json.loads(Path(res.checkpoint_path).read_text())
        assert saved["S"] == off["S"] and saved["verified_by"] == "official"
    assert res.accepted >= 2, res
    assert res.integrity_vetoes == 1, res
    assert res.proxy_rejected == 1, res
    # El verificador NUNCA se llamó para la variante del proxy.
    assert "demasiado-grande" not in verifier.names, verifier.names
    assert verifier.calls == 8, verifier.calls  # mis, reg, off + 5 peor
    # El mejor final es el oficial, y el checkpoint lo guarda.
    assert abs(res.best_S - off["S"]) < 1.0, res
    assert abs(res.best_verified_S - off["S"]) < 1.0, res
    # La cadena CVV: baseline + 2 aceptados + 1 veto + convergencia.
    phases = [r.phase for r in mvp.cvv.records]
    assert phases[0] == "INGEST_BASELINE"
    assert "REJECTED_REGRESSION" in phases
    assert phases[-1] == "MVP_CONVERGENCE"
    veto = [r for r in mvp.cvv.records if r.phase == "REJECTED_REGRESSION"][0]
    assert veto.veto_reason and "SIGMA_DIVERGENCE" in veto.veto_reason
    ok, bad = mvp.cvv.verify()
    assert ok and bad is None
    # La regresión con mejor S NO movió el mejor.
    assert res.best_S < MIS_S and res.best_S == off["S"]


if __name__ == "__main__":
    test_cvv_chain_and_tamper()
    print("cvv ok")
    test_checkpoint_atomic_and_history()
    print("checkpoint ok")
    test_integrity_filter()
    print("integrity ok")
    test_construction_guard()
    print("guard ok")
    test_goal_stops()
    print("goal ok")
    test_proxy_hard_caps_and_calibration()
    print("proxy ok")
    test_orchestrator_end_to_end()
    print("orchestrator ok")
    print("ALL v0.3.0 TESTS PASSED")

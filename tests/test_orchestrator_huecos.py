"""Huecos H1, H2, H7, H14-H18, H20, H23-H25 de la auditoría MORPH/JSON/
orquestador: correcciones solo en auto_mvp/orchestrator.py.

Números medidos, sin verificador oficial real (las rutas oficiales se
prueban con monkeypatch o con ruta inexistente, que falla rápido).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_mvp.json_directive import Directive
from auto_mvp.morph_tunnel import RULES
from auto_mvp.orchestrator import (AdaptiveOrchestrator, StepOrderError)
from auto_mvp.pipeline import Pipeline, PromotionGate
from auto_mvp.proxy import MetadataProxy
from auto_mvp.qualtran_bridge import Block, CallGraph
from auto_mvp.step_plan import StepPlan
from auto_mvp.vqcc import dqi_spec
from auto_mvp.vqcc.verify import CircuitVerifyResult


def _pipe(tmp: Path, meta_mvp: float = 30.0, **kw) -> Pipeline:
    return Pipeline(
        proxy=MetadataProxy(spec=dqi_spec(), margin=0.10),
        gate=PromotionGate(meta_mvp),
        runs_dir=tmp / "runs",
        time_budget_seconds=None,
        **kw,
    )


def _bm_graph() -> CallGraph:
    root = Block(name="dqi-bm-forney", kind="dqi", t_count=1_511_522,
                 qubits=1_414, children=[
                     (Block(name="bm_forward", kind="bm_forward"), 1),
                     (Block(name="omega", kind="omega"), 1),
                     (Block(name="chien", kind="chien"), 1),
                     (Block(name="bm_backward", kind="bm_backward"), 1)])
    return CallGraph(root=root, source="cost_model")


def _bm_candidate(**extra) -> dict:
    cand = {
        "name": "bm-forney", "kind": "candidate",
        "meta": {"task": "dqi", "metrics": {"Q": 1_414, "T": 1_511_522,
                                            "eps_plus": 0.001188}},
        "metrics": {"Q": 1_414, "T": 1_511_522, "eps_plus": 0.001188},
        "call_graph": _bm_graph().to_dict(),
    }
    cand.update(extra)
    return cand


def _steps(*names: str) -> StepPlan:
    return StepPlan(steps=[{"step": s, "method": "", "params": {}}
                           for s in names])


def _probe_json() -> str:
    # Sonda realista: dos candidatos pegados al baseline DQI
    # (1.99836e13): rel 0.0001 y 0.0095, así el margen calibrado
    # queda ~0.01 y no cierra el proxy al candidato BM.
    probe = [
        {"name": "base", "task": "dqi",
         "metrics": {"Q": 1_899, "T": 738_000, "eps_plus": 0.0424}},
        {"name": "mut", "task": "dqi",
         "metrics": {"Q": 1_899, "T": 745_000, "eps_plus": 0.0424}},
    ]
    return json.dumps(probe)


# --- H1: la directiva tunnel guarda bloque Y regla ---

def test_h1_tunnel_guarda_bloque_y_regla(tmp_path):
    orch = AdaptiveOrchestrator(_pipe(tmp_path), StepPlan())
    assert orch.apply_directive("tunela chien con montgomery-b17")
    assert orch.attack_block == "chien"
    assert orch.attack_rule == "montgomery-b17"
    # Sin regla, la regla queda en None (no basura del intento anterior).
    assert orch.apply_directive("ataca unextract")
    assert orch.attack_block == "unextract"
    assert orch.attack_rule is None


# --- H7: el paso tunnel recibe block y rule ---

def test_h7_tunnel_recibe_bloque_y_regla(tmp_path):
    pipe = _pipe(tmp_path, meta_mvp=30.0)
    pipe.best_S = {"dqi": 3.714e12}
    orch = AdaptiveOrchestrator(pipe, _steps(
        "tunnel", "proxy", "gate", "compile", "observe"))
    orch.apply_directive("tunela chien con chien-montgomery-b17")
    calls: dict = {}
    orig = pipe.tunnel_candidate

    def spy(candidate, method="greedy", block=None, rule=None):
        calls.update(method=method, block=block, rule=rule)
        return orig(candidate, method=method, block=block, rule=rule)

    pipe.tunnel_candidate = spy
    res = orch.run([_bm_candidate()], directives=["sube la meta a 2"])
    assert res.promoted == 1 and res.tunneled == 1
    assert calls == {"method": "greedy", "block": "chien",
                     "rule": "chien-montgomery-b17"}
    t = [x for x in res.step_log if x["step"] == "tunnel"][0]
    assert t["tunnel_filter"] == {"block": "chien",
                                  "rule": "chien-montgomery-b17"}
    assert t["moves"] == 1  # el filtro dejó pasar justo esa regla


def test_h7_sin_soporte_en_pipeline_queda_registrado(tmp_path):
    # Un Pipeline sin block/rule (firma vieja) no recibe el filtro:
    # no se inventa que se aplicó, queda en el trace. Se simula con
    # un envoltorio que solo acepta (candidate, method).
    pipe = _pipe(tmp_path, meta_mvp=30.0)
    pipe.best_S = {"dqi": 3.714e12}
    orch = AdaptiveOrchestrator(pipe, _steps("tunnel", "proxy", "gate",
                                            "compile", "observe"))
    orch.apply_directive("tunela chien con chien-montgomery-b17")
    orig = pipe.tunnel_candidate

    def legacy(candidate, method="greedy"):
        return orig(candidate, method=method)

    pipe.tunnel_candidate = legacy
    res = orch.run([_bm_candidate()], directives=["sube la meta a 2"])
    assert res.promoted == 1  # sin filtro, el túnel aplica todas
    t = [x for x in res.step_log if x["step"] == "tunnel"][0]
    assert "sin aplicar" in str(t["tunnel_filter"])


# --- H2: el presupuesto aplicado antes de run() sobrevive ---

def test_h2_presupuesto_antes_de_run_se_aplica(tmp_path):
    pipe = _pipe(tmp_path, meta_mvp=30.0)
    orch = AdaptiveOrchestrator(pipe, StepPlan())
    assert orch.apply_directive("presupuesto 1 intentos")
    res = orch.run([_bm_candidate(), _bm_candidate(), _bm_candidate()])
    assert res.screened == 1  # antes del arreglo corría los 3
    assert res.stopped == "límite de iteraciones"


def test_h2_presupuesto_en_run_sigue_funcionando(tmp_path):
    orch = AdaptiveOrchestrator(_pipe(tmp_path), StepPlan())
    res = orch.run([_bm_candidate()] * 3,
                   directives=["presupuesto 2 intentos"])
    assert res.screened == 2


# --- H14: verify oficial con veto ---

def _promoting_plan():
    return _steps("tunnel", "proxy", "gate", "verify", "compile", "observe")


def test_h14_artefacto_inexistente_veta(tmp_path):
    # Ruta de circuito que no existe: el verificador oficial real
    # falla rápido (sin subproceso) y el candidato no se compila.
    pipe = _pipe(tmp_path, meta_mvp=30.0)
    pipe.best_S = {"dqi": 3.714e12}
    orch = AdaptiveOrchestrator(pipe, _promoting_plan())
    cand = _bm_candidate(circuit_path="/no/existe/circuito.kmb")
    res = orch.run([cand], directives=["sube la meta a 2"])
    assert res.promoted == 0 and res.artifacts == []
    v = [t for t in res.step_log if t["step"] == "verify"][0]
    assert v["ok"] is False and v["veto"] is True
    assert v["verified_by"] == "none"  # no hay archivo: ni siquiera oficial
    assert not any(t["step"] == "compile" for t in res.step_log)


def test_h14_oficial_fail_veta_y_oficial_pass_promueve(tmp_path, monkeypatch):
    for ok, expect_promoted in ((False, 0), (True, 1)):
        pipe = _pipe(tmp_path / f"case{ok}", meta_mvp=30.0)
        pipe.best_S = {"dqi": 3.714e12}
        orch = AdaptiveOrchestrator(pipe, _promoting_plan())
        monkeypatch.setattr(
            "auto_mvp.orchestrator.verify_circuit_file",
            lambda p, task: CircuitVerifyResult(
                ok=ok, S=3.2e12, verified_by="official",
                failures=[] if ok else ["verificador oficial FAIL"]),
        )
        res = orch.run([_bm_candidate(circuit_path="/tmp/falso.kmb")],
                       directives=["sube la meta a 2"])
        v = [t for t in res.step_log if t["step"] == "verify"][0]
        assert v["verified_by"] == "official" and v["ok"] is ok
        assert res.promoted == expect_promoted, (ok, res.promoted)
        assert v.get("veto", False) is (not ok)


def test_h14_factorizacion_llama_al_verificador_de_quimica(tmp_path,
                                                           monkeypatch):
    # La factorización (.npz) va por verify_chemistry_factorization,
    # no por el de circuitos. Se prueba con el cableado: el candidato
    # es DQI (promueve por proxy/gate) pero trae factorization_path.
    pipe = _pipe(tmp_path, meta_mvp=30.0)
    pipe.best_S = {"dqi": 3.714e12}
    orch = AdaptiveOrchestrator(pipe, _promoting_plan())
    seen: dict = {}

    def fake_chem(path, system="FeMoCo76o113e"):
        seen.update(path=path, system=system)
        return CircuitVerifyResult(False, failures=["química FAIL"],
                                   verified_by="official")

    monkeypatch.setattr("auto_mvp.orchestrator.verify_chemistry_factorization",
                        fake_chem)
    cand = _bm_candidate(factorization_path="/tmp/fact.npz")
    res = orch.run([cand], directives=["sube la meta a 2"])
    assert seen["path"] == "/tmp/fact.npz"
    assert res.promoted == 0
    v = [t for t in res.step_log if t["step"] == "verify"][0]
    assert v["veto"] is True and v["verified_by"] == "official"


def test_h14_sin_artefacto_sigue_el_cribado_local(tmp_path):
    pipe = _pipe(tmp_path, meta_mvp=30.0)
    pipe.best_S = {"dqi": 3.714e12}
    orch = AdaptiveOrchestrator(pipe, _promoting_plan())
    res = orch.run([_bm_candidate()], directives=["sube la meta a 2"])
    assert res.promoted == 1
    v = [t for t in res.step_log if t["step"] == "verify"][0]
    assert v["ok"] is True and v["verified_by"] == "cost-only"


# --- H15: search cableado con SearchLoop real ---

def test_h15_search_corre_el_lazo_real(tmp_path):
    from auto_mvp.orchestrator import IMPLEMENTED_STEPS, NOT_WIRED
    assert "search" in IMPLEMENTED_STEPS and "search" not in NOT_WIRED
    pipe = _pipe(tmp_path, meta_mvp=30.0)
    pipe.best_S = {"dqi": 3.714e12}
    plan = _steps("search", "tunnel", "proxy", "gate", "compile", "observe")
    orch = AdaptiveOrchestrator(pipe, plan)
    res = orch.run([_bm_candidate()], directives=["sube la meta a 2"])
    s = [t for t in res.step_log if t["step"] == "search"][0]
    # El lazo corrió de verdad: 5 intentos, 1 aceptado (S 3.714e12 bajo
    # el baseline 1.99836e13), 4 rechazados (mismo S, sin mejora).
    assert s["ok"] is True
    assert s["trials"] == 5 and s["accepted"] == 1 and s["rejected"] == 4
    assert s["best_S"] == pytest.approx(3.714e12, rel=1e-3)
    assert res.promoted == 1


def test_h15_search_con_mutador_real_devuelve_el_mejor(tmp_path):
    class BetterMutator:
        def propose(self, spec, best, evidence):
            return {"name": "mutado", "kind": "candidate",
                    "meta": {"task": "dqi", "metrics": {
                        "Q": 1_414, "T": 1_000_000, "eps_plus": 0.001188}},
                    "metrics": {"Q": 1_414, "T": 1_000_000,
                                "eps_plus": 0.001188}}

    pipe = _pipe(tmp_path, meta_mvp=30.0)
    pipe.best_S = {"dqi": 3.714e12}
    plan = StepPlan(steps=[
        {"step": "search", "method": "morph",
         "params": {"mutator": BetterMutator(), "max_trials": 2}},
        {"step": "proxy", "method": "", "params": {}},
        {"step": "gate", "method": "", "params": {}},
        {"step": "compile", "method": "", "params": {}},
    ])
    orch = AdaptiveOrchestrator(pipe, plan)
    res = orch.run([_bm_candidate()], directives=["sube la meta a 2"])
    s = [t for t in res.step_log if t["step"] == "search"][0]
    assert s["found"] == "mutado" and s["accepted"] >= 1
    assert res.promoted == 1  # el mutado (S ~2.46e12) promueve


# --- H16: sonda por directiva para calibrate ---

def test_h16_sonda_por_directiva_calibra(tmp_path):
    pipe = _pipe(tmp_path, meta_mvp=30.0)
    pipe.best_S = {"dqi": 3.714e12}
    orch = AdaptiveOrchestrator(pipe, _steps(
        "calibrate", "tunnel", "proxy", "gate", "compile", "observe"))
    assert orch.apply_directive(f"sonda {_probe_json()}")
    assert orch.probe is not None and len(orch.probe) == 2
    res = orch.run([_bm_candidate()], directives=["sube la meta a 2"])
    c = [t for t in res.step_log if t["step"] == "calibrate"][0]
    assert c["ok"] is True and c["probe_source"] == "directive"
    assert c["margin"] == pytest.approx(pipe.proxy.margin)
    assert res.promoted == 1


def test_h16_sonda_por_objeto_directive_y_texto_invalido(tmp_path):
    orch = AdaptiveOrchestrator(_pipe(tmp_path), StepPlan())
    probe = json.loads(_probe_json())
    assert orch.apply_directive(Directive("set_probe", {"probe": probe}))
    assert len(orch.probe) == 2
    assert not orch.apply_directive("sonda")
    assert not orch.apply_directive("sonda no-es-json")
    assert not orch.apply_directive(
        Directive("set_probe", {"probe": "no-una-lista"}))


def test_h16_calibrate_sin_sonda_sigue_fallando_visible(tmp_path):
    pipe = _pipe(tmp_path, meta_mvp=30.0)
    pipe.best_S = {"dqi": 3.714e12}
    orch = AdaptiveOrchestrator(pipe, _steps(
        "calibrate", "tunnel", "proxy", "gate", "compile", "observe"))
    res = orch.run([_bm_candidate()], directives=["sube la meta a 2"])
    c = [t for t in res.step_log if t["step"] == "calibrate"][0]
    assert c["ok"] is False and "sonda" in c["reason"]
    assert res.promoted == 1  # la corrida sigue sin la calibración


# --- H17: orden inválido lanza error claro, no descarta en silencio ---

def test_h17_gate_sin_proxy_lanza_error(tmp_path):
    pipe = _pipe(tmp_path, meta_mvp=30.0)
    orch = AdaptiveOrchestrator(pipe, _steps(
        "gate", "proxy", "compile", "observe"))
    with pytest.raises(StepOrderError, match="proxy no corrió antes"):
        orch.run([_bm_candidate()])
    assert "proxy" in orch.step_log[-1]["reason"]


def test_h17_compile_sin_promocion_lanza_error(tmp_path):
    pipe = _pipe(tmp_path, meta_mvp=30.0)
    pipe.best_S = {"dqi": 1e13}  # para que el proxy pase sin túnel
    orch = AdaptiveOrchestrator(pipe, _steps("proxy", "compile", "observe"))
    with pytest.raises(StepOrderError, match="sin promoción"):
        orch.run([_bm_candidate()])


# --- H18: el record de compile lleva name ---

def test_h18_compile_record_lleva_name(tmp_path):
    pipe = _pipe(tmp_path, meta_mvp=30.0)
    pipe.best_S = {"dqi": 3.714e12}
    orch = AdaptiveOrchestrator(pipe, StepPlan())
    res = orch.run([_bm_candidate()], directives=["sube la meta a 2"])
    assert res.promoted == 1 and len(res.artifacts) == 1
    saved = json.loads((Path(res.artifacts[0]) / "candidate.json")
                       .read_text(encoding="utf-8"))
    assert saved["name"] == "bm-forney"


# --- H20: el mejor se actualiza durante la corrida ---

def test_h20_mejor_actualizado_durante_corrida(tmp_path):
    pipe = _pipe(tmp_path, meta_mvp=30.0)
    pipe.best_S = {"dqi": 3.714e12}
    orch = AdaptiveOrchestrator(pipe, StepPlan())
    res = orch.run([_bm_candidate()], directives=["sube la meta a 2"])
    # El candidato promueve (S tunelado 3.2331e12) y sube el listón:
    # mejor por tarea y "current" de la puerta ya no son el inicial.
    assert res.promoted == 1
    assert pipe.best_S["dqi"] == pytest.approx(3.2331e12, rel=1e-3)
    assert pipe.gate.current["dqi"] == pipe.best_S["dqi"]
    g = [t for t in res.step_log if t["step"] == "gate"][0]
    assert g["best_S_updated"] == {"dqi": pytest.approx(3.2331e12, rel=1e-3)}
    # Segunda corrida con el mismo pipe y la meta subida (si no, la
    # corrida pararía por "meta alcanzada"): el candidato idéntico ya
    # no pasa el proxy contra el mejor nuevo.
    orch2 = AdaptiveOrchestrator(pipe, StepPlan())
    res2 = orch2.run([_bm_candidate()], directives=["sube la meta a 30"])
    assert res2.promoted == 0 and res2.proxy_rejected == 1


def test_h20_sin_promocion_no_sube_el_liston(tmp_path):
    # Con meta 30 el candidato no promueve: el mejor por tarea no se
    # mueve y un segundo intento idéntico aún pasa el proxy.
    pipe = _pipe(tmp_path, meta_mvp=30.0)
    pipe.best_S = {"dqi": 3.714e12}
    orch = AdaptiveOrchestrator(pipe, StepPlan())
    res = orch.run([_bm_candidate(), _bm_candidate()])
    assert res.promoted == 0 and res.proxy_rejected == 0
    assert pipe.best_S["dqi"] == pytest.approx(3.714e12, rel=1e-9)


# --- H23: respeta un tunnel_engine ya configurado ---

def test_h23_respeta_motor_existente_y_pone_el_propio_si_no_hay(tmp_path):
    custom = [RULES[0]]
    pipe = _pipe(tmp_path, meta_mvp=30.0, tunnel_engine=custom)
    AdaptiveOrchestrator(pipe, StepPlan())
    assert pipe.tunnel_engine is custom
    pipe2 = _pipe(tmp_path / "otro", meta_mvp=30.0)
    orch2 = AdaptiveOrchestrator(pipe2, StepPlan())
    assert pipe2.tunnel_engine == orch2.tunnel_rules == RULES


# --- H24: set_meta_mvp actualiza pipe.meta_mvp ---

def test_h24_set_meta_mvp_actualiza_pipe_meta_mvp(tmp_path):
    pipe = _pipe(tmp_path, meta_mvp=30.0)
    orch = AdaptiveOrchestrator(pipe, StepPlan())
    assert orch.apply_directive("sube la meta a 30")
    assert pipe.meta_mvp == 30.0
    assert pipe.gate.meta_mvp == 30.0 and pipe.gate.threshold == 30.0


# --- H25: prune registra que el margen es genérico ---

def test_h25_prune_registra_margen_generico(tmp_path):
    pipe = _pipe(tmp_path, meta_mvp=30.0)
    orch = AdaptiveOrchestrator(pipe, StepPlan())
    assert orch.apply_directive("poda lo que no baje T un 5%")
    assert pipe.proxy.margin == 0.05
    rec = [r for r in orch.reprogrammings if r["action"] == "prune"][0]
    assert rec["detail"]["metric"] == "T"
    assert rec["detail"]["scope"] == "generic"
    assert "proxy.margin" in rec["detail"]["note"]

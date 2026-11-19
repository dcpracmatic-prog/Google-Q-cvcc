"""AUTO_MVP v0.6.0 — capa de adaptación dinámica (MORPH + JSON + orquestador).

Verifica, con números medidos:
- Puente Qualtran: Bloqs reales (Toffoli T=4 Q=3; Add(QUInt(4))
  T=12 Q=8, And 3+3 + CNOT 15) y T/Q como cantidades de primera clase.
- Tunelamiento MORPH: reemplazo y reordenamiento de bloques sobre
  el grafo de llamadas; la regla Montgomery medida (T 1,511,522 ->
  1,315,731) y Toom-4 (S 1.99836e13 -> 1.923348e13).
- Decodificador JSON en lenguaje natural: el vocabulario controlado
  y las directivas no parseadas (nunca se tiran en silencio).
- Plan de pasos: reordenar, reemplazar, insertar, quitar, con log.
- Orquestador adaptativo: el orden de los pasos cambia el resultado
  (túnel antes del proxy salta la barrera del proxy; túnel después
  no) y las directivas en caliente reprograman la meta y el plan.
"""
from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path

import pytest

from auto_mvp.goal import Goal
from auto_mvp.json_directive import load_plan, parse_directive
from auto_mvp.morph_tunnel import RULES, ReplacementRule, tunnel
from auto_mvp.orchestrator import AdaptiveOrchestrator
from auto_mvp.pipeline import Pipeline
from auto_mvp.proxy import MetadataProxy
from auto_mvp.qualtran_bridge import Block, CallGraph, from_qualtran_bloq
from auto_mvp.step_plan import StepPlan
from auto_mvp.vqcc import dqi_spec


# --- Puente Qualtran (Bloqs reales) ---

def test_bridge_toffoli_real():
    pytest.importorskip("qualtran")
    from qualtran.bloqs.basic_gates import Toffoli
    g = from_qualtran_bloq(Toffoli())
    assert g.source == "qualtran"
    assert g.cost() == {"T": 4.0, "Q": 3}
    assert g.root.is_leaf


def test_bridge_add_real():
    pytest.importorskip("qualtran")
    from qualtran.bloqs.arithmetic import Add
    from qualtran import QUInt
    g = from_qualtran_bloq(Add(QUInt(4)))
    assert g.cost() == {"T": 12.0, "Q": 8}
    kids = {c.name: n for c, n in g.root.children}
    # Qualtran 0.8.0.dev0 renombró el adjunto: "And†" pasó a "And_adj"
    # (mismo conteo: And 3 + adjunto 3 + CNOT 15, T=12, Q=8).
    # v2.17.11: en otras versiones el adjunto se llama "And†" o
    # "And_dag"; se busca por prefijo, no por el nombre exacto.
    adj = next((n for name, n in kids.items()
                if name != "And" and name.startswith("And")), None)
    assert kids["And"] == 3 and adj == 3 and kids["CNOT"] == 15
    # El T total sale de la suma de los llamados, como en Qualtran.
    assert g.total_T() == 12.0


def test_bridge_cost_first_class():
    leaf = Block(name="a", kind="a", t_count=100, qubits=5)
    assert leaf.total_T() == 100.0
    root = Block(name="r", kind="r", t_count=None, qubits=10, children=[
        (Block(name="x", kind="x", t_count=30), 2),
        (Block(name="y", kind="y", t_count=40), 1)])
    assert CallGraph(root=root).total_T() == 100.0
    assert CallGraph(root=root).total_Q() == 10
    unknown = Block(name="u", kind="u", t_count=None)
    assert unknown.total_T() is None  # sin medir, no se inventa
    assert CallGraph(root=Block(name="r2", kind="r2", children=[(unknown, 1)])).total_T() is None


def test_bridge_roundtrip_json():
    g = CallGraph(root=Block(name="r", kind="r", t_count=7, qubits=2,
                             children=[(Block(name="c", kind="c", t_count=7), 1)]),
                  source="cost_model")
    g2 = CallGraph.from_dict(json.loads(json.dumps(g.to_dict())))
    assert g2.total_T() == 7.0 and g2.total_Q() == 2 and g2.source == "cost_model"


# --- Tunelamiento MORPH ---

def _bm_graph() -> CallGraph:
    """El circuito BM+Forney como grafo de llamadas (cost_model exacto)."""
    root = Block(name="dqi-bm-forney", kind="dqi", t_count=1_511_522,
                 qubits=1_414, children=[
                     (Block(name="bm_forward", kind="bm_forward"), 1),
                     (Block(name="omega", kind="omega"), 1),
                     (Block(name="chien", kind="chien"), 1),
                     (Block(name="bm_backward", kind="bm_backward"), 1)])
    return CallGraph(root=root, source="cost_model")


def test_tunnel_montgomery_measured():
    res = tunnel(_bm_graph(), RULES)
    assert res.baseline_T == 1_511_522.0
    assert res.final_T == 1_315_731.0  # medido (montgomery-v4)
    assert res.final_Q == 1_414
    assert len(res.moves) == 1 and res.moves[0].rule == "chien-montgomery-b17"
    s = 1.22901 * 1_414 ** 2 * res.final_T
    assert abs(s - 3.2331e12) / 3.2331e12 < 1e-3


def test_tunnel_toom4_measured():
    q, r = 1899.0, 1.22901
    t_toom3 = 1.99836e13 / (r * q ** 2)
    root = Block(name="dqi-toom3", kind="dqi", t_count=t_toom3, qubits=1_899,
                 children=[(Block(name="multiplier", kind="multiplier"), 1)])
    res = tunnel(CallGraph(root=root, source="cost_model"), RULES)
    assert res.moves and res.moves[0].rule == "multiplier-toom4"
    s = r * q ** 2 * res.final_T
    assert abs(s - 1.923348e13) / 1.923348e13 < 1e-3


def test_tunnel_reorder_unlocks_rule():
    root = Block(name="r", kind="r", t_count=None, children=[
        (Block(name="C", kind="C", t_count=50), 1),
        (Block(name="A", kind="A", t_count=100), 1),
        (Block(name="B", kind="B", t_count=200), 1)])
    rule = ReplacementRule(
        name="b-mejora", target="B", replacement="B2", delta_T=-80.0,
        evidence="sintético con evidencia", requires_order=("A", "C"))
    res = tunnel(CallGraph(root=root, source="manual"), [rule])
    assert res.baseline_T == 350.0 and res.final_T == 270.0
    assert res.moves[0].kind == "reorder"  # reordena A antes que C
    assert res.moves[1].rule == "b-mejora"
    # Reordenar solo no cambia el costo.
    order = [c.name for c, _ in res.graph.root.children]
    assert order.index("A") < order.index("C")


def test_tunnel_rule_needs_evidence():
    with pytest.raises(ValueError):
        ReplacementRule(name="sin-evidencia", target="x", replacement="y",
                        delta_T=-1.0, evidence="")
    with pytest.raises(ValueError):
        ReplacementRule(name="sin-delta", target="x", replacement="y",
                        evidence="algo")


def test_tunnel_beam_finds_best_sequence():
    # Dos reglas independientes: voraz y haz llegan al mismo óptimo
    # (el haz explora secuencias; aquí no hay dependencia de orden).
    root = Block(name="r", kind="r", t_count=None, children=[
        (Block(name="A", kind="A", t_count=100), 1),
        (Block(name="B", kind="B", t_count=100), 1)])
    r1 = ReplacementRule(name="a-10", target="A", replacement="A2",
                         delta_T=-10.0, evidence="sintético")
    r2 = ReplacementRule(name="b-50", target="B", replacement="B2",
                         delta_T=-50.0, evidence="sintético")
    greedy = tunnel(CallGraph(root=root, source="manual"), [r1, r2])
    beam = tunnel(CallGraph(root=root, source="manual"), [r1, r2], method="beam")
    assert greedy.final_T == 140.0 and beam.final_T == 140.0
    assert [m.rule for m in beam.moves] == ["b-50", "a-10"]


# --- Decodificador JSON en lenguaje natural ---

CASES = [
    ("sube la meta a 30", "set_meta_mvp", {"meta_mvp": 30.0}),
    ("meta 2", "set_meta_mvp", {"meta_mvp": 2.0}),
    ("baja la meta a 2.5", "set_meta_mvp", {"meta_mvp": 2.5}),
    ("ataca unextract", "tunnel", {"block": "unextract"}),
    ("tunela chien con montgomery-b17", "tunnel",
     {"block": "chien", "rule": "montgomery-b17"}),
    ("poda lo que no baje T un 5%", "prune", {"metric": "T", "pct": 5.0}),
    ("reordena tunnel antes que gate", "reorder_step",
     {"step": "tunnel", "before": "gate"}),
    ("mueve proxy despues de tunnel", "reorder_step",
     {"step": "proxy", "after": "tunnel"}),
    ("reemplaza proxy por numeric", "replace_method",
     {"step": "proxy", "method": "numeric"}),
    ("usa beam en vez de greedy", "replace_method",
     {"from": "greedy", "method": "beam"}),
    ("inserta observe despues de compile", "insert_step",
     {"step": "observe", "after": "compile"}),
    ("quita calibrate", "remove_step", {"step": "calibrate"}),
    ("presupuesto 20 intentos", "set_budget", {"trials": 20.0}),
    ("presupuesto 6 horas", "set_budget", {"hours": 6.0}),
    ("usa numeric para proxy", "set_method",
     {"step": "proxy", "method": "numeric"}),
]


def test_directives_vocabulary():
    for text, verb, params in CASES:
        d = parse_directive(text)
        assert d.parsed and d.verb == verb, text
        assert d.params == params, text


def test_directive_unparsed_never_silent():
    d = parse_directive("haz magia con los qubits")
    assert not d.parsed and d.reason
    plan = load_plan({"directives": ["haz magia con los qubits",
                                     "meta 30"]})
    assert len(plan["unparsed"]) == 1
    assert plan["unparsed"][0].raw == "haz magia con los qubits"
    assert plan["directives"][1].verb == "set_meta_mvp"


def test_load_plan_json():
    cfg = {"meta_mvp": 30.0,
           "steps": [{"step": "tunnel", "method": "greedy"},
                     {"step": "proxy", "method": "metadata"}],
           "directives": ["reordena tunnel antes que gate"],
           "budget": {"trials": 20}}
    plan = load_plan(cfg)
    assert plan["meta_mvp"] == 30.0
    assert [s["step"] for s in plan["steps"]] == ["tunnel", "proxy"]
    assert plan["budget"] == {"trials": 20}
    assert plan["directives"][0].verb == "reorder_step"


# --- Plan de pasos ---

def test_step_plan_reprogram():
    plan = StepPlan()
    assert plan.order == ["tunnel", "proxy", "gate", "compile", "observe"]
    assert plan.move("tunnel", after="gate")
    assert plan.order == ["proxy", "gate", "tunnel", "compile", "observe"]
    assert plan.replace_method("tunnel", "beam")
    assert plan.method_of("tunnel") == "beam"
    assert plan.insert("calibrate", "dcp", before="proxy")
    assert plan.order[0] == "calibrate"
    assert plan.remove("calibrate")
    assert "calibrate" not in plan.order
    assert len(plan.log) == 4  # cada reprogramación queda en el log
    assert not plan.move("inexistente", after="gate")


def test_step_plan_apply_directive():
    plan = StepPlan()
    assert plan.apply(parse_directive("reordena gate antes que proxy"))
    assert plan.order[1] == "gate" and plan.order[2] == "proxy"
    assert plan.apply(parse_directive("usa beam en vez de greedy"))
    assert plan.method_of("tunnel") == "beam"


# --- Orquestador adaptativo ---

def _pipe(tmp: Path, meta_mvp: float = 30.0) -> Pipeline:
    from auto_mvp.pipeline import PromotionGate
    return Pipeline(
        proxy=MetadataProxy(spec=dqi_spec(), margin=0.10),
        gate=PromotionGate(meta_mvp),
        runs_dir=tmp / "runs",
        time_budget_seconds=None,
    )


def _bm_candidate() -> dict:
    """El candidato BM+Forney con su grafo de llamadas (cost_model)."""
    return {
        "name": "bm-forney", "kind": "candidate",
        "meta": {"task": "dqi", "metrics": {"Q": 1_414, "T": 1_511_522,
                                            "eps_plus": 0.001188}},
        "metrics": {"Q": 1_414, "T": 1_511_522, "eps_plus": 0.001188},
        "call_graph": _bm_graph().to_dict(),
    }


def test_orchestrator_tunnel_first_jumps_proxy_barrier(tmp_path):
    """Túnel antes del proxy: el candidato pasa; túnel después: no."""
    stream = [_bm_candidate()]
    # El mejor DQI conocido es el BM+Forney (3.714e12): el proxy exige
    # mejorar un 10% sobre él. Sin túnel S=3.714e12 no pasa; con
    # Montgomery (S=3.2331e12) sí.
    for i, (order, expect_promoted) in enumerate((
            (["tunnel", "proxy", "gate", "compile", "observe"], True),
            (["proxy", "gate", "compile", "tunnel", "observe"], False))):
        # Cada orden corre en su propio estado (si no, el mejor del
        # primer caso se cuela en el segundo por el state.json).
        pipe = _pipe(tmp_path / f"case{i}", meta_mvp=30.0)
        pipe.best_S = {"dqi": 3.714e12}
        plan = StepPlan(steps=[{"step": s, "method": "", "params": {}}
                               for s in order])
        orch = AdaptiveOrchestrator(pipe, plan)
        res = orch.run(stream, directives=["sube la meta a 2"])
        assert res.meta_mvp == 2.0
        assert (res.promoted == 1) == expect_promoted, order
        assert res.goal_reached == expect_promoted, order
        if expect_promoted:
            assert res.tunneled == 1
            assert res.best_gm > 2.0  # GM ~11.7 con DQI 7.55x


def test_orchestrator_mid_run_reprogramming(tmp_path):
    """Una directiva en caliente (iteración 2) baja la meta y reordena."""
    cands = [_bm_candidate(), _bm_candidate()]
    pipe = _pipe(tmp_path, meta_mvp=30.0)
    pipe.best_S = {"dqi": 3.714e12}
    plan = StepPlan()
    orch = AdaptiveOrchestrator(pipe, plan)
    res = orch.run(cands, directives_at={
        2: ["sube la meta a 2", "reordena observe antes que compile"]})
    assert res.promoted == 1  # el 2º candidato promueve con meta 2
    assert res.meta_mvp == 2.0
    actions = [r["action"] for r in res.reprogrammings]
    assert "set_meta_mvp" in actions and "plan:reorder_step" in actions
    assert res.step_log[0]["step"] == "tunnel"


def test_orchestrator_prune_sets_proxy_margin(tmp_path):
    pipe = _pipe(tmp_path, meta_mvp=30.0)
    orch = AdaptiveOrchestrator(pipe, StepPlan())
    assert orch.apply_directive("poda lo que no baje T un 5%")
    assert pipe.proxy.margin == 0.05


def test_orchestrator_unparsed_directive_reported(tmp_path):
    pipe = _pipe(tmp_path, meta_mvp=30.0)
    orch = AdaptiveOrchestrator(pipe, StepPlan())
    assert not orch.apply_directive("haz magia con los qubits")
    res = orch.run([_bm_candidate()])
    assert any(r["action"] == "unparsed" for r in res.reprogrammings)
    assert res.screened == 1  # la corrida sigue, no muere por eso


def test_orchestrator_verify_step(tmp_path):
    pipe = _pipe(tmp_path, meta_mvp=30.0)
    pipe.best_S = {"dqi": 3.714e12}
    plan = StepPlan(steps=[
        {"step": "tunnel", "method": "greedy", "params": {}},
        {"step": "proxy", "method": "metadata", "params": {}},
        {"step": "gate", "method": "meta_mvp", "params": {}},
        {"step": "verify", "method": "local", "params": {}},
        {"step": "compile", "method": "local", "params": {}},
    ])
    orch = AdaptiveOrchestrator(pipe, plan)
    res = orch.run([_bm_candidate()], directives=["sube la meta a 2"])
    assert res.promoted == 1
    v = [t for t in res.step_log if t["step"] == "verify"][0]
    assert v["ok"] is True and v["verified_by"] == "cost-only"


def test_orchestrator_default_plan_matches_pipeline(tmp_path):
    """El plan por defecto (tunnel, proxy, gate, compile, observe) con
    un stream sin grafos da lo mismo que el Pipeline solo."""
    def stream():
        yield {"name": "a", "kind": "candidate",
               "meta": {"task": "dqi", "metrics": {"Q": 892, "T": 195_000,
                                                   "eps_plus": 0.001}},
               "metrics": {"Q": 892, "T": 195_000, "eps_plus": 0.001}}
    pipe = _pipe(tmp_path, meta_mvp=30.0)
    orch = AdaptiveOrchestrator(pipe, StepPlan())
    res = orch.run(stream())
    assert res.promoted == 1 and res.best_gm > 30.0

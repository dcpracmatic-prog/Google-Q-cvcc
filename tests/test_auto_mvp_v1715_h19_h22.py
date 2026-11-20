"""Tests H19/H22 (v2.17.15): el cableado real de AutoMvp al orquestador,
al pipeline, a MORPH, al JSON y al puente Qualtran.

H19: AutoMvp.run corre SOBRE un Pipeline + AdaptiveOrchestrator
construidos con sus propios componentes: el túnel MORPH va por
Pipeline.tunnel_candidate, la criba por proxy va por
Pipeline.proxy_eval y las directivas JSON van por
AdaptiveOrchestrator.apply_directive. El lazo NO es
AdaptiveOrchestrator.run ni Pipeline.run (ver docstring de mvp.py:
esos dos paran en la primera promoción y su "gate" necesita el S
estimado del paso "proxy").

H22: from_qualtran_bloq se usa en producción: AutoMvp.run extrae el
grafo de un Bloq REAL de Qualtran cuando el candidato trae "bloq",
y ese grafo real es el que se tunela. Sin Qualtran, el lazo sigue
sin grafo (no se inventa ninguno).

Números DQI medidos: base BM+Forney S=3.714e12 (Q=1414, T=1511522);
MIS S=3.197e12; túnel chien-montgomery S=3.2331e12 (T=1315731).
"""
from __future__ import annotations

import sys
import tempfile
from dataclasses import replace as _replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auto_mvp import AutoMvp, Goal, MetadataProxy
from auto_mvp.morph_tunnel import RULES
from auto_mvp.orchestrator import AdaptiveOrchestrator
from auto_mvp.pipeline import Pipeline
from auto_mvp.qualtran_bridge import CallGraph
from auto_mvp.vqcc import dqi_spec
from auto_mvp.vqcc.costs import s_dqi

EPS = 0.001188
BASE_S = 3.714e12  # BM+Forney base, Q=1414 T=1511522
MIS_S = s_dqi(1412, 1_304_706, EPS)  # ~3.197e12


def _bm_graph() -> dict:
    """BM+Forney como grafo (igual que test_auto_mvp_v060._bm_graph)."""
    from auto_mvp.qualtran_bridge import Block
    root = Block(name="dqi-bm-forney", kind="dqi", t_count=1_511_522,
                 qubits=1_414, children=[
                     (Block(name="bm_forward", kind="bm_forward"), 1),
                     (Block(name="omega", kind="omega"), 1),
                     (Block(name="chien", kind="chien"), 1),
                     (Block(name="bm_backward", kind="bm_backward"), 1)])
    return CallGraph(root=root, source="cost_model").to_dict()


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


def _goal():
    return Goal(baseline_S=BASE_S, improvement_pct=50.0, base_trials=10,
                max_trials=10, patience=5)


def _spec():
    return _replace(dqi_spec(), baseline_S=BASE_S)


# --- H19: el lazo posee pipeline + orquestador ---

def test_mvp_owns_pipeline_and_orchestrator():
    mvp = AutoMvp(_spec(), ScriptedMutator([]), _goal())
    assert isinstance(mvp.pipeline, Pipeline)
    assert isinstance(mvp.orchestrator, AdaptiveOrchestrator)
    assert mvp.orchestrator.pipe is mvp.pipeline
    # El orquestador conectó el motor MORPH al pipeline.
    assert list(mvp.pipeline.tunnel_engine) == list(RULES)
    assert mvp.pipeline_runs_dir is not None
    assert Path(mvp.pipeline_runs_dir).is_dir()


def test_mvp_tunnels_real_call_graph():
    """H19 (MORPH): el túnel corre en el lazo y su T medido se verifica."""
    cand = {"mutation": "bm-forney",
            "metrics": {"Q": 1414, "T": 1_511_522, "eps_plus": EPS},
            "params": {"combo": "bm-forney"},
            "call_graph": _bm_graph()}
    with tempfile.TemporaryDirectory() as d:
        mvp = AutoMvp(_spec(), ScriptedMutator([cand]), _goal(), workdir=d)
        res = mvp.run()
    assert res.tunnel_checked == 1, res
    assert res.tunneled == 1, res
    assert res.tunnel_errors == []
    assert res.accepted == 1, res
    # El S verificado es el del grafo TUNELADO (medido montgomery-v4).
    assert abs(res.best_S - 3.2331e12) / 3.2331e12 < 1e-3, res
    assert res.best_S < BASE_S
    # El mejor guardado lleva el grafo tunelado, no el base.
    best_graph = res.best["call_graph"]
    assert best_graph["root"]["t_count"] == 1_315_731.0
    names = [c[0]["name"] for c in best_graph["root"]["children"]]
    assert "montgomery-b17" in names and "chien" not in names
    assert res.best["tunnel"]["moves"][0]["rule"] == "chien-montgomery-b17"


def test_mvp_grafo_roto_no_tumba_el_lazo():
    """Un grafo roto no tumba el lazo: queda registrado y se verifica igual."""
    cand = {"mutation": "grafo-roto",
            "metrics": {"Q": 1412, "T": 1_304_706, "eps_plus": EPS},
            "params": {}, "call_graph": {"root": {}}}
    with tempfile.TemporaryDirectory() as d:
        mvp = AutoMvp(_spec(), ScriptedMutator([cand]), _goal(), workdir=d)
        res = mvp.run()
    assert len(res.tunnel_errors) == 1, res
    assert res.accepted == 1, res
    assert abs(res.best_S - MIS_S) < 1.0, res


class CountingProxy(MetadataProxy):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.calls = 0

    def evaluate(self, meta, best_S):
        self.calls += 1
        return super().evaluate(meta, best_S)


def test_mvp_proxy_runs_through_pipeline():
    """H19 (Pipeline): la criba va por Pipeline.proxy_eval, con el
    mejor S del MVP sincronizado en el pipeline (no contra el mejor envío)."""
    spec = _spec()
    proxy = CountingProxy(spec, hard_caps={"max_qubits": 2000}, margin=0.10)
    mis = {"mutation": "L+D+G_b17",
           "metrics": {"Q": 1412, "T": 1_304_706, "eps_plus": EPS},
           "params": {"combo": "L+D+G_b17"}}
    big = {"mutation": "demasiado-grande",
           "metrics": {"Q": 1412, "T": 1_304_706, "eps_plus": EPS},
           "params": {},
           "meta": {"task": "dqi",
                    "metrics": {"Q": 1412, "T": 1_304_706, "eps_plus": EPS},
                    "register_widths": {"S": 840, "C": 432, "B": 432,
                                        "extra": 500}}}
    with tempfile.TemporaryDirectory() as d:
        mvp = AutoMvp(spec, ScriptedMutator([mis, big]), _goal(),
                      proxy=proxy, workdir=d)
        # La criba usa EL MISMO proxy que el pipeline (no una copia).
        assert mvp.pipeline.proxy is proxy
        res = mvp.run()
    # Solo el candidato con "meta" pasó por el proxy (el otro, no).
    assert proxy.calls == 1, proxy.calls
    assert res.proxy_rejected == 1, res
    assert res.accepted == 1, res
    # El pipeline comparó contra el best_S vigente (MIS), no contra el
    # mejor envío: la sincronización ocurrió de verdad.
    assert abs(mvp.pipeline.best_S["dqi"] - MIS_S) < 1.0


def test_mvp_directives_prune_changes_screening():
    """H19 (JSON): una directiva "prune" cambia el margen del proxy
    del lazo y eso cambia qué se criba (efecto real, no solo registro)."""
    spec = _spec()
    # S estimado 0.798x la base: pasa con margen 0.10, no con 0.25.
    cand = {"mutation": "casi",
            "metrics": {"Q": 1400, "T": 1_230_000, "eps_plus": EPS},
            "params": {},
            "meta": {"task": "dqi",
                     "metrics": {"Q": 1400, "T": 1_230_000, "eps_plus": EPS},
                     "register_widths": {"S": 800, "C": 300, "B": 300}}}
    est = s_dqi(1400, 1_230_000, EPS)
    assert BASE_S * 0.75 < est < BASE_S * 0.90, est
    with tempfile.TemporaryDirectory() as d:
        proxy_a = MetadataProxy(spec, margin=0.25)
        mvp_a = AutoMvp(spec, ScriptedMutator([dict(cand)]), _goal(),
                        proxy=proxy_a, workdir=d)
        res_a = mvp_a.run()
        proxy_b = MetadataProxy(spec, margin=0.25)
        mvp_b = AutoMvp(spec, ScriptedMutator([dict(cand)]), _goal(),
                        proxy=proxy_b, workdir=d)
        res_b = mvp_b.run(directives=["poda lo que no baje T un 10%"])
    # Sin directiva: el proxy (margen 0.25) lo criba.
    assert res_a.proxy_rejected == 1 and res_a.accepted == 0, res_a
    # Con directiva: el margen baja a 0.10, pasa la criba y se acepta.
    assert res_b.proxy_rejected == 0 and res_b.accepted == 1, res_b
    assert abs(res_b.best_S - est) < 1.0, res_b
    assert mvp_b.orchestrator.pipe.proxy.margin == 0.10
    assert any(r["action"] == "prune" for r in res_b.reprogrammings), \
        res_b.reprogrammings


def test_mvp_directiva_no_parseada_no_tumba_el_lazo():
    """Una directiva fuera del vocabulario queda registrada, no se tira
    en silencio y no tumba el lazo."""
    cand = {"mutation": "mis",
            "metrics": {"Q": 1412, "T": 1_304_706, "eps_plus": EPS},
            "params": {}}
    with tempfile.TemporaryDirectory() as d:
        mvp = AutoMvp(_spec(), ScriptedMutator([cand]), _goal(), workdir=d)
        res = mvp.run(directives=["esto no es una directiva"])
    assert res.accepted == 1, res
    assert any(r["action"] == "unparsed" for r in res.reprogrammings), \
        res.reprogrammings


def test_mvp_docstring_no_miente():
    """H19 (docstring): ya no afirma lo que no hace."""
    import auto_mvp.mvp as mvp_mod
    doc = mvp_mod.__doc__ or ""
    assert "SÍ están aquí" not in doc
    assert "no es AdaptiveOrchestrator.run" in doc
    assert "Pipeline.tunnel_candidate" in doc
    assert "Pipeline.proxy_eval" in doc
    assert "AdaptiveOrchestrator.apply_directive" in doc


# --- H22: from_qualtran_bloq en producción ---

def test_mvp_bloq_real_graph():
    """H22: un candidato con un Bloq real se extrae en producción
    (Add(QUInt(4)): T=12, Q=8) y ese grafo real es el que se tunela."""
    pytest.importorskip("qualtran")
    from qualtran import QUInt
    from qualtran.bloqs.arithmetic import Add
    cand = {"mutation": "adder-4",
            "metrics": {"Q": 1412, "T": 1_304_706, "eps_plus": EPS},
            "params": {"bloq": "Add(QUInt(4))"},
            "bloq": Add(QUInt(4))}
    with tempfile.TemporaryDirectory() as d:
        mvp = AutoMvp(_spec(), ScriptedMutator([cand]), _goal(), workdir=d)
        res = mvp.run()
    assert res.qualtran_graphs == 1, res
    assert res.bloq_errors == []
    assert res.tunnel_checked == 1, res
    assert res.tunneled == 0, res  # ninguna regla MORPH aplica a And/CNOT
    assert res.accepted == 1, res
    assert abs(res.best_S - MIS_S) < 1.0, res
    g = CallGraph.from_dict(res.best["call_graph"])
    assert g.source == "qualtran"
    assert g.cost() == {"T": 12.0, "Q": 8}


def test_mvp_bloq_sin_qualtran_no_tumba_el_lazo(monkeypatch):
    """H22 (fallback): sin Qualtran no se inventa el grafo; el lazo
    sigue y verifica por métricas."""
    import auto_mvp.mvp as mvp_mod

    def _sin_qualtran(bloq):
        raise ImportError(
            "Qualtran no está instalado en este entorno; el puente "
            "necesita qualtran para extraer un Bloq real")

    monkeypatch.setattr(mvp_mod, "from_qualtran_bloq", _sin_qualtran)
    cand = {"mutation": "adder-4",
            "metrics": {"Q": 1412, "T": 1_304_706, "eps_plus": EPS},
            "params": {}, "bloq": object()}
    with tempfile.TemporaryDirectory() as d:
        mvp = AutoMvp(_spec(), ScriptedMutator([cand]), _goal(), workdir=d)
        res = mvp.run()
    assert res.qualtran_graphs == 0, res
    assert len(res.bloq_errors) == 1 and "Qualtran" in res.bloq_errors[0]
    assert res.accepted == 1, res
    assert "call_graph" not in (res.best or {})


def test_bridge_docstring_documenta_uso_produccion():
    """H22 (docstring): el puente dice dónde se usa en producción y
    qué grafos siguen construidos a mano (cost_model)."""
    import auto_mvp.qualtran_bridge as qb
    doc = qb.__doc__ or ""
    assert "mvp.py" in doc
    assert "from_qualtran_bloq" in doc
    assert "cost_model" in doc

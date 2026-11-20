"""Tests H8-H11: huecos de la auditoría MORPH/JSON/orquestador.

- H8: el gancho de integridad ``verify`` de tunnel() descarta de
  verdad los grafos tunelados que no lo pasan (y no aborta).
- H9: el motor ya no reordena: ningún movimiento es "reorder" y
  ninguna regla del registro exige orden.
- H10: la evidencia cita artefactos reales que existen en el repo;
  una cita falsa falla al construir la regla. Los números no se
  tocan (chien -195,791 exacto; toom4 delta_T = -169,248.72).
- H11: la semilla DQI trae el bloque "multiplier" (real: el
  decodificador usa multiplicadores GF) y la regla
  multiplier-toom4 puede aplicar; invsqrt y química siguen con
  grafos de solo raíz, sin reglas inventadas.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auto_mvp.morph_tunnel import RULES, ReplacementRule, _apply_rule, tunnel
from auto_mvp.qualtran_bridge import Block, CallGraph
from auto_mvp.seeds import default_seeds

REPO = Path(__file__).resolve().parents[1]


def _bm_graph() -> CallGraph:
    """El circuito BM+Forney como grafo de llamadas (cost_model exacto)."""
    root = Block(name="dqi-bm-forney", kind="dqi", t_count=1_511_522,
                 qubits=1_414, children=[
                     (Block(name="bm_forward", kind="bm_forward"), 1),
                     (Block(name="omega", kind="omega"), 1),
                     (Block(name="chien", kind="chien"), 1),
                     (Block(name="bm_backward", kind="bm_backward"), 1),
                     (Block(name="multiplier", kind="multiplier"), 1)])
    return CallGraph(root=root, source="cost_model")


# --- H8: el gancho verify descarta de verdad ---

def test_h8_verify_false_descarta_candidato_greedy():
    llamadas = []
    def verify(g: CallGraph) -> bool:
        llamadas.append(g.total_T())
        return False
    res = tunnel(_bm_graph(), RULES, verify=verify)
    assert llamadas, "verify nunca se llamó"
    assert res.moves == []  # el grafo tunelado se descartó
    assert res.final_T == res.baseline_T == 1_511_522.0
    assert res.graph.find("chien") is not None  # no se aplicó nada
    assert res.graph.find("montgomery-b17") is None


def test_h8_verify_false_descarta_candidato_beam():
    res = tunnel(_bm_graph(), RULES, method="beam",
                 verify=lambda g: False)
    assert res.moves == []
    assert res.final_T == 1_511_522.0


def test_h8_verify_rechaza_mejor_pero_aplica_peor():
    # Dos reglas independientes: verify rechaza el candidato bueno
    # (T=100) pero acepta el peor (T=190). El rechazo descarta ese
    # grafo sin abortar la búsqueda: se aplica la otra regla.
    # Base: A=100 + B=100 = 200.
    root = Block(name="r", kind="r", t_count=None, children=[
        (Block(name="A", kind="A", t_count=100), 1),
        (Block(name="B", kind="B", t_count=100), 1)])
    r_big = ReplacementRule(name="a-100", target="A", replacement="A2",
                            delta_T=-100.0, evidence="sintético")
    r_small = ReplacementRule(name="b-10", target="B", replacement="B2",
                              delta_T=-10.0, evidence="sintético")
    seen = []
    def verify(g: CallGraph) -> bool:
        seen.append(g.total_T())
        return g.total_T() >= 190.0  # rechaza T=100, acepta T=190
    res = tunnel(CallGraph(root=root, source="manual"), [r_big, r_small],
                 verify=verify)
    assert 100.0 in seen, "verify nunca vio el candidato rechazado"
    assert [m.rule for m in res.moves] == ["b-10"]
    assert res.final_T == 190.0
    assert res.graph.find("A2") is None  # el rechazado no se aplicó
    assert res.graph.find("B2") is not None


def test_h8_verify_true_aplica_normal():
    res = tunnel(_bm_graph(), RULES, verify=lambda g: True)
    assert res.final_T == 1_315_731.0 - 169_248.72234194502
    assert {m.rule for m in res.moves} == {
        "chien-montgomery-b17", "multiplier-toom4"}


# --- H9: no hay reordenamiento ---

def test_h9_ningun_movimiento_es_reorder():
    root = Block(name="r", kind="r", t_count=None, children=[
        (Block(name="C", kind="C", t_count=50), 1),
        (Block(name="A", kind="A", t_count=100), 1),
        (Block(name="B", kind="B", t_count=200), 1)])
    rule = ReplacementRule(
        name="b-mejora", target="B", replacement="B2", delta_T=-80.0,
        evidence="sintético con evidencia", requires_order=("A", "C"))
    res = tunnel(CallGraph(root=root, source="manual"), [rule])
    assert all(m.kind != "reorder" for m in res.moves)
    assert "reordenamiento de bloques que conmutan" not in [
        m.evidence for m in res.moves]


def test_h9_ninguna_regla_del_registro_exige_orden():
    assert all(r.requires_order is None for r in RULES)


# --- H10: evidencia verificable ---

def test_h10_artefacto_inexistente_falla_con_error_claro():
    with pytest.raises(ValueError, match="no existe en el repo"):
        ReplacementRule(name="cita-falsa", target="x", replacement="y",
                        delta_T=-1.0, evidence="algo",
                        evidence_artifact="no/existe.md")


def test_h10_reglas_citan_artefactos_reales():
    assert len(RULES) == 2
    for rule in RULES:
        assert rule.evidence_artifact, f"{rule.name} no cita artefacto"
        path = REPO / rule.evidence_artifact
        assert path.is_file(), f"{rule.name}: {path} no existe"
        assert rule.evidence_artifact in rule.evidence


def test_h10_citas_falsas_eliminadas():
    assert "INFORME_V4" not in RULES[0].evidence
    assert "montgomery-v4 INFORME_V4" not in RULES[0].evidence
    assert "dqi-toom4-v1-e2-102400" not in RULES[1].evidence
    assert RULES[0].evidence_artifact == "tests/test_auto_mvp_v060.py"
    assert RULES[1].evidence_artifact == (
        "auto_mvp/circuits/cost_models/dqi_cost.py")


def test_h10_numeros_no_cambian():
    # La aritmética cuadra y no se tocó (auditoría H10).
    assert RULES[0].delta_T == -195_791.0
    assert RULES[1].delta_T == pytest.approx(-169_248.72, rel=1e-6)
    # El artefacto citado para toom4 reproduce el S medido.
    from auto_mvp.circuits.cost_models.dqi_cost import estimate_variant
    v = estimate_variant(42, v1=True, e2=True)
    assert v["Q"] == 1_899 and v["T"] == 4_477_394
    assert abs(v["S"] - 1.923348e13) / 1.923348e13 < 1e-3


# --- H11: multiplier en la semilla DQI ---

def test_h11_semilla_dqi_tiene_multiplier():
    seed = default_seeds()["dqi"]["seed_graph"]
    names = [c.name for c, _ in
             CallGraph.from_dict(seed).root.children]
    assert "multiplier" in names
    graph = CallGraph.from_dict(seed)
    assert RULES[1].applies_to(graph)  # multiplier-toom4 ya puede aplicar
    assert RULES[0].applies_to(graph)  # chien-montgomery sigue aplicando


def test_h11_semilla_dqi_conserva_totales_y_sin_T_inventado():
    seed = default_seeds()["dqi"]["seed_graph"]
    graph = CallGraph.from_dict(seed)
    assert graph.total_T() == 1_511_522.0
    assert graph.total_Q() == 1_414
    mult = graph.find("multiplier")
    assert mult is not None and mult.t_count is None  # sin costo inventado


def test_h11_toom4_reemplaza_multiplier_en_semilla():
    graph = CallGraph.from_dict(default_seeds()["dqi"]["seed_graph"])
    new = _apply_rule(graph, RULES[1])
    assert new is not None
    assert new.find("toom4") is not None
    assert new.find("multiplier") is None


def test_h11_invsqrt_y_quimica_siguen_sin_hijos():
    seeds = default_seeds()
    for task in ("invsqrt", "dfthcsos"):
        graph = CallGraph.from_dict(seeds[task]["seed_graph"])
        assert graph.root.children == [], task

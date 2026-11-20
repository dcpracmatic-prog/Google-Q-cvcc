"""Huecos H7, H8, H12, H13 y H20 (lado pipeline) — auditoría MORPH/JSON.

Cada test mide con números, no con promesas:
- H7: tunnel_candidate filtra RULES por bloque (target) y por regla.
- H8: el gancho verify del túnel usa el filtro de integridad existente.
- H12: el túnel actualiza toffoli/t_count (invsqrt) y Ttot/Qtot (química),
  así que estimate_S ve la mejora en las tres tareas.
- H13: Pipeline.run() tunela antes del proxy cuando hay tunnel_engine.
- H20: el mejor visto sube el listón en caliente (best_S y gate.current).
"""
from __future__ import annotations

import pytest

from auto_mvp.morph_tunnel import RULES, ReplacementRule
from auto_mvp.pipeline import Pipeline, PromotionGate
from auto_mvp.proxy import MetadataProxy, estimate_S
from auto_mvp.qualtran_bridge import Block, CallGraph
from auto_mvp.vqcc import dfthcsos_spec, dqi_spec, invsqrt_spec
from auto_mvp.vqcc.costs import s_chem, s_dqi

EPS = 0.001188


def _graph(root_T: float, root_Q: int, children: list[str]) -> dict:
    root = Block(name="root", kind="root", t_count=root_T, qubits=root_Q,
                 children=[(Block(name=c, kind=c), 1) for c in children])
    return CallGraph(root=root, source="manual").to_dict()


def _pipe(tmp, spec, meta_mvp: float = 30.0, tunnel_engine=None) -> Pipeline:
    return Pipeline(proxy=MetadataProxy(spec=spec, margin=0.10),
                    gate=PromotionGate(meta_mvp),
                    runs_dir=tmp / "runs",
                    tunnel_engine=tunnel_engine)


def _cand(task: str, metrics: dict, graph: dict) -> dict:
    return {"name": "c", "kind": "candidate",
            "meta": {"task": task, "metrics": dict(metrics)},
            "metrics": dict(metrics), "call_graph": graph}


# --- H7: filtro por bloque y por regla ---

def _both_graph() -> dict:
    # Grafo con los dos bloques atacables: chien y multiplier.
    return _graph(1_511_522, 1_414, ["chien", "multiplier"])


def _dqi_metrics() -> dict:
    return {"Q": 1_414, "T": 1_511_522, "eps_plus": EPS}


def test_h7_filter_by_block_chien(tmp_path):
    pipe = _pipe(tmp_path, dqi_spec(), tunnel_engine=RULES)
    cand, res = pipe.tunnel_candidate(
        _cand("dqi", _dqi_metrics(), _both_graph()), block="chien")
    assert [m["rule"] for m in res.as_dict()["moves"]] == ["chien-montgomery-b17"]
    assert res.final_T == 1_315_731  # 1,511,522 - 195,791 (medido)
    assert cand["metrics"]["T"] == 1_315_731


def test_h7_filter_by_block_multiplier(tmp_path):
    pipe = _pipe(tmp_path, dqi_spec(), tunnel_engine=RULES)
    cand, res = pipe.tunnel_candidate(
        _cand("dqi", _dqi_metrics(), _both_graph()), block="multiplier")
    assert [m["rule"] for m in res.as_dict()["moves"]] == ["multiplier-toom4"]
    delta_toom4 = (1.923348e13 - 1.99836e13) / (1.22901 * 1899 ** 2)
    assert res.final_T == pytest.approx(1_511_522 + delta_toom4)


def test_h7_filter_by_rule_name(tmp_path):
    pipe = _pipe(tmp_path, dqi_spec(), tunnel_engine=RULES)
    _, res = pipe.tunnel_candidate(
        _cand("dqi", _dqi_metrics(), _both_graph()),
        rule="multiplier-toom4")
    assert [m["rule"] for m in res.as_dict()["moves"]] == ["multiplier-toom4"]


def test_h7_no_filter_applies_all_rules(tmp_path):
    # Sin block ni rule, el comportamiento actual no cambia: las dos
    # reglas aplican (greedy: Montgomery y luego Toom-4).
    pipe = _pipe(tmp_path, dqi_spec(), tunnel_engine=RULES)
    _, res = pipe.tunnel_candidate(_cand("dqi", _dqi_metrics(), _both_graph()))
    assert [m["rule"] for m in res.as_dict()["moves"]] == [
        "chien-montgomery-b17", "multiplier-toom4"]
    assert res.final_T == pytest.approx(1_146_482.28, rel=1e-6)


def test_h7_unknown_block_tunnels_nothing(tmp_path):
    pipe = _pipe(tmp_path, dqi_spec(), tunnel_engine=RULES)
    cand, res = pipe.tunnel_candidate(
        _cand("dqi", _dqi_metrics(), _both_graph()), block="unextract")
    assert res.moves == []
    assert cand["metrics"]["T"] == 1_511_522  # candidato intacto


# --- H8: gancho de integridad del túnel ---

def _bm_candidate() -> dict:
    return _cand("dqi", _dqi_metrics(), _graph(1_511_522, 1_414, ["chien"]))


def test_h8_bad_integrity_evidence_vetoes_tunnel(tmp_path):
    # Evidencia que NO pasa IntegrityFilter (kind proyección, sin
    # circuito): el túnel se descarta entero.
    pipe = _pipe(tmp_path, dqi_spec(), tunnel_engine=RULES)
    cand = _bm_candidate()
    cand["integrity"] = {"kind": "projection"}
    cand2, res = pipe.tunnel_candidate(cand)
    assert res.moves == []
    assert cand2["metrics"]["T"] == 1_511_522


def test_h8_no_integrity_evidence_tunnels(tmp_path):
    # Sin evidencia, el túnel pasa (solo se exige la estructura del
    # grafo): el comportamiento actual no se rompe.
    pipe = _pipe(tmp_path, dqi_spec(), tunnel_engine=RULES)
    _, res = pipe.tunnel_candidate(_bm_candidate())
    assert len(res.moves) == 1
    assert res.final_T == 1_315_731


# --- H12: métricas por tarea ---

def test_h12_invsqrt_updates_toffoli_and_t_count(tmp_path):
    rule = ReplacementRule(name="test-achica", target="chien",
                           replacement="chien-fast", delta_T=-100.0,
                           evidence="test")
    pipe = _pipe(tmp_path, invsqrt_spec(), tunnel_engine=[rule])
    metrics = {"Q": 62, "toffoli": 1000, "t_count": 1000, "C": 1250,
               "rotations": 0}
    cand, res = pipe.tunnel_candidate(
        _cand("invsqrt", metrics, _graph(1000, 62, ["chien"])))
    assert res.final_T == 900
    assert cand["metrics"]["toffoli"] == 900
    assert cand["metrics"]["t_count"] == 900
    assert cand["metrics"]["C"] == pytest.approx(900 + 900 / 4.0)
    assert cand["metrics"]["T"] == 900
    from auto_mvp.proxy import CandidateMeta
    before = estimate_S(CandidateMeta(task="invsqrt", metrics=metrics))
    after = estimate_S(CandidateMeta(**cand["meta"]))
    assert before == 77_500.0 and after == 69_750.0  # S ve la mejora


def test_h12_chem_updates_ttot_qtot_lambda_untouched(tmp_path):
    rule = ReplacementRule(name="test-achica", target="chien",
                           replacement="chien-fast", delta_T=-1000.0,
                           evidence="test")
    pipe = _pipe(tmp_path, dfthcsos_spec(), tunnel_engine=[rule])
    metrics = {"lambda_eff": 49.3014, "Ttot": 93_237, "Qtot": 730}
    cand, res = pipe.tunnel_candidate(
        _cand("dfthcsos", metrics, _graph(93_237, 730, ["chien"])))
    assert res.final_T == 92_237
    assert cand["metrics"]["Ttot"] == 92_237
    assert cand["metrics"]["Qtot"] == 730
    assert cand["metrics"]["lambda_eff"] == 49.3014  # no se reentrena
    from auto_mvp.proxy import CandidateMeta
    before = estimate_S(CandidateMeta(task="dfthcsos", metrics=metrics))
    after = estimate_S(CandidateMeta(**cand["meta"]))
    assert after == pytest.approx(s_chem(49.3014, 92_237, 730))
    assert after < before  # 3.3196e9 < 3.3556e9


def test_h12_dqi_still_updates_T_Q(tmp_path):
    pipe = _pipe(tmp_path, dqi_spec(), tunnel_engine=RULES)
    cand, _ = pipe.tunnel_candidate(_bm_candidate())
    assert cand["metrics"]["T"] == 1_315_731
    assert cand["metrics"]["Q"] == 1_414


# --- H13: paso túnel en Pipeline.run() ---

def test_h13_run_tunnels_before_proxy(tmp_path):
    pipe = _pipe(tmp_path, dqi_spec(), meta_mvp=2.0, tunnel_engine=RULES)
    pipe.best_S = {"dqi": 3.714e12}  # sin túnel S=3.714e12 no pasa el proxy
    res = pipe.run(iter([_bm_candidate()]))
    assert res.tunneled == 1
    assert res.promoted == 1
    assert len(pipe.trials_log[0]["tunnel"]["moves"]) == 1


def test_h13_run_without_engine_has_no_tunnel_step(tmp_path):
    pipe = _pipe(tmp_path, dqi_spec(), meta_mvp=2.0)  # sin tunnel_engine
    pipe.best_S = {"dqi": 3.714e12}
    res = pipe.run(iter([_bm_candidate()]))
    assert res.tunneled == 0
    assert res.proxy_rejected == 1  # sin túnel no pasa el proxy
    assert "tunnel" not in pipe.trials_log[0]


# --- H20: trinquete del mejor en caliente ---

def test_h20_best_ratchets_during_run(tmp_path):
    # A mejora (S~2.999e12, GM~11.99 < meta 30: no promueve, pero el
    # mejor SÍ sube el listón). B es mejor que el mejor INICIAL
    # (3.198e12 < 3.714e12*0.9) pero peor que A con margen: sin
    # trinquete pasaría el proxy; con trinquete, no.
    pipe = _pipe(tmp_path, dqi_spec(), meta_mvp=30.0)
    pipe.best_S = {"dqi": 3.714e12}
    a = _cand("dqi", {"Q": 1_414, "T": 1_220_280, "eps_plus": EPS},
              _graph(1_220_280, 1_414, []))
    b = _cand("dqi", {"Q": 1_414, "T": 1_301_632, "eps_plus": EPS},
              _graph(1_301_632, 1_414, []))
    s_a = s_dqi(1_414, 1_220_280, EPS)
    s_b = s_dqi(1_414, 1_301_632, EPS)
    assert s_b < 3.714e12 * 0.9  # B pasaría contra el mejor inicial
    assert s_b > s_a * 0.9  # ...pero no contra A con margen
    res = pipe.run(iter([a, b]))
    assert res.screened == 2
    assert res.gate_rejected == 1  # A: mejora pero no llega a la meta
    assert res.proxy_rejected == 1  # B: lo para el trinquete, no la puerta
    assert res.promoted == 0
    assert pipe.best_S["dqi"] == pytest.approx(s_a)
    assert pipe.gate.current["dqi"] == pytest.approx(s_a)

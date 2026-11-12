"""Tests de AUTO_MVP v1.1.0: el mutador autónomo (familias D y K).

El lazo ya no depende de un proponente externo: el Mutator genera
candidatos mutando la semilla con las cuatro estrategias (morph,
window, tunnel Lévy, mwis) y el pipeline los criba y promueve.
Números medidos: BM+Forney T=1,511,522 -> Montgomery b=17 T=1,315,731
(S 3.714e12 -> 3.2331e12, R=1.22901, eps_plus=0.001188).
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auto_mvp import MetadataProxy, PromotionGate
from auto_mvp.morph_tunnel import ReplacementRule
from auto_mvp.mutator import Mutator
from auto_mvp.pipeline import Pipeline
from auto_mvp.qualtran_bridge import Block, CallGraph
from auto_mvp.vqcc import dqi_spec

EPS = 0.001188


def _bm_graph() -> CallGraph:
    """La semilla BM+Forney: T=1,511,522, Q=1,414, con hijos chien y multiplier."""
    chien = Block(name="chien", kind="chien", t_count=400_000, qubits=200)
    mult = Block(name="multiplier", kind="multiplier", t_count=300_000, qubits=300)
    root = Block(name="bm-forney", kind="dqi", t_count=1_511_522,
                 qubits=1_414, children=[(chien, 1), (mult, 1)])
    return CallGraph(root=root, source="cost_model")


def _base_metrics() -> dict:
    return {"Q": 1414, "T": 1_511_522, "eps_plus": EPS}


def test_mutator_morph_chien_montgomery():
    """La regla chien-montgomery-b17 da el número medido (T=1,315,731)."""
    mut = Mutator(_bm_graph(), "dqi", _base_metrics(), seed=42)
    cands = list(mut.propose(6))
    assert cands, "el mutador no propuso nada"
    mont = [c for c in cands if c["metrics"]["T"] == 1_315_731]
    assert mont, [c["metrics"]["T"] for c in cands]
    # El S estimado es el medido de Montgomery b=17 (3.2331e12).
    s = mont[0]["metrics"]
    assert abs(s["Q"] - 1414) < 1e-9
    # S = R * Q^2 * T con R(0.001188) = 1.22901
    from auto_mvp.vqcc.costs import s_dqi
    assert abs(s_dqi(1414, 1_315_731, EPS) - 3.2331e12) / 3.2331e12 < 1e-3
    # El candidato trae el formato del pipeline.
    c = mont[0]
    assert c["kind"] == "candidate" and c["meta"].task == "dqi"
    assert c["call_graph"]["root"]["t_count"] == 1_315_731
    assert c["source"]["strategy"] in ("morph", "window", "tunnel", "mwis")


def test_mutator_mwis_resuelve_conflicto():
    """Dos reglas sobre el mismo bloque: MWIS elige la de mayor ganancia."""
    rules = [
        ReplacementRule(name="r-chien-a", target="chien", replacement="a",
                        delta_T=-100_000.0, delta_Q=0.0, scope="block",
                        evidence="test"),
        ReplacementRule(name="r-chien-b", target="chien", replacement="b",
                        delta_T=-50_000.0, delta_Q=0.0, scope="block",
                        evidence="test"),
    ]
    mut = Mutator(_bm_graph(), "dqi", _base_metrics(), rules=rules, seed=7)
    moves = mut._mwis_moves(mut.current)
    assert len(moves) == 1
    assert moves[0].rule_name == "r-chien-a"
    assert moves[0].delta_T == -100_000.0
    assert moves[0].graph.total_T() == 1_411_522


def test_mutator_determinista_misma_semilla():
    """Misma semilla -> misma secuencia de candidatos."""
    a = [c["name"] for c in Mutator(_bm_graph(), "dqi", _base_metrics(), seed=3).propose(8)]
    b = [c["name"] for c in Mutator(_bm_graph(), "dqi", _base_metrics(), seed=3).propose(8)]
    assert a == b and len(a) > 0


def test_mutator_pipeline_promueve_montgomery():
    """El mutador alimenta el pipeline y Montgomery se promueve.

    La semilla es BM+Forney (S 3.714e12): el estado del pipeline se
    siembra con ese S, así el proxy mide la mejora real del mutador
    (3.2331e12, -13%) y no contra el mejor envío (3.7676e11, que
    Montgomery no bate y el proxy rechaza con razón). El registro de
    reglas se limita a chien-montgomery-b17 para que el primer
    candidato sea Montgomery (con el registro completo, el primer
    candidato puede ser otra regla y la meta 2.0 para la corrida)."""
    from auto_mvp.morph_tunnel import RULES
    spec = dqi_spec()
    with tempfile.TemporaryDirectory() as d:
        runs = Path(d) / "r1"
        runs.mkdir(parents=True)
        (runs / "state.json").write_text(
            '{"best_S": {"dqi": 3714000000000.0}}', encoding="utf-8")
        proxy = MetadataProxy(spec, hard_caps={"max_qubits": 2000}, margin=0.10)
        pipe = Pipeline(proxy, PromotionGate(2.0), runs_dir=runs)
        mut = Mutator(_bm_graph(), "dqi", _base_metrics(),
                      rules=[RULES[0]], seed=42)
        res = pipe.run(mut.propose(6))
        assert res.promoted >= 1, res
        # El mejor registro de la corrida es Montgomery (S 3.2331e12).
        assert res.best is not None and abs(
            res.best["S"]["dqi"] - 3.2331e12) / 3.2331e12 < 1e-3, res.best
        # El ledger de la guía NO reemplaza el mejor envío (3.7676e11):
        # Montgomery mejora la semilla, pero no bate el mejor. Solo mejora.
        assert pipe.ledger.best()["dqi"]["S"] == 3.7676e11


def test_mutator_pipeline_rechaza_contra_mejor_envio():
    """Contra el mejor envío (3.7676e11) el proxy rechaza a Montgomery
    con razón: el mutador mejora la semilla, pero no bate el mejor."""
    spec = dqi_spec()
    with tempfile.TemporaryDirectory() as d:
        proxy = MetadataProxy(spec, hard_caps={"max_qubits": 2000}, margin=0.10)
        pipe = Pipeline(proxy, PromotionGate(2.0), runs_dir=Path(d) / "r2")
        mut = Mutator(_bm_graph(), "dqi", _base_metrics(), seed=42)
        res = pipe.run(mut.propose(6))
        assert res.promoted == 0 and res.proxy_rejected >= 1, res


def test_mutator_no_inventa_costo():
    """El eps_plus se hereda de la semilla; el mutador no lo toca."""
    mut = Mutator(_bm_graph(), "dqi", _base_metrics(), seed=42)
    for c in mut.propose(6):
        assert c["metrics"]["eps_plus"] == EPS
        assert c["metrics"]["T"] <= 1_511_522


def test_cli_mutate(tmp_path):
    """La CLI mutate genera candidatos (Montgomery, T=1,315,731)."""
    import json
    import subprocess
    import sys
    data = {"seed_graph": _bm_graph().to_dict(), "task": "dqi",
            "base_metrics": _base_metrics()}
    inp = tmp_path / "semilla.json"
    inp.write_text(json.dumps(data), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, "-m", "auto_mvp.cli", "mutate", "--in", str(inp),
         "--n", "2", "--seed", "42"],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]))
    assert r.returncode == 0, r.stderr[-1000:]
    out = json.loads(r.stdout)
    assert out["n"] >= 1
    assert any(c["metrics"]["T"] == 1_315_731 for c in out["candidates"])

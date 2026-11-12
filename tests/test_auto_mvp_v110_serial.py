"""Tests de AUTO_MVP v1.1.0: orquestación en serie con compensación global.

La combinación llega aunque una tarea se quede rezagada, si las
otras dos compensan: la aceptación es la GM combinada, no por tarea.
Números: la semilla del ledger es el mejor envío (GM 23.94676). Con
objetivo 20.00, la combinación YA llega sin correr nada (la base en
cero); con objetivo 30.00, no llega y la compensación no se acepta.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auto_mvp.qualtran_bridge import Block, CallGraph
from auto_mvp.serial import run_serial

EPS = 0.001188


def _bm_graph() -> CallGraph:
    chien = Block(name="chien", kind="chien", t_count=400_000, qubits=200)
    mult = Block(name="multiplier", kind="multiplier", t_count=300_000, qubits=300)
    root = Block(name="bm-forney", kind="dqi", t_count=1_511_522,
                 qubits=1_414, children=[(chien, 1), (mult, 1)])
    return CallGraph(root=root, source="cost_model")


def test_serial_base_llega_a_20():
    """La base en cero (mejor envío) ya llega a 20.00: compensación aceptada."""
    with tempfile.TemporaryDirectory() as d:
        res = run_serial(
            [{"task": "dqi", "seed_graph": _bm_graph(),
              "base_metrics": {"Q": 1414, "T": 1_511_522, "eps_plus": EPS},
              "n": 2}],
            target_gm=20.0, runs_dir=Path(d) / "runs")
        assert res["reached"] is True, res
        assert abs(res["gm"] - 23.94676) / 23.94676 < 1e-4, res["gm"]
        assert res["compensation"]["accepted"] is True
        assert res["audit_zip"] != ""
        assert Path(res["audit_zip"]).exists()


def test_serial_no_llega_a_30():
    """A 30.00 no llega: la compensación NO se acepta y no hay ZIP."""
    with tempfile.TemporaryDirectory() as d:
        res = run_serial(
            [{"task": "dqi", "seed_graph": _bm_graph(),
              "base_metrics": {"Q": 1414, "T": 1_511_522, "eps_plus": EPS},
              "n": 2}],
            target_gm=30.0, runs_dir=Path(d) / "runs")
        assert res["reached"] is False, res
        assert res["compensation"]["accepted"] is False
        assert res["audit_zip"] == ""
        assert len(res["per_task"]) == 1
        assert res["per_task"][0]["task"] == "dqi"


def test_serial_compensacion_registra_rezago():
    """Cuando llega, la compensación registra qué tarea se rezaga y
    cuáles compensan (con la base en cero a 20.00, ninguna se rezaga
    porque el mejor envío ya supera el objetivo en las tres)."""
    with tempfile.TemporaryDirectory() as d:
        res = run_serial(
            [{"task": "dqi", "seed_graph": _bm_graph(),
              "base_metrics": {"Q": 1414, "T": 1_511_522, "eps_plus": EPS},
              "n": 2}],
            target_gm=20.0, runs_dir=Path(d) / "runs")
        assert res["compensation"]["accepted"] is True
        assert res["compensation"]["lagging_tasks"] == []
        assert len(res["compensation"]["compensating_tasks"]) == 3


def test_cli_serial_y_notebook(tmp_path):
    """La CLI serial llega a 20.00 y exporta el ZIP; la CLI notebook
    escribe el .ipynb con los tres módulos ganadores."""
    import json
    import subprocess
    import sys
    repo = Path(__file__).resolve().parents[1]
    runs = tmp_path / "runs"
    jobs = {"jobs": [{"task": "dqi", "seed_graph": _bm_graph().to_dict(),
                      "base_metrics": {"Q": 1414, "T": 1_511_522,
                                       "eps_plus": EPS}, "n": 2}],
            "target_gm": 20.0}
    inp = tmp_path / "trabajos.json"
    inp.write_text(json.dumps(jobs), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, "-m", "auto_mvp.cli", "serial", "--in", str(inp),
         "--runs-dir", str(runs), "--target", "20"],
        capture_output=True, text=True, cwd=str(repo))
    assert r.returncode == 0, r.stderr[-1000:]
    out = json.loads(r.stdout)
    assert out["reached"] is True and out["audit_zip"] != ""
    nb = tmp_path / "ganadores.ipynb"
    r2 = subprocess.run(
        [sys.executable, "-m", "auto_mvp.cli", "notebook",
         "--runs-dir", str(runs), "--out", str(nb), "--target", "20"],
        capture_output=True, text=True, cwd=str(repo))
    assert r2.returncode == 0, r2.stderr[-1000:]
    out2 = json.loads(r2.stdout)
    assert Path(out2["path"]).exists()
    nb_data = json.loads(Path(out2["path"]).read_text(encoding="utf-8"))
    assert nb_data["nbformat"] == 4 and len(nb_data["cells"]) == 5

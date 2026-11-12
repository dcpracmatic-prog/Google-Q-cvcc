"""AUTO_MVP v1.1.0 — exportar los ganadores a un Notebook ejecutable.

Verifica el entregable final del Solucionador Morfológico: un
.ipynb nbformat 4 con los tres módulos ganadores, ejecutable en
orden, que recomputa la GM desde los tres S.

- El ledger + dataset falsos: invsqrt y dqi con module.py real en
  el dataset (vía export_candidate), química sin módulo (el mejor
  envío sembrado, fallback del ledger).
- El .ipynb es JSON válido nbformat 4: 1 markdown + 3 celdas de
  tarea + 1 de verificación. Las celdas de tarea incrustan el
  module.py (o el component.json como fallback).
- El notebook se ejecuta en orden (exec por celda, mismo
  namespace): la GM que imprime la celda final coincide con
  combine() del ledger.
"""
from __future__ import annotations

import io
import json
import math
import re
from contextlib import redirect_stdout

from auto_mvp.combiner import TASKS, BestLedger, combine
from auto_mvp.dataset import export_candidate
from auto_mvp.notebook import export_winner_notebook
from auto_mvp.vqcc.contracts import BEST_SUBMISSION_S, REFERENCE_S
from auto_mvp.vqcc.costs import s_dqi, s_invsqrt

EPS = 0.001188


def _gm_with(task, S):
    """La GM que el module.py recomputa: las otras dos tareas en el
    mejor envío (la misma fórmula del template de dataset.py)."""
    scores = dict(BEST_SUBMISSION_S)
    scores[task] = S
    return math.exp(sum(math.log(REFERENCE_S[t] / scores[t])
                        for t in TASKS) / len(TASKS))


def _build(tmp_path):
    """Ledger + dataset falsos: invsqrt y dqi con módulo, química no."""
    runs = tmp_path / "runs"
    led = BestLedger(runs / "best_per_task.json")
    s_inv = s_invsqrt(62, 1000, 488)  # 69,564.0 < 100,568.5 (semilla)
    led.record("invsqrt", {
        "name": "invsqrt-mejor", "kind": "candidate", "S": s_inv,
        "metrics": {"Q": 62, "toffoli": 1000, "t_count": 488},
        "artifact_name": "invsqrt-mejor", "run_id": "run-test",
        "iteration": 1, "measured": False})
    s_d = s_dqi(1414, 81393, EPS)  # ~2.0e11 < 3.7676e11 (semilla)
    led.record("dqi", {
        "name": "dqi-mejor", "kind": "candidate", "S": s_d,
        "metrics": {"Q": 1414, "T": 81393, "eps_plus": EPS},
        "artifact_name": "dqi-mejor", "run_id": "run-test",
        "iteration": 2, "measured": False})
    dataset_root = runs / "dataset"
    for task, name, S, metrics in (
            ("invsqrt", "invsqrt-mejor", s_inv,
             {"Q": 62, "toffoli": 1000, "t_count": 488}),
            ("dqi", "dqi-mejor", s_d,
             {"Q": 1414, "T": 81393, "eps_plus": EPS})):
        export_candidate(
            {"artifact_name": name, "kind": "candidate", "task": task,
             "iteration": 1, "gm": _gm_with(task, S), "S": {task: S},
             "ratios": {}, "metrics": metrics, "call_graph": None,
             "integrity": None, "source": {}, "source_commit": "test"},
            runs / f"i1-{S:.0f}", dataset_root)
    return led, dataset_root


def _run_cells(cells):
    """Ejecuta las celdas de código en orden, mismo namespace."""
    ns: dict = {}
    buf = io.StringIO()
    with redirect_stdout(buf):
        for c in cells:
            exec("".join(c["source"]), ns)
    return buf.getvalue()


def test_notebook_structure_module_and_gm(tmp_path):
    led, dataset_root = _build(tmp_path)
    out = tmp_path / "ganadores.ipynb"
    res = export_winner_notebook(led, dataset_root, out, target_gm=30.0)
    assert res["path"] == str(out)
    assert res["files"] == [str(out)]
    assert res["tasks"] == list(TASKS)
    assert res["target"] == 30.0
    assert res["gm"] == combine(led, 30.0)["gm"]
    assert res["reached"] is True  # GM ~37.33 con los dos mejores
    nb = json.loads(out.read_text(encoding="utf-8"))
    assert nb["nbformat"] == 4
    assert nb["nbformat_minor"] >= 0
    cells = nb["cells"]
    assert len(cells) == 5
    assert cells[0]["cell_type"] == "markdown"
    assert [c["cell_type"] for c in cells[1:]] == ["code"] * 4
    assert "30.00" in "".join(cells[0]["source"])
    # Las celdas de tarea incrustan el module.py del dataset.
    src_inv = "".join(cells[1]["source"])
    src_dqi = "".join(cells[2]["source"])
    assert "def verify()" in src_inv and "invsqrt-mejor" in src_inv
    assert "def verify()" in src_dqi and "dqi-mejor" in src_dqi
    # Química no tiene módulo: fallback del ledger (component.json).
    src_chem = "".join(cells[3]["source"])
    assert "quimica-publica" in src_chem and "sin module.py" in src_chem
    # El notebook se ejecuta en orden; la GM final coincide con combine().
    out_text = _run_cells(cells[1:])
    m = re.search(r"GM recomputada = ([0-9.]+)", out_text)
    assert m, out_text
    gm = combine(led, 30.0)["gm"]
    assert abs(float(m.group(1)) - gm) < 1e-4
    assert "LLEGA al objetivo 30.00" in out_text


def test_notebook_all_fallback_executes(tmp_path):
    """Solo la semilla (sin dataset): tres fallbacks, GM 23.94676."""
    led = BestLedger(tmp_path / "runs" / "best_per_task.json")
    out = tmp_path / "base.ipynb"
    res = export_winner_notebook(led, tmp_path / "runs" / "dataset", out)
    assert res["tasks"] == list(TASKS)
    assert res["reached"] is True  # target = la GM de la semilla
    nb = json.loads(out.read_text(encoding="utf-8"))
    assert len(nb["cells"]) == 5
    assert all("sin module.py" in "".join(c["source"])
               for c in nb["cells"][1:4])
    out_text = _run_cells(nb["cells"][1:])
    m = re.search(r"GM recomputada = ([0-9.]+)", out_text)
    assert m, out_text
    assert abs(float(m.group(1)) - 23.94676) < 1e-3

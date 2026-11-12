"""AUTO_MVP v1.5.0 — Notebook de ganadores + compensación global en run_auto.

El corredor entrega, al llegar a la meta, el ZIP + el Notebook
(.ipynb) con los tres módulos ganadores + el balance global de la
compensación (qué tarea va rezagada y cuál compensa). Los
aceleradores nativos se venden en el repo (auto_mvp/native/).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_mvp.accel import available, dijkstra, spmm_csr_dense, swar_friction
from auto_mvp.auto import run_auto
from auto_mvp.combiner import BestLedger
from auto_mvp.proxy import CandidateMeta, estimate_S
from auto_mvp.seeds import default_seeds
from auto_mvp.serial import compensation_record


def _notebook_text(path: str | Path) -> str:
    nb = json.loads(Path(path).read_text(encoding="utf-8"))
    assert nb["nbformat"] == 4
    parts = []
    for cell in nb["cells"]:
        src = cell.get("source", [])
        parts.append("".join(src) if isinstance(src, list) else str(src))
    return "\n".join(parts), nb


def _seeded_ledger(tmp_path: Path) -> BestLedger:
    """El ledger con la base conocida (las semillas medidas).

    GM de las semillas ≈ 5.14 (DQI 6.57×, invsqrt 20.65×, química
    1.0×): llega a 1.5, no llega a 30.
    """
    led = BestLedger(tmp_path / "best.json")
    for task, seed in default_seeds().items():
        metrics = dict(seed["base_metrics"])
        led.record(task, {
            "task": task, "name": f"seed:{task}", "kind": "seed",
            "S": float(estimate_S(
                CandidateMeta(task=task, metrics=metrics))),
            "ratio": 1.0, "metrics": metrics,
            "artifact_name": None, "run_id": "seed",
            "iteration": 0, "measured": True, "source_commit": None,
        })
    return led


def test_compensation_record_reached_all_compensating(tmp_path):
    led = _seeded_ledger(tmp_path)
    rec = compensation_record(led, 1.5)
    assert rec["accepted"] is True
    assert rec["lagging_tasks"] == []
    assert {c["task"] for c in rec["compensating_tasks"]} == {
        "dqi", "invsqrt", "dfthcsos"}


def test_compensation_record_not_reached_lagging(tmp_path):
    led = _seeded_ledger(tmp_path)
    rec = compensation_record(led, 30.0)
    assert rec["accepted"] is False
    assert rec["lagging_tasks"]
    for entry in rec["lagging_tasks"]:
        assert entry["S"] > entry["required_S"]


def test_run_auto_15_delivers_notebook_and_compensation(tmp_path):
    res = run_auto(1.5, runs_dir=tmp_path / "runs")
    assert res["reached"] is True
    assert res["rounds"] == 0
    assert res["notebook"]
    text, nb = _notebook_text(res["notebook"])
    assert len(nb["cells"]) == 5  # intro + 3 tareas + final
    for task in ("dqi", "invsqrt", "dfthcsos"):
        assert task in text
    assert "Proyectado" in text
    assert res["compensation"]["accepted"] is True
    assert Path(res["zip"]).is_file()


def test_run_auto_30_delivers_notebook_and_compensation(tmp_path):
    res = run_auto(30.0, runs_dir=tmp_path / "runs")
    assert res["reached"] is True
    assert res["gm"] == pytest.approx(30.005566491649372)
    assert res["notebook"]
    text, nb = _notebook_text(res["notebook"])
    assert len(nb["cells"]) == 5
    for task in ("dqi", "invsqrt", "dfthcsos"):
        assert task in text
    # Los tres componentes son de fuerza bruta: proyectados.
    assert res["projected"] is True
    assert "Proyectado" in text
    comp = res["compensation"]
    assert comp["accepted"] is True
    assert comp["lagging_tasks"] == []
    assert {c["task"] for c in comp["compensating_tasks"]} == {
        "dqi", "invsqrt", "dfthcsos"}
    assert Path(res["zip"]).is_file()
    assert Path(res["notebook"]).is_file()


def test_run_auto_not_reached_has_compensation_no_notebook(tmp_path):
    res = run_auto(1e9, runs_dir=tmp_path / "runs", max_rounds=1)
    assert res["reached"] is False
    assert res["notebook"] == ""
    assert res["compensation"]["accepted"] is False
    assert res["compensation"]["lagging_tasks"]


def test_accel_vendored_loads_and_matches_python(tmp_path):
    av = available()
    assert set(av) == {"spmm", "field", "swar"}
    for kind, st in av.items():
        assert st["loaded"] is True, f"{kind}: {st['reason']}"
    # Nativo == Python puro en casos chicos.
    assert spmm_csr_dense(
        [0, 2, 3], [0, 1, 0], [1.0, 2.0, 3.0],
        [[1.0, 0.0], [0.0, 1.0]], 2, 2) == [[1.0, 2.0], [3.0, 0.0]]
    assert swar_friction(0b101, 0b110) == 1
    assert dijkstra(3, [(0, 1, 1.0), (1, 2, 2.0)], 0) == [0.0, 1.0, 3.0]
    assert dijkstra(3, [(0, 1, 1.0)], 0)[2] == float("inf")

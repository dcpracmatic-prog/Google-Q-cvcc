"""AUTO_MVP v0.8.0 — dataset de trabajo: exportar e inyectar módulos.

Verifica, con números medidos, que un módulo promovido NO se queda
en métricas frías:
- El export escribe structure.json (grafo completo), module.py
  (código ejecutable, solo stdlib) y source/... en el artefacto Y
  en el dataset, con su índice.
- El module.py exportado, corrido en un proceso limpio, reproduce
  el S y la GM del record (Montgomery: S 3.2331e12, GM 11.697).
- El cargador del dataset devuelve el grafo (T total 1,315,731)
  y la ruta del código ejecutable.
- El pipeline/orquestador exporta cada promoción (exported=1) y el
  fail-closed sigue intacto: el export NO crea un submission.zip.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from auto_mvp.dataset import WorkingDataset, export_candidate, render_module
from auto_mvp.numeric_lab import fail_closed_gate
from auto_mvp.orchestrator import AdaptiveOrchestrator
from auto_mvp.pipeline import Pipeline, PromotionGate
from auto_mvp.proxy import MetadataProxy
from auto_mvp.step_plan import StepPlan
from auto_mvp.vqcc import dqi_spec

VENV_PY = sys.executable  # v2.17.11: portátil (sandbox y Kaggle)
GRAPH = {"source": "cost_model", "root": {
    "name": "dqi-bm-forney", "kind": "dqi", "t_count": 1315731, "qubits": 1414,
    "rotations": 0, "cliffords": 0,
    "children": [
        [{"name": "bm_forward", "kind": "bm_forward", "t_count": None,
          "qubits": None, "rotations": 0, "cliffords": 0, "children": []}, 1],
        [{"name": "omega", "kind": "omega", "t_count": None,
          "qubits": None, "rotations": 0, "cliffords": 0, "children": []}, 1],
        [{"name": "montgomery-b17", "kind": "montgomery-b17", "t_count": None,
          "qubits": None, "rotations": 0, "cliffords": 0, "children": []}, 1],
        [{"name": "bm_backward", "kind": "bm_backward", "t_count": None,
          "qubits": None, "rotations": 0, "cliffords": 0, "children": []}, 1]]}}
METRICS = {"Q": 1414, "T": 1315731, "eps_plus": 0.001188}
SOURCE = {"builder.py": "# constructor del módulo Montgomery b=17\n\ndef build():\n    return {'Q': 1414, 'T': 1315731}\n"}


def _record() -> dict:
    return {"iteration": 1, "gm": 11.696652711070563,
            "S": {"dqi": 3233109031095.556},
            "ratios": {"invsqrt": 20.65, "dqi": 7.546915295872942,
                       "dfthcsos": 10.27},
            "task": "dqi", "kind": "candidate",
            "meta": {"task": "dqi", "metrics": dict(METRICS)},
            "metrics": dict(METRICS), "call_graph": GRAPH,
            "source": dict(SOURCE), "source_commit": "test"}


def _run_module(path: Path) -> dict:
    r = subprocess.run([sys.executable, str(path)], capture_output=True,
                       text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_export_writes_full_structure(tmp_path):
    art = tmp_path / "runs" / "i1-11.70"
    art.mkdir(parents=True)
    (art / "manifest.json").write_text("{}", encoding="utf-8")
    out = export_candidate(_record(), art, tmp_path / "runs" / "dataset")
    assert out["has_call_graph"] is True and out["has_source"] is True
    for d in (art, tmp_path / "runs" / "dataset" / "i1-11.70"):
        assert (d / "structure.json").is_file()
        assert (d / "module.py").is_file()
        assert (d / "source" / "builder.py").is_file()
        assert (d / "source" / "builder.py").read_text() == SOURCE["builder.py"]
        st = json.loads((d / "structure.json").read_text())
        assert st["metrics"] == METRICS
        assert st["call_graph"]["root"]["t_count"] == 1315731
    idx = WorkingDataset(tmp_path / "runs" / "dataset").index()
    assert len(idx) == 1 and idx[0]["name"] == "i1-11.70"
    assert idx[0]["has_call_graph"] is True


def test_exported_module_reproduces_numbers(tmp_path):
    art = tmp_path / "runs" / "i1-11.70"
    art.mkdir(parents=True)
    (art / "manifest.json").write_text("{}", encoding="utf-8")
    out = export_candidate(_record(), art, tmp_path / "runs" / "dataset")
    # El module.py es solo stdlib: corre sin auto_mvp en el path.
    mod = Path(out["dataset_dir"]) / "module.py"
    res = _run_module(mod)
    assert res["ok"] is True, res
    assert res["has_call_graph"] is True
    assert abs(res["S"] - 3.2331e12) / 3.2331e12 < 1e-3
    assert abs(res["gm"] - 11.697) < 0.01


def test_dataset_load_returns_graph_and_code(tmp_path):
    art = tmp_path / "runs" / "i1-11.70"
    art.mkdir(parents=True)
    (art / "manifest.json").write_text("{}", encoding="utf-8")
    export_candidate(_record(), art, tmp_path / "runs" / "dataset")
    ds = WorkingDataset(tmp_path / "runs" / "dataset")
    loaded = ds.load("i1-11.70")
    assert loaded["total_T"] == 1315731.0
    assert loaded["total_Q"] == 1414
    assert loaded["metrics"] == METRICS
    assert Path(loaded["module_path"]).is_file()
    with pytest.raises(KeyError):
        ds.load("no-existe")


def test_export_without_call_graph(tmp_path):
    rec = _record()
    rec["call_graph"] = None
    rec["source"] = {}
    art = tmp_path / "runs" / "i1-11.70"
    art.mkdir(parents=True)
    (art / "manifest.json").write_text("{}", encoding="utf-8")
    out = export_candidate(rec, art, tmp_path / "runs" / "dataset")
    assert out["has_call_graph"] is False and out["has_source"] is False
    res = _run_module(Path(out["dataset_dir"]) / "module.py")
    assert res["ok"] is True and res["has_call_graph"] is False
    assert abs(res["S"] - 3.2331e12) / 3.2331e12 < 1e-3


def test_pipeline_exports_promotion(tmp_path):
    cand = {"name": "bm-forney", "kind": "candidate",
            "meta": {"task": "dqi", "metrics": {"Q": 1414, "T": 1511522,
                                                "eps_plus": 0.001188}},
            "metrics": {"Q": 1414, "T": 1511522, "eps_plus": 0.001188},
            "call_graph": {"source": "cost_model", "root": {
                "name": "dqi-bm-forney", "kind": "dqi", "t_count": 1511522,
                "qubits": 1414, "rotations": 0, "cliffords": 0,
                "children": [
                    [{"name": "bm_forward", "kind": "bm_forward",
                      "t_count": None, "qubits": None, "rotations": 0,
                      "cliffords": 0, "children": []}, 1],
                    [{"name": "omega", "kind": "omega", "t_count": None,
                      "qubits": None, "rotations": 0, "cliffords": 0,
                      "children": []}, 1],
                    [{"name": "chien", "kind": "chien", "t_count": None,
                      "qubits": None, "rotations": 0, "cliffords": 0,
                      "children": []}, 1],
                    [{"name": "bm_backward", "kind": "bm_backward",
                      "t_count": None, "qubits": None, "rotations": 0,
                      "cliffords": 0, "children": []}, 1]]}},
            "source": dict(SOURCE)}
    pipe = Pipeline(proxy=MetadataProxy(dqi_spec(), margin=0.10),
                    gate=PromotionGate(2.0), runs_dir=tmp_path / "runs",
                    time_budget_seconds=None)
    pipe.best_S = {"dqi": 3.714e12}
    orch = AdaptiveOrchestrator(pipe, StepPlan())
    res = orch.run(iter([cand]))
    assert res.promoted == 1 and res.exported == 1
    assert res.dataset_dir == str(tmp_path / "runs" / "dataset")
    ds = WorkingDataset(tmp_path / "runs" / "dataset")
    assert ds.names() == ["i1-11.70"]
    loaded = ds.load("i1-11.70")
    assert loaded["total_T"] == 1315731.0  # tunelado, no el base
    assert loaded["metrics"]["T"] == 1315731.0
    # El module.py exportado reproduce los números del artefacto.
    mod_res = _run_module(Path(loaded["module_path"]))
    assert mod_res["ok"] is True
    assert abs(mod_res["S"] - 3.2331e12) / 3.2331e12 < 1e-3
    assert abs(mod_res["gm"] - 11.697) < 0.01
    # Y el fail-closed sigue intacto: el export NO arma un submission.zip.
    assert fail_closed_gate({"invsqrt": "NOT_RUN", "dqi": "NOT_RUN",
                             "dfthcsos": "NOT_RUN"})["status"] == "NOT_CREATED"
    assert not list((tmp_path / "runs").rglob("submission.zip"))


def test_cli_export_and_mcp_export(tmp_path):
    r = subprocess.run([VENV_PY, "-m", "auto_mvp.cli", "export",
                        "--runs-dir", str(tmp_path / "runs")],
                       input=json.dumps(_record()), capture_output=True,
                       text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["has_call_graph"] is True
    assert (Path(out["dataset_dir"]) / "module.py").is_file()
    # La operación export_module por MCP da lo mismo.
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                            / "skills" / "auto-mvp-vqcc"))
    from mcp_server import handle
    resp = handle({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                   "params": {"name": "export_module",
                              "arguments": {"record": _record(),
                                            "runs_dir": str(tmp_path / "runs2")}}})
    text = json.loads(resp["result"]["content"][0]["text"])
    assert text["has_source"] is True
    assert Path(text["dataset_dir"]).is_dir()


def test_render_module_is_valid_python():
    src = render_module("i1-11.70", "candidate", "dqi")
    compile(src, "module.py", "exec")
    assert "def verify" in src and "def build" in src

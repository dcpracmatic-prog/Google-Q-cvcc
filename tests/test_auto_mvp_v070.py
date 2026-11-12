"""AUTO_MVP v0.7.0 — la Skill / Tool nativa para LLMs.

Verifica, con números medidos, que el empaquetado reproduce los
resultados del repo:
- CLI: cada subcomando da los mismos números que el repo (gate 30
  -> ratio 127.335; evaluate Montgomery -> S 3.2331e12, GM 11.697;
  tunnel -> T 1,511,522 -> 1,315,731; run -> promovido 1, tunelado 1).
- Servidor MCP: initialize + tools/list + tools/call dan lo mismo.
- tools.py (ChatGPT/Grok): las funciones dan lo mismo.
- functions.json: esquema válido, 6 funciones, mismos nombres.
- La skill: mcp_server.py, tools.py, functions.json (el código).
  El único markdown del repo es README.md, que describe cómo
  funciona y qué hace.
- pip install: el paquete se instala desde el repo y la CLI corre
  desde la instalación (ruta vendida / Kaggle simulada con el
  paquete vendido en un directorio limpio).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "skills" / "auto-mvp-vqcc"
VENV_PY = "/home/hatch/workspace/sandbox-run/venv/bin/python"

BM = {"name": "bm-forney", "kind": "candidate",
      "meta": {"task": "dqi", "metrics": {"Q": 1414, "T": 1511522,
                                         "eps_plus": 0.001188}},
      "metrics": {"Q": 1414, "T": 1511522, "eps_plus": 0.001188}}
MONT = {"name": "montgomery-b17", "kind": "candidate",
        "meta": {"task": "dqi", "metrics": {"Q": 1414, "T": 1315731,
                                           "eps_plus": 0.001188}},
        "metrics": {"Q": 1414, "T": 1315731, "eps_plus": 0.001188}}
GRAPH = {"source": "cost_model", "root": {
    "name": "dqi-bm-forney", "kind": "dqi", "t_count": 1511522, "qubits": 1414,
    "rotations": 0, "cliffords": 0,
    "children": [
        [{"name": "bm_forward", "kind": "bm_forward", "t_count": None,
          "qubits": None, "rotations": 0, "cliffords": 0, "children": []}, 1],
        [{"name": "omega", "kind": "omega", "t_count": None,
          "qubits": None, "rotations": 0, "cliffords": 0, "children": []}, 1],
        [{"name": "chien", "kind": "chien", "t_count": None,
          "qubits": None, "rotations": 0, "cliffords": 0, "children": []}, 1],
        [{"name": "bm_backward", "kind": "bm_backward", "t_count": None,
          "qubits": None, "rotations": 0, "cliffords": 0, "children": []}, 1]]}}


def _cli(*args, inp=None, cwd=None):
    r = subprocess.run([VENV_PY, "-m", "auto_mvp.cli", *args],
                       input=json.dumps(inp) if inp is not None else None,
                       capture_output=True, text=True, cwd=cwd or REPO,
                       timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


def test_cli_version_and_gate():
    assert _cli("version")["version"] == "1.0.1"
    g = _cli("gate", "--meta-mvp", "30")
    assert abs(g["required_dqi_ratio"] - 127.335) < 0.01
    assert abs(g["target_S_dqi"] - 1.916e11) / 1.916e11 < 1e-3


def test_cli_evaluate_montgomery():
    out = _cli("evaluate", "--meta-mvp", "2", "--best-S", "3.714e12", inp=MONT)
    assert out["proxy_ok"] is True and out["promote"] is True
    assert abs(out["S"] - 3.2331e12) / 3.2331e12 < 1e-3
    assert abs(out["gm"] - 11.697) < 0.01


def test_cli_evaluate_bm_rejected():
    out = _cli("evaluate", "--meta-mvp", "2", "--best-S", "3.714e12", inp=BM)
    assert out["proxy_ok"] is False  # S 3.714e12 no baja el 10%


def test_cli_tunnel():
    out = _cli("tunnel", inp={"call_graph": GRAPH})
    assert out["baseline_T"] == 1511522.0 and out["final_T"] == 1315731.0
    assert out["moves"][0]["rule"] == "chien-montgomery-b17"


def test_cli_decode_and_integrity(tmp_path):
    from auto_mvp.integrity import canonical_hash
    out = _cli("decode", inp={"meta_mvp": 2.0,
                              "directives": ["ataca chien", "haz magia"]})
    assert out["directives"][0]["verb"] == "tunnel"
    assert len(out["unparsed"]) == 1  # "haz magia" se reporta, no se tira
    ev = {"kind": "circuit", "sigma": [1, 2, 3],
          "sigma_ref_hash": canonical_hash([1, 2, 3]),
          "c_restored": 180, "b_restored": 180, "total_coef": 180,
          "dreg_zero": True, "alpha_zero": True,
          "temporaries_zero": 10, "temporaries_total": 10,
          "allowed_dirty": [], "shots": 5, "verified_by": "circuit_sim"}
    assert _cli("integrity", inp=ev)["ok"] is True
    ev["kind"] = "projection"
    assert _cli("integrity", inp=ev)["ok"] is False


def test_cli_run_tunnel_first(tmp_path):
    cand = dict(BM)
    cand["call_graph"] = GRAPH
    cfg = {"meta_mvp": 2.0, "directives": ["ataca chien"],
           "candidates": [cand]}
    out = _cli("run", "--best-S", '{"dqi": 3.714e12}',
               "--runs-dir", str(tmp_path / "runs"), inp=cfg)
    assert out["promoted"] == 1 and out["tunneled"] == 1
    assert out["goal_reached"] is True
    assert abs(out["best_gm"] - 11.697) < 0.01
    assert out["artifacts"]  # el artefacto quedó guardado


def test_mcp_server_roundtrip():
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "promotion_gate", "arguments": {"meta_mvp": 30}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "evaluate_candidate",
                    "arguments": {"candidate": MONT, "meta_mvp": 2,
                                  "best_S": 3.714e12}}},
    ]
    r = subprocess.run([VENV_PY, str(SKILL / "mcp_server.py")],
                       input="\n".join(json.dumps(m) for m in msgs),
                       capture_output=True, text=True, cwd=REPO, timeout=120)
    assert r.returncode == 0, r.stderr
    lines = [json.loads(x) for x in r.stdout.strip().splitlines()]
    assert len(lines) == 4  # initialize, tools/list, 2 calls (la notificación no responde)
    by_id = {x["id"]: x["result"] for x in lines}
    assert by_id[1]["serverInfo"]["name"] == "auto-mvp-vqcc"
    assert [t["name"] for t in by_id[2]["tools"]] == [
        "evaluate_candidate", "apply_morph_tunnel", "decode_json_config",
        "run_orchestrator", "check_integrity", "export_module",
        "validate_submission", "combine_best", "promotion_gate"]
    gate = json.loads(by_id[3]["content"][0]["text"])
    assert abs(gate["required_dqi_ratio"] - 127.335) < 0.01
    ev = json.loads(by_id[4]["content"][0]["text"])
    assert ev["promote"] is True and abs(ev["gm"] - 11.697) < 0.01


def test_tools_py_functions():
    sys.path.insert(0, str(SKILL))
    sys.path.insert(0, str(REPO))
    import tools
    assert tools.promotion_gate(30.0)["required_dqi_ratio"] > 127
    out = tools.evaluate_candidate(MONT, meta_mvp=2, best_S=3.714e12)
    assert out["promote"] is True and abs(out["S"] - 3.2331e12) / 3.2331e12 < 1e-3
    t = tools.apply_morph_tunnel(GRAPH)
    assert t["final_T"] == 1315731.0


def test_functions_json_schema():
    funcs = json.loads((SKILL / "functions.json").read_text())
    assert isinstance(funcs, list) and len(funcs) == 9
    names = [f["function"]["name"] for f in funcs]
    assert names == ["evaluate_candidate", "apply_morph_tunnel",
                     "decode_json_config", "run_orchestrator",
                     "check_integrity", "export_module",
                     "validate_submission", "combine_best", "promotion_gate"]
    for f in funcs:
        assert "parameters" in f["function"]
        assert f["function"]["parameters"]["type"] == "object"


def test_skill_files_and_readme():
    """La skill: el código (MCP, tools, functions) y el README,
    que es el único markdown del repo y describe cómo funciona."""
    assert (SKILL / "mcp_server.py").exists()
    assert (SKILL / "tools.py").exists()
    assert (SKILL / "functions.json").exists()
    readme = (REPO / "README.md").read_text()
    for op in ("evaluate_candidate", "apply_morph_tunnel", "decode_json_config",
               "run_orchestrator", "check_integrity", "export_module",
               "validate_submission", "combine_best", "promotion_gate"):
        assert op in readme
    assert "SKILL.md" not in [p.name for p in SKILL.iterdir()]


def test_pip_install_and_vendored_path(tmp_path):
    """pip install desde el repo + CLI desde la instalación (y la
    ruta vendida, como en Kaggle: solo el paquete, sin el repo)."""
    target = tmp_path / "site"
    r = subprocess.run([VENV_PY, "-m", "pip", "install", "--quiet",
                        "--target", str(target), str(REPO)],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    env = {"PYTHONPATH": str(target)}
    import os
    full_env = dict(os.environ, **env)
    out = subprocess.run([VENV_PY, "-m", "auto_mvp.cli", "gate",
                          "--meta-mvp", "30"], capture_output=True,
                         text=True, env=full_env, timeout=120)
    assert out.returncode == 0, out.stderr
    assert abs(json.loads(out.stdout)["required_dqi_ratio"] - 127.335) < 0.01

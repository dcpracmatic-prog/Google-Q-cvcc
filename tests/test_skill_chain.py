"""La Skill/Tool run_vqcc_chain — la cadena completa en una llamada.

Cada test mide con números, no con promesas:
- el plan por defecto es tunnel -> proxy -> gate -> verify -> compile
  -> observe (verify antes de compile: el veto bloquea compilar);
- la directiva JSON se parsea y el túnel aplica la regla con evidencia
  medida (chien: T 1,511,522 -> 1,315,731, delta -195,791);
- sin artefacto, la verificación es solo local (PASS_LOCAL, nunca un
  PASS oficial inventado);
- con artefacto real, la verificación es oficial (fixture del
  portfolio invsqrt, Q=44, sha d0227f3c, pantalla max_x=512);
- con artefacto inexistente, el veto es fail-closed
  (VETO_SIN_VERIFICADOR);
- las directivas no parseadas quedan en "unparsed" con su motivo.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from auto_mvp.operations import OPERATIONS, run_vqcc_chain
from auto_mvp.seeds import _dqi_seed_graph

EPS = 0.001188
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "portfolio" / "invsqrt.kmb"


def _bm_candidate() -> dict:
    return {
        "name": "bm-forney", "kind": "candidate",
        "meta": {"task": "dqi",
                 "metrics": {"Q": 1414, "T": 1511522, "eps_plus": EPS}},
        "metrics": {"Q": 1414, "T": 1511522, "eps_plus": EPS},
        "call_graph": _dqi_seed_graph().to_dict(),
    }


def _chain_config() -> dict:
    return {"directives": ["tunela chien con chien-montgomery-b17",
                           "sube la meta a 2"]}


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_chain_default_plan_tunnels_and_promotes_local(tmp_path):
    out = run_vqcc_chain(_chain_config(), [_bm_candidate()],
                         runs_dir=tmp_path / "runs",
                         best_S={"dqi": 3.714e12})
    assert out["version"] == "2.17.21"
    assert out["plan_order"] == ["tunnel", "proxy", "gate", "verify",
                                 "compile", "observe"]
    assert out["verify_before_compile"] is True
    assert out["steps_from_config"] is False
    assert out["promoted"] == 1 and out["tunneled"] == 1
    assert out["screened"] == 1 and out["unparsed"] == []
    assert len(out["tunnel"]) == 1
    tun = out["tunnel"][0]
    assert tun["baseline_T"] == 1511522.0
    assert tun["final_T"] == 1315731.0  # delta -195,791 (medido)
    assert [m["rule"] for m in tun["moves"]] == ["chien-montgomery-b17"]
    # Sin artefacto: la verificación es solo local, nunca oficial.
    assert len(out["verify"]) == 1
    assert out["verify"][0]["official"] is False
    assert out["verify"][0]["ok"] is True
    assert out["verdict"] == "PASS_LOCAL"


def test_chain_unparsed_directive_reported_not_dropped(tmp_path):
    cfg = {"directives": ["tunela chien con chien-montgomery-b17",
                          "sube la meta a 2",
                          "haz magia cuántica"]}
    out = run_vqcc_chain(cfg, [_bm_candidate()],
                         runs_dir=tmp_path / "runs",
                         best_S={"dqi": 3.714e12})
    assert len(out["unparsed"]) == 1
    assert out["unparsed"][0]["raw"] == "haz magia cuántica"
    assert out["unparsed"][0]["reason"]
    # La cadena corre igual; la directiva mala no mata el resultado.
    assert out["verdict"] == "PASS_LOCAL"
    assert out["promoted"] == 1


def test_chain_config_steps_respected_no_verify(tmp_path):
    # Mismos pasos que el plan por defecto pero sin verify: el túnel
    # sigue corriendo primero (sin él, el proxy rechaza: el S sin
    # tunelar, 3.71422e12, no baja del mejor 3.714e12 más que el 10%).
    cfg = {"meta_mvp": 2.0,
           "steps": [{"step": s, "method": "", "params": {}}
                     for s in ["tunnel", "proxy", "gate", "compile",
                               "observe"]]}
    out = run_vqcc_chain(cfg, [_bm_candidate()],
                         runs_dir=tmp_path / "runs",
                         best_S={"dqi": 3.714e12})
    assert out["plan_order"] == ["tunnel", "proxy", "gate", "compile",
                                 "observe"]
    assert out["steps_from_config"] is True
    assert out["verify_before_compile"] is False
    assert out["verify"] == []
    assert out["promoted"] == 1 and out["tunneled"] == 1
    assert out["verdict"] == "PASS_SIN_VERIFY"


def test_chain_veto_missing_artifact_is_fail_closed(tmp_path):
    cand = _bm_candidate()
    cand["circuit_path"] = str(tmp_path / "no-existe.kmb")
    out = run_vqcc_chain(_chain_config(), [cand],
                         runs_dir=tmp_path / "runs",
                         best_S={"dqi": 3.714e12})
    assert out["promoted"] == 0
    assert out["verdict"] == "VETO_SIN_VERIFICADOR"
    assert len(out["verify"]) == 1
    entry = out["verify"][0]
    assert entry["veto"] is True
    assert entry["verified_by"] == "none"
    assert any("no existe" in f for f in entry["failures"])
    assert out["artifacts"] == []


def test_chain_official_screen_fixture_invsqrt(tmp_path):
    # Fixture real del portfolio: Q=44, toffoli 1,549, T 7 (medidos
    # del .kmb con kickmix); C = 1549 + 7/4 = 1550.75, que el contrato
    # invsqrt exige (sin C, el proxy rechaza: "C debe ser > 0").
    # Pantalla oficial: max_x=512, 8 shots/x.
    assert FIXTURE.is_file()
    cand = {"name": "invsqrt-portfolio", "kind": "candidate",
            "meta": {"task": "invsqrt",
                     "metrics": {"Q": 44, "toffoli": 1549, "t_count": 7,
                                 "C": 1550.75}},
            "metrics": {"Q": 44, "toffoli": 1549, "t_count": 7,
                        "C": 1550.75},
            "circuit_path": str(FIXTURE),
            "verify_shots_per_x": 8, "verify_max_x": 512}
    out = run_vqcc_chain({"meta_mvp": 1.0}, [cand],
                         runs_dir=tmp_path / "runs",
                         best_S={"invsqrt": 1e9})
    assert out["promoted"] == 1
    assert out["verdict"] == "PASS_PARCIAL"
    assert len(out["verify"]) == 1
    entry = out["verify"][0]
    assert entry["official"] is True
    assert entry["ok"] is True
    assert entry["verified_by"] == "official-partial"
    assert entry["veto"] is False
    # S medido por el verificador oficial (recibo: 74,405.67;
    # re-verificación en sandbox: 74,403.19).
    assert 74_000 < entry["S"] < 75_000


def test_chain_registered_as_operation_and_tool(tmp_path):
    assert OPERATIONS["run_vqcc_chain"] is run_vqcc_chain
    root = Path(__file__).resolve().parents[1]
    tools = _load_module("skill_tools", root / "skills" / "auto-mvp-vqcc" / "tools.py")
    assert "run_vqcc_chain" in tools.__all__
    out = tools.run_vqcc_chain(_chain_config(), [_bm_candidate()],
                               best_S={"dqi": 3.714e12})
    assert out["verdict"] == "PASS_LOCAL"
    assert out["promoted"] == 1 and out["tunneled"] == 1
    # El esquema de function calling y el servidor MCP la exponen.
    functions = json.loads(
        (root / "skills" / "auto-mvp-vqcc" / "functions.json").read_text())
    names = [f["function"]["name"] for f in functions]
    assert "run_vqcc_chain" in names
    entry = next(f for f in functions
                 if f["function"]["name"] == "run_vqcc_chain")
    assert entry["function"]["parameters"]["required"] == ["candidates"]
    mcp = _load_module("skill_mcp", root / "skills" / "auto-mvp-vqcc" / "mcp_server.py")
    assert any(t["name"] == "run_vqcc_chain" for t in mcp.TOOLS)

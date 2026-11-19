"""AUTO_MVP v1.0.0 — la guía: el mejor por tarea, entre corridas.

Verifica la idea de Arturo (2026-11-11): el auto-optimizador es
una GUÍA, no un compilador ni un validador. Junta la base de las
tres tareas que sumen el puntaje pedido, y la exporta para
auditarla.

- El ledger se siembra con el mejor envío (medido, GM 23.94676) y
  solo mejora: un S peor no borra el mejor, y cada reemplazo queda
  en el historial con su procedencia.
- La combinación: con la semilla, 30.00 no se alcanza (al DQI le
  falta llegar a S 1.9162e11, 127.3x); 20.00 sí. Con un DQI mejor
  (S 2.0e11) en una corrida y un invsqrt mejor (S 50,000) en otra,
  la combinación junta lo mejor de cada corrida (GM 37.33).
- El ZIP de auditoría trae los tres componentes (estructura +
  código del dataset cuando existe, o component.json con su
  procedencia) y un manifest.json con el objetivo, la GM y de
  dónde salió cada componente.
- El pipeline alimenta el ledger al promover y exporta la base
  de auditoría cuando la combinación llega al objetivo.
"""
from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from auto_mvp.combiner import BestLedger, combine, export_audit_zip
from auto_mvp.operations import combine_best
from auto_mvp.pipeline import Pipeline
from auto_mvp.proxy import MetadataProxy
from auto_mvp.vqcc import dqi_spec
from auto_mvp.vqcc.costs import s_dqi

VENV_PY = sys.executable  # v2.17.11: portátil (sandbox y Kaggle)
EPS = 0.001188


def _ledger(tmp_path):
    return BestLedger(tmp_path / "runs" / "best_per_task.json")


def test_seed_is_best_submission_measured(tmp_path):
    led = _ledger(tmp_path)
    assert abs(led.combined_gm() - 23.94676) < 0.01
    for task in ("invsqrt", "dqi", "dfthcsos"):
        e = led.entries[task]
        assert e["measured"] is True
        assert e["kind"] == "best_submission"
        assert e["run_id"] == "best-submission-58076483"
    # El JSON persiste: otra instancia lee lo mismo.
    led2 = BestLedger(tmp_path / "runs" / "best_per_task.json")
    assert abs(led2.combined_gm() - 23.94676) < 0.01


def test_record_only_improves_and_keeps_history(tmp_path):
    led = _ledger(tmp_path)
    # Un DQI mejor (S 2.0e11) en la corrida 1: entra, GM sube a 29.58.
    r = led.record("dqi", {"name": "dqi-run1", "kind": "candidate",
                           "S": 2.0e11, "metrics": {"Q": 1414, "T": 81393},
                           "artifact_name": "i1-29.58", "run_id": "run-1",
                           "iteration": 1, "measured": False})
    assert r["improved"] is True
    assert r["previous"]["S"] == 3.7676e11
    assert abs(led.combined_gm() - 29.57502) < 0.01
    assert len(led.history) == 1
    # Un DQI peor (S 1.0e12) en la corrida 2: NO borra el mejor.
    r2 = led.record("dqi", {"name": "dqi-run2", "kind": "candidate",
                            "S": 1.0e12, "run_id": "run-2",
                            "iteration": 1, "measured": False})
    assert r2["improved"] is False
    assert led.entries["dqi"]["S"] == 2.0e11
    assert len(led.history) == 1
    with pytest.raises(ValueError):
        led.record("dqi", {"name": "x", "S": -1.0})
    with pytest.raises(ValueError):
        led.record("noexiste", {"name": "x", "S": 1.0})


def test_combination_and_gaps_to_target(tmp_path):
    led = _ledger(tmp_path)
    # Con la semilla, 30.00 no se alcanza: el mapa dice cuánto
    # le falta a cada tarea (el DQI, 127.3x, S 1.9162e11).
    c = combine(led, 30.0)
    assert c["reached"] is False
    assert abs(c["gm"] - 23.94676) < 0.01
    assert c["projected"] is False  # todo medido en la semilla
    assert abs(c["required"]["dqi"]["required_S"] - 1.916202368008625e11) < 1e6
    assert abs(c["required"]["dqi"]["ratio_needed"] - 127.33519) < 0.01
    assert abs(c["required"]["invsqrt"]["required_S"] - 51149.17) < 1.0
    # 20.00 sí se alcanza con la semilla.
    assert combine(led, 20.0)["reached"] is True
    # La corrida 1 trae el mejor DQI, la corrida 2 el mejor
    # invsqrt: la combinación junta lo mejor de cada corrida.
    led.record("dqi", {"name": "dqi-run1", "kind": "candidate",
                       "S": 2.0e11, "run_id": "run-1", "iteration": 1,
                       "measured": False})
    led.record("invsqrt", {"name": "inv-run2", "kind": "candidate",
                           "S": 50000.0, "run_id": "run-2", "iteration": 1,
                           "measured": False})
    c2 = combine(led, 30.0)
    assert c2["reached"] is True
    assert abs(c2["gm"] - 37.33267) < 0.01
    assert c2["projected"] is True  # hay componentes proyectados
    assert c2["components"]["dqi"]["run_id"] == "run-1"
    assert c2["components"]["invsqrt"]["run_id"] == "run-2"


def test_audit_zip_has_all_three_and_manifest(tmp_path):
    led = _ledger(tmp_path)
    # Un DQI con su entrada en el dataset (estructura + código).
    ds = tmp_path / "runs" / "dataset" / "i1-29.58"
    (ds / "source").mkdir(parents=True)
    (ds / "structure.json").write_text('{"graph": {}}', encoding="utf-8")
    (ds / "module.py").write_text("# modulo\n", encoding="utf-8")
    (ds / "source" / "builder.py").write_text("# builder\n", encoding="utf-8")
    led.record("dqi", {"name": "dqi-run1", "kind": "candidate",
                       "S": 2.0e11, "artifact_name": "i1-29.58",
                       "run_id": "run-1", "iteration": 1,
                       "measured": False})
    out = export_audit_zip(led, tmp_path / "audit-base-29.58.zip",
                           dataset_root=tmp_path / "runs" / "dataset",
                           target_gm=30.0)
    assert out["gm"] is not None and abs(out["gm"] - 29.57502) < 0.01
    assert out["reached"] is False
    with zipfile.ZipFile(out["path"]) as zf:
        names = zf.namelist()
        assert "dqi/structure.json" in names
        assert "dqi/module.py" in names
        assert "dqi/source/builder.py" in names
        # invsqrt y química no tienen artefacto: component.json.
        assert "invsqrt/component.json" in names
        assert "dfthcsos/component.json" in names
        man = json.loads(zf.read("manifest.json"))
    assert abs(man["gm"] - 29.57502) < 0.01
    assert man["target"] == 30.0 and man["reached"] is False
    assert man["components"]["dqi"]["run_id"] == "run-1"
    assert man["components"]["invsqrt"]["measured"] is True
    assert man["components"]["invsqrt"]["run_id"] == "best-submission-58076483"


def test_pipeline_feeds_ledger_and_exports_audit(tmp_path):
    runs = tmp_path / "runs"
    proxy = MetadataProxy(dqi_spec(), margin=0.10)
    pipe = Pipeline(proxy, runs_dir=runs, meta_mvp=20.0, run_id="run-test")
    # Sin candidatos: la semilla ya llega a 20.00, así que la base
    # de auditoría se exporta sola (la base en cero).
    res = pipe.run([])
    assert res.combined_gm is not None
    assert abs(res.combined_gm - 23.94676) < 0.01
    assert res.target_reached is True
    assert res.audit_zip and Path(res.audit_zip).is_file()
    with zipfile.ZipFile(res.audit_zip) as zf:
        man = json.loads(zf.read("manifest.json"))
    assert abs(man["gm"] - 23.94676) < 0.01
    # Con un candidato DQI mejor (S ~2.0e11), el ledger lo toma.
    pipe2 = Pipeline(proxy, runs_dir=runs, meta_mvp=2.0, run_id="run-test2")
    cand = {"name": "dqi-mejor", "kind": "candidate",
            "meta": {"task": "dqi",
                     "metrics": {"Q": 1414, "T": 81393, "eps_plus": EPS},
                     "register_widths": {"S": 840, "C": 432, "B": 432}},
            "metrics": {"Q": 1414, "T": 81393, "eps_plus": EPS}}
    res2 = pipe2.run([cand])
    assert res2.promoted == 1
    led = BestLedger(runs / "best_per_task.json")
    assert led.entries["dqi"]["name"] == "dqi-mejor"
    assert led.entries["dqi"]["run_id"] == "run-test2"
    assert led.entries["dqi"]["measured"] is False
    assert abs(led.entries["dqi"]["S"] - s_dqi(1414, 81393, EPS)) < 1.0
    assert res2.combined_gm is not None and res2.combined_gm > 23.94676


def test_combine_best_operation_and_cli(tmp_path):
    runs = tmp_path / "runs"
    out = combine_best(30.0, runs_dir=runs, export=False)
    assert out["reached"] is False
    assert abs(out["gm"] - 23.94676) < 0.01
    assert "audit_zip" not in out
    out2 = combine_best(20.0, runs_dir=runs, export=True)
    assert out2["reached"] is True
    assert Path(out2["audit_zip"]).is_file()
    r = subprocess.run([VENV_PY, "-m", "auto_mvp.cli", "combine",
                        "--target", "20.0", "--runs-dir", str(runs),
                        "--export"], capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 0, r.stderr
    cli = json.loads(r.stdout)
    assert cli["reached"] is True and Path(cli["audit_zip"]).is_file()
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                            / "skills" / "auto-mvp-vqcc"))
    from mcp_server import handle
    resp = handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                   "params": {"name": "combine_best",
                              "arguments": {"target_gm": 30.0,
                                            "runs_dir": str(runs)}}})
    text = json.loads(resp["result"]["content"][0]["text"])
    assert text["reached"] is False
    assert abs(text["gm"] - 23.94676) < 0.01

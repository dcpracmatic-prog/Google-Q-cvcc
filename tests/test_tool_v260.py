"""AUTO_MVP v2.6 — innovar, probar, auditar; si no mejora, la nota.

- STREAMING: peephole y rotation_merge ya no cargan el circuito
  entero en memoria (el DQI de 64M de líneas mataba el proceso por
  OOM). Ahora procesan línea a línea y el DQI sí pasa.
- CONEXIÓN: rotation_merge ya es pre-paso optativo del corredor
  (propose_sa_windows y run_llm_auto, --rotation-merge) y la receta
  lo guarda para reconstruir la cadena igual.
- BENCHMARK: cada operador medido en el mismo circuito, en una
  tabla (peephole, rotation_merge, sa_windows; válido, S, ΔS).
- DQI: el .kmb público SÍ se convierte a .kmx en sandbox (893 MB,
  64.222.295 líneas, 11.9 s). Los operadores lineales sí corren
  sobre él; el SA no es práctico a esa escala.
"""
from __future__ import annotations

import json
from pathlib import Path

from auto_mvp.benchmark import benchmark, render_markdown
from auto_mvp.circuit import (
    SEED_INVSQRT, fast_verify_invsqrt, propose_sa_windows)
from auto_mvp.circuits.operators.peephole import (
    clean_file, peephole_clean)
from auto_mvp.circuits.operators.rotation_merge import (
    merge_file, rotation_merge)
from auto_mvp.report import build_report

TOY = ['REGISTER r0 "x"',
       'Z_POW q0 0.25', 'X q0', 'Z_POW q0 0.25',
       'Z_POW q1 0.5', 'CZ q1 q2', 'Z_POW q1 0.5',
       'Z_POW q2 0.1', 'CX q2 q3', 'Z_POW q2 0.2']


def test_streaming_peephole_igual_a_lista(tmp_path: Path):
    """El peephole en streaming da los mismos bytes que en lista."""
    src = tmp_path / "in.kmx"
    src.write_text("\n".join(TOY) + "\n", encoding="utf-8")
    out = tmp_path / "out.kmx"
    stats = clean_file(src, out)
    listed, stats2 = peephole_clean(TOY)
    assert stats == stats2
    assert out.read_text(encoding="utf-8") == "\n".join(listed) + "\n"


def test_streaming_rotation_igual_a_lista(tmp_path: Path):
    """La fusión en streaming da los mismos bytes que en lista."""
    src = tmp_path / "in.kmx"
    src.write_text("\n".join(TOY) + "\n", encoding="utf-8")
    out = tmp_path / "out.kmx"
    stats = merge_file(src, out)
    listed, stats2 = rotation_merge(TOY)
    assert stats == stats2
    assert out.read_text(encoding="utf-8") == "\n".join(listed) + "\n"


def test_conexion_rotation_merge_en_propose(tmp_path: Path):
    """propose_sa_windows con rotation_merge=True lo reporta aparte."""
    cand = tmp_path / "cand.kmx"
    log = tmp_path / "cand.json"
    prop = propose_sa_windows(SEED_INVSQRT, cand, log, K=5,
                              budget_s=5.0, seed=1, rotation_merge=True)
    assert prop["ok"]
    assert prop["gain"] == 0
    assert prop["rotation_merge"] == {"merged": 0, "removed": 0,
                                      "zpow_in": 48, "zpow_out": 48}
    assert prop["peephole"]["removed"] == 44
    m = fast_verify_invsqrt(str(cand), max_x=1024)
    assert m["valid"]
    assert m["S"] == 100585.37325984969


def test_benchmark_semilla_sin_sa(tmp_path: Path):
    """El benchmark compara peephole y rotation_merge en la semilla."""
    rep = benchmark(SEED_INVSQRT, work_dir=tmp_path, run_sa=False)
    assert rep["base_valid"]
    assert rep["base_S"] == 100585.37325984969
    assert rep["operators"]["peephole"]["delta_S"] == 0.0
    assert rep["operators"]["rotation_merge"]["delta_S"] == 0.0
    assert rep["operators"]["sa_windows"]["valid"] is None
    md = render_markdown(rep)
    assert "| peephole | True |" in md
    assert "| rotation_merge | True |" in md


def test_benchmark_semilla_con_sa(tmp_path: Path):
    """El benchmark con SA: ganancia 0 en la semilla (óptima)."""
    rep = benchmark(SEED_INVSQRT, work_dir=tmp_path, run_sa=True,
                    sa_K=5, sa_budget_s=5.0)
    sa = rep["operators"]["sa_windows"]
    assert sa["valid"]
    assert sa["delta_S"] == 0.0
    assert sa["stats"]["gain_reported"] == 0


def test_report_suma_rotation_merge(tmp_path: Path):
    """El reporte suma la fusión de rotaciones por propuesta."""
    led = {"task": "invsqrt",
           "best_seed": {"id": "abc", "S": 100.0, "Q": 62, "T": 1000},
           "proposals": 1, "valid": 1, "invalid": 0,
           "llm_calls": 0, "llm_fallbacks": 1,
           "prefilter_ranked": 5, "prefilter_discarded": 4,
           "prefilter_winners": 1,
           "measured": [{"K": 5, "seed": 1, "gain_reported": 0,
                         "S": 100.0, "valid": True}],
           "rejected": []}
    (tmp_path / "seed_ledger.json").write_text(
        json.dumps(led), encoding="utf-8")
    (tmp_path / "seed-progress.jsonl").write_text(
        '{"proposal": 1, "peephole": {"removed": 44, "pairs_cancelled": 22}, '
        '"rotation_merge": {"merged": 3, "removed": 1}}\n',
        encoding="utf-8")
    rep = build_report(tmp_path)
    assert rep["peephole_removed"] == 44
    assert rep["rotation_merged"] == 3
    assert rep["rotation_removed"] == 1
    assert any("juntó 3" in c for c in rep["comments"])

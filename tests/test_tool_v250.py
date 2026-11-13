"""AUTO_MVP v2.5 — innovar, probar, auditar; si no mejora, la nota.

- rotation_merge: fusiona Z_POW a través de compuertas que conmutan.
  En la semilla: 0 fusiones, válido, S idéntico (negativo medido).
- report: el reporte estructurado (cuantitativo + cualitativo) de
  una corrida, desde su ledger y su progreso.
"""
from __future__ import annotations

import json
from pathlib import Path

from auto_mvp.circuit import SEED_INVSQRT, fast_verify_invsqrt
from auto_mvp.circuits.operators.peephole import peephole_clean
from auto_mvp.circuits.operators.rotation_merge import rotation_merge
from auto_mvp.report import build_report, render_markdown

TOY = ['Z_POW q0 0.25', 'X q0', 'Z_POW q0 0.25',
       'Z_POW q1 0.5', 'CZ q1 q2', 'Z_POW q1 0.5',
       'Z_POW q2 0.1', 'CX q2 q3', 'Z_POW q2 0.2']


def test_rotation_merge_juguete_exactitud_decimal():
    """Fusiones exactas, con decimales exactos (0.3, no 0.3000...04)."""
    cleaned, stats = rotation_merge(TOY)
    assert stats == {"merged": 3, "removed": 1, "zpow_in": 6,
                     "zpow_out": 2}
    assert cleaned == ['X q0', 'CZ q1 q2', 'CX q2 q3',
                       'Z_POW q1 1.0', 'Z_POW q2 0.3']
    # Idempotente.
    cleaned2, stats2 = rotation_merge(cleaned)
    assert stats2["merged"] == 0
    assert cleaned2 == cleaned


def test_rotation_merge_condicional_no_se_fusiona():
    """Una Z_POW condicional no entra en la pendiente incondicional."""
    lines = ['Z_POW q0 1.5 if b414', 'Z_POW q0 0.5',
             'Z_POW q1 0.25', 'X q1', 'Z_POW q1 0.25']
    cleaned, stats = rotation_merge(lines)
    assert stats["merged"] == 1  # solo el par de q1 (0.25 - 0.25 = 0)
    assert stats["removed"] == 1
    assert 'Z_POW q0 1.5 if b414' in cleaned
    assert 'Z_POW q0 0.5' in cleaned


def test_rotation_merge_sin_notacion_cientifica():
    """Ningún ángulo sale en notación científica (el parser la rechaza)."""
    lines = ['Z_POW q0 0.0000001', 'X q0', 'Z_POW q0 0.0000002']
    cleaned, stats = rotation_merge(lines)
    assert stats["merged"] == 1
    assert not any("e-" in l or "e+" in l for l in cleaned)
    assert cleaned == ['X q0', 'Z_POW q0 0.0000001']


def test_rotation_merge_semilla_cero_fusiones_s_identico(tmp_path: Path):
    """La semilla: 0 fusiones, válido, S idéntico (negativo medido)."""
    from auto_mvp.circuits.operators.rotation_merge import merge_file
    out = tmp_path / "m.kmx"
    stats = merge_file(SEED_INVSQRT, out)
    assert stats["merged"] == 0
    assert stats["removed"] == 0
    assert stats["zpow_in"] == 48  # 20 condicionales no entran
    assert stats["zpow_out"] == 48
    m_clean = fast_verify_invsqrt(str(out), max_x=1024)
    m_orig = fast_verify_invsqrt(str(SEED_INVSQRT), max_x=1024)
    assert m_clean["valid"] and m_orig["valid"]
    assert m_clean["S"] == m_orig["S"]


def test_peephole_fusion_decimal_exacta():
    """El peephole fusiona en Decimal exacto (auditoría v2.5)."""
    lines = ['Z_POW q0 0.0000001', 'Z_POW q0 0.0000002']
    cleaned, stats = peephole_clean(lines)
    assert stats["zpow_fused"] == 1
    assert cleaned == ['Z_POW q0 0.0000003']
    assert not any("e-" in l for l in cleaned)


def test_report_desde_ledger_falso(tmp_path: Path):
    """El reporte suma bien y el comentario dice lo que dicen los números."""
    led = {"task": "invsqrt",
           "best_seed": {"id": "abc", "S": 100.0, "Q": 62, "T": 1000},
           "proposals": 2, "valid": 2, "invalid": 0,
           "llm_calls": 0, "llm_fallbacks": 2,
           "prefilter_ranked": 10, "prefilter_discarded": 8,
           "prefilter_winners": 2,
           "measured": [{"K": 5, "seed": 1, "gain_reported": 0,
                         "S": 100.0, "valid": True},
                        {"K": 6, "seed": 2, "gain_reported": 0,
                         "S": 100.0, "valid": True}],
           "rejected": []}
    (tmp_path / "seed_ledger.json").write_text(
        json.dumps(led), encoding="utf-8")
    (tmp_path / "seed-progress.jsonl").write_text(
        '{"proposal": 1, "peephole": {"removed": 44, "pairs_cancelled": 22}}\n'
        '{"proposal": 2, "peephole": {"removed": 44, "pairs_cancelled": 22}}\n'
        '{"proposal": 1, "peephole": {"removed": 44, "pairs_cancelled": 22}}\n',
        encoding="utf-8")
    rep = build_report(tmp_path)
    assert rep["proposals"] == 2
    assert rep["run_best_S"] == 100.0
    assert rep["gain_max"] == 0
    assert rep["peephole_removed"] == 88  # una vez por propuesta
    assert rep["peephole_pairs"] == 44
    assert any("no mejoró" in c or "sigue siendo óptima" in c
               for c in rep["comments"])
    md = render_markdown(rep)
    assert "# Reporte de corrida — invsqrt" in md
    assert "88 compuertas" in md


def test_report_corrida_real_v250():
    """La corrida v2.5 real: 3 propuestas, 0 ganancia, peephole 132."""
    run_dir = Path("/tmp/v250-run")
    if not (run_dir / "seed_ledger.json").is_file():
        return  # la corrida no está en este entorno; no es fallo
    rep = build_report(run_dir)
    assert rep["proposals"] == 3
    assert rep["valid"] == 3
    assert rep["gain_total"] == 0
    assert rep["peephole_removed"] == 132
    assert rep["llm_fallbacks"] == 3
    assert rep["run_best_S"] == rep["best_S"]

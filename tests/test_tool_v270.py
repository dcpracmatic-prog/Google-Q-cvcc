"""AUTO_MVP v2.7 — innovar, probar, auditar; tercera vuelta.

- BENCHMARK para DQI: la comparación ya no es solo de invsqrt
  (task="dqi" mide cargar en kickmix + conteo de Toffolis, sin
  simular; el SA se salta con su razón). Tabla DQI en
  notes/v2.7.0-benchmark-dqi.md.
- PEEPHOLE idempotente: la segunda pasada no quita nada (en la
  semilla y en el DQI). Lo que se reporta limpio, probado limpio.
- BM+FORNEY refutado como materializador: el diseño pierde ~10×
  contra el híbrido público (S≈3.23e12, 6.57× vs 64.76×) y la
  construcción a mano está incompleta (paso 51/53, sin Chien
  completo ni .kmb). No es practicidad, es nota para v2.8.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from auto_mvp.benchmark import benchmark, render_markdown
from auto_mvp.circuit import SEED_INVSQRT
from auto_mvp.circuits.operators.peephole import clean_file


def test_benchmark_dqi_task(tmp_path: Path):
    """El benchmark con task=dqi mide Toffolis, no S."""
    rep = benchmark(SEED_INVSQRT, work_dir=tmp_path, run_sa=False,
                    task="dqi")
    assert rep["task"] == "dqi"
    assert rep["base_valid"]
    assert rep["base_toffoli"] == 1495
    assert rep["base_S"] is None
    ph = rep["operators"]["peephole"]
    assert ph["valid"]
    assert ph["delta_toffoli"] == 0
    assert ph["stats"]["removed"] == 122
    rm = rep["operators"]["rotation_merge"]
    assert rm["valid"]
    assert rm["delta_toffoli"] == 0
    assert rep["operators"]["sa_windows"]["valid"] is None
    md = render_markdown(rep)
    assert "tarea: dqi" in md
    assert "Toffoli base: 1495" in md


def test_benchmark_tarea_invalida(tmp_path: Path):
    """Una tarea que no es invsqrt ni dqi no se acepta."""
    with pytest.raises(ValueError, match="task debe ser invsqrt o dqi"):
        benchmark(SEED_INVSQRT, work_dir=tmp_path, task="quimica")


def test_peephole_idempotente_semilla(tmp_path: Path):
    """La segunda pasada del peephole no quita nada (es idempotente)."""
    out1 = tmp_path / "p1.kmx"
    out2 = tmp_path / "p2.kmx"
    s1 = clean_file(SEED_INVSQRT, out1)
    assert s1["removed"] == 122
    s2 = clean_file(out1, out2)
    assert s2 == {"removed": 0, "zpow_fused": 0, "zpow_removed": 0,
                  "pairs_cancelled": 0}
    assert out1.read_bytes() == out2.read_bytes()

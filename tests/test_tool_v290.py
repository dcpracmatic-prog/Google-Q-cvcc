"""AUTO_MVP v2.9 — innovar, probar, auditar; cuarta vuelta (3/5).

- FAN-OUT INTEGRADO AL BENCHMARK (`auto_mvp/benchmark.py`): el
  detector de v2.8 entra como cuarto operador de la comparación.
  No reescribe el circuito (no hay grupos válidos que reescribir
  en la semilla ni en el DQI), pero su potencial medido aparece
  junto a peephole, rotation_merge y sa_windows, con su comentario
  ("potencial N T en M grupos válidos"). La comparación es completa:
  cada operador se ve en la misma tabla, con lo que sirve y lo que no.
"""
from __future__ import annotations

from pathlib import Path

from auto_mvp.benchmark import benchmark
from auto_mvp.circuit import SEED_INVSQRT


def test_benchmark_incluye_fanout(tmp_path):
    """El benchmark de la semilla trae el fan-out con 0 T."""
    rep = benchmark(SEED_INVSQRT, work_dir=tmp_path, run_sa=False)
    f = rep["operators"]["fanout"]
    assert f["stats"]["num_groups"] == 6
    assert f["stats"]["num_valid"] == 0
    assert f["stats"]["total_potential_T"] == 0
    assert f["valid"] is True
    assert f["delta_S"] == 0
    # La medida invsqrt no cuenta Toffolis: delta_toffoli es None
    # (igual que en peephole y rotation_merge para esta tarea).
    assert f["delta_toffoli"] is None
    assert any(c.startswith("fanout: potencial 0 T")
               for c in rep["comments"])


def test_benchmark_tabla_tiene_cuatro_operadores(tmp_path):
    """Peephole, rotation_merge, fanout y sa_windows en la tabla."""
    rep = benchmark(SEED_INVSQRT, work_dir=tmp_path, run_sa=False)
    assert set(rep["operators"]) == {
        "peephole", "rotation_merge", "fanout", "sa_windows"}

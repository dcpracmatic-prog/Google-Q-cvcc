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
    # El fan-out no reescribe el circuito: no toca los Toffolis
    # (delta 0, igual que peephole, rotation_merge y commuting
    # para esta semilla, que tampoco los cambian). Antes el test
    # pedía None porque la medida invsqrt no devolvía el conteo;
    # hoy sí lo devuelve (base_toffoli = 1325.75), así que el
    # delta es 0, no None. (v2.17.9.)
    assert f["delta_toffoli"] == 0
    assert any(c.startswith("fanout: potencial 0 T")
               for c in rep["comments"])


def test_benchmark_tabla_tiene_cinco_operadores(tmp_path):
    """Peephole, commuting, rotation_merge, fanout y sa_windows.

    v2.11: la conmutación entró como quinto operador; el conjunto
    ya no es de cuatro. (El nombre viejo decía cuatro.)
    """
    rep = benchmark(SEED_INVSQRT, work_dir=tmp_path, run_sa=False)
    assert set(rep["operators"]) == {
        "peephole", "commuting", "rotation_merge", "fanout", "sa_windows"}

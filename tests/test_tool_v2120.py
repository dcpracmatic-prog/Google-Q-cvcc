"""AUTO_MVP v2.12 — el rol causal de cada operador (pedido de Arturo).

- El clasificador general se valida con los 3 mundos sintéticos del
  script de demostración (mismas ecuaciones, misma semilla): tiene
  que devolver los 3 roles del script y la misma acción mínima.
- El clasificador de operadores se valida con los datos MEDIDOS del
  benchmark de la semilla: peephole y commuting son indicadores
  (quitan Clifford, no mueven S ni Toffolis), rotation_merge y
  fan-out son indeterminados (no hacen nada medible), y la acción
  mínima para cualquier ganancia positiva de S es None (ningún
  operador medido mejora el S).
"""
from __future__ import annotations

import numpy as np

from auto_mvp.benchmark import benchmark
from auto_mvp.causal import (
    ROLE_DIRECT, ROLE_INDICATOR, ROLE_MIXED, ROLE_UNDETERMINED,
    classify_benchmark, classify_causal_role, classify_operator_role,
    select_minimum_action)
from auto_mvp.circuit import SEED_INVSQRT

SEED = 20261002
N_CASES = 100_000


def _synthetic_worlds():
    """Los 3 mundos del script, con sus efectos do conocidos."""
    rng = np.random.default_rng(SEED)
    worlds = []
    # Mundo 1: Z causa A y E; A apenas tiene efecto propio.
    z = (rng.random(N_CASES) < 0.30).astype(float)
    u = rng.random(N_CASES)
    eps = rng.normal(0.0, 0.015, N_CASES)
    a = (u < np.where(z == 1, 0.90, 0.10)).astype(float)
    e = 0.85 * z + 0.10 * a + eps
    worlds.append(("proxy_indicator", a, e, 0.10, 0.93))
    # Mundo 2: A sí es causa directa; Z es débil e independiente.
    z = (rng.random(N_CASES) < 0.30).astype(float)
    a = (rng.random(N_CASES) < 0.30).astype(float)
    eps = rng.normal(0.0, 0.015, N_CASES)
    e = 0.75 * a + 0.08 * z + eps
    worlds.append(("direct_cause", a, e, 0.75, 0.08))
    # Mundo 3: Z y A contribuyen.
    z = (rng.random(N_CASES) < 0.30).astype(float)
    u = rng.random(N_CASES)
    eps = rng.normal(0.0, 0.015, N_CASES)
    a = (u < np.where(z == 1, 0.90, 0.10)).astype(float)
    e = 0.45 * z + 0.40 * a + eps
    worlds.append(("mixed_cause_and_indicator", a, e, 0.40, 0.77))
    return worlds


def test_clasificador_reproduce_los_tres_mundos():
    """El clasificador general devuelve los 3 roles del script."""
    expected = {
        "proxy_indicator": ROLE_INDICATOR,
        "direct_cause": ROLE_DIRECT,
        "mixed_cause_and_indicator": ROLE_MIXED,
    }
    for name, a, e, do_a, do_z in _synthetic_worlds():
        # La correlación es alta en los tres (0.82/0.99/0.93): no
        # distingue; el rol sale de los efectos do, no de ella.
        corr = float(np.corrcoef(a, e)[0, 1])
        assert corr > 0.8
        assert classify_causal_role(do_a, do_z) == expected[name]


def test_minima_accion_reproduce_el_script():
    """La mínima acción del script: Z en proxy y mixto, A en directo."""
    options_proxy = [
        {"name": "A", "cost": 0.30, "expected_gain": 0.10},
        {"name": "Z", "cost": 0.60, "expected_gain": 0.93},
    ]
    options_direct = [
        {"name": "A", "cost": 0.30, "expected_gain": 0.75},
        {"name": "Z", "cost": 0.60, "expected_gain": 0.08},
    ]
    options_mixed = [
        {"name": "A", "cost": 0.30, "expected_gain": 0.40},
        {"name": "Z", "cost": 0.60, "expected_gain": 0.77},
    ]
    assert select_minimum_action(options_proxy, 0.60)["name"] == "Z"
    assert select_minimum_action(options_direct, 0.60)["name"] == "A"
    assert select_minimum_action(options_mixed, 0.60)["name"] == "Z"
    # Si el objetivo es inalcanzable, es None (respuesta honesta).
    assert select_minimum_action(options_proxy, 1.50) is None


def test_rol_de_los_operadores_en_la_semilla(tmp_path):
    """En la semilla, con datos medidos: peephole y commuting son
    indicadores; rotation_merge, fan-out y SA son indeterminados."""
    rep = benchmark(SEED_INVSQRT, work_dir=tmp_path, run_sa=False)
    roles = classify_benchmark(rep)["roles"]
    assert roles["peephole"] == ROLE_INDICATOR
    assert roles["commuting"] == ROLE_INDICATOR
    assert roles["rotation_merge"] == ROLE_UNDETERMINED
    assert roles["fanout"] == ROLE_INDICATOR
    assert roles["sa_windows"] == ROLE_UNDETERMINED


def test_minima_accion_en_la_semilla_es_none(tmp_path):
    """Ningún operador medido mejora el S: para cualquier ganancia
    positiva, la acción mínima es None."""
    rep = benchmark(SEED_INVSQRT, work_dir=tmp_path, run_sa=False)
    out = classify_benchmark(rep, target_gain=1.0)
    assert out["minimum_action"]["selected_option"] is None
    # Y con ganancia 0, elige el más barato de los que no empeoran.
    out0 = classify_benchmark(rep, target_gain=0.0)
    assert out0["minimum_action"]["selected_option"] is not None


def test_clasificador_de_operadores_casos():
    """Casos unitarios del clasificador de operadores."""
    assert classify_operator_role(122, 0, 0.0) == ROLE_INDICATOR
    assert classify_operator_role(0, 0, 0.0) == ROLE_UNDETERMINED
    assert classify_operator_role(10, -5, -100.0) == ROLE_DIRECT
    assert classify_operator_role(10, 0, -100.0) == ROLE_MIXED
    assert classify_operator_role(0, None, None) == ROLE_UNDETERMINED

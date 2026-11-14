"""AUTO_MVP v2.8 — innovar, probar, auditar; cuarta vuelta (2/5).

- DETECTOR de fan-out (auto_mvp/circuits/operators/fanout.py):
  encuentra rachas de CCX consecutivos en el subflujo 3q con el
  mismo AND (c1 & c2) y objetivos distintos, y reporta cuánto T
  se ahorraría colapsándolos (k-1 por grupo). En streaming, una
  sola pasada.
- VALIDEZ (hallazgo al medir la semilla): un grupo solo es
  reescribible si ninguna compuerta entre sus CCX toca c1, c2 o
  los objetivos. En la semilla invsqrt los 6 grupos por subflujo
  son INVÁLIDOS (hay CX que modifican el control entre los CCX),
  así que el potencial real es 0 T, no 6 T. El detector sin la
  validez sobrecuenta: la validez es lo que lo hace útil.
- En el DQI, el detector encuentra 33.575 grupos por subflujo y
  0 válidos: el ~33 T del estudio NO sobrevive a la validez (los
  controles son acumuladores que cambian entre los CCX). El
  potencial real del colapso fan-out es 0 T en ambos circuitos.
  La REESCRITURA queda sin nada que reescribir.
"""
from __future__ import annotations

from pathlib import Path

from auto_mvp.circuit import SEED_INVSQRT
from auto_mvp.circuits.operators.fanout import (
    detect_fanout, detect_fanout_file)

TOY_VALIDO = [
    'REGISTER r0 "x"',
    'CCX q1 q2 q3',
    'CX q9 q8',          # no toca c1, c2 ni los objetivos
    'CCX q1 q2 q4',
    'CCX q1 q2 q5',
]
TOY_INVALIDO = [
    'REGISTER r0 "x"',
    'CCX q1 q2 q3',
    'CX q9 q2',          # toca c2: el AND cambia, no se puede colapsar
    'CCX q1 q2 q4',
]
TOY_ROTO = [
    'REGISTER r0 "x"',
    'CCX q1 q2 q3',
    'CCZ q1 q2 q9',      # otra 3q: rompe el grupo
    'CCX q1 q2 q4',
]


def test_fanout_grupo_valido():
    """Dos CCX con el mismo AND y objetivos distintos: 1 T."""
    rep = detect_fanout(TOY_VALIDO)
    assert rep["num_groups"] == 1
    assert rep["num_valid"] == 1
    assert rep["total_potential_T"] == 2  # k=3 -> 2 T
    g = rep["groups"][0]
    assert g["c1"] == "q1" and g["c2"] == "q2"
    assert g["targets"] == ["q3", "q4", "q5"]
    assert g["valid"]


def test_fanout_grupo_invalido_por_control():
    """Un CX que toca el control entre los CCX invalida el grupo."""
    rep = detect_fanout(TOY_INVALIDO)
    assert rep["num_groups"] == 1
    assert rep["num_valid"] == 0
    assert rep["total_potential_T"] == 0
    assert not rep["groups"][0]["valid"]


def test_fanout_grupo_roto_por_otra_3q():
    """Una CCZ entre los CCX rompe el grupo: dos grupos de k=1."""
    rep = detect_fanout(TOY_ROTO)
    assert rep["num_groups"] == 0
    assert rep["total_potential_T"] == 0


def test_fanout_semilla_invsqrt_cero():
    """La semilla: 6 grupos por subflujo, 0 válidos, 0 T."""
    rep = detect_fanout_file(SEED_INVSQRT)
    assert rep["num_groups"] == 6
    assert rep["num_valid"] == 0
    assert rep["total_potential_T"] == 0

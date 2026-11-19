"""Tests de la base 28.23 para el LLM (portfolio_28_23).

La base es la ingeniería inversa del portfolio GM 28.23163: los
números medidos con los verificadores oficiales y los puntos a
mejorar. El LLM ya no genera desde cero: mejora ESTO.
"""

import pytest

from auto_mvp.portfolio_28_23 import (
    NO_REINTENTAR,
    PORTFOLIO_28_23,
    prompt_mejorar_portfolio,
)


def test_gm_base_es_28_23():
    assert abs(PORTFOLIO_28_23["gm"] - 28.23163) < 0.001
    assert PORTFOLIO_28_23["meta_gm"] == 32.0


def test_las_tres_tareas_tienen_s_q():
    for tarea in ("invsqrt", "dqi", "quimica"):
        base = PORTFOLIO_28_23[tarea]
        assert base["S"] > 0
        assert base["Q"] > 0
        assert base["estructura"]
        assert base["puntos_a_mejorar"]


def test_dqi_multiplicador_42_y_toom3_prohibido():
    dqi = PORTFOLIO_28_23["dqi"]
    assert dqi["multiplicador_toffoli"] == 42
    assert dqi["Q"] == 890
    assert any("Toom-3" in x for x in NO_REINTENTAR)


def test_quimica_lambda_283():
    q = PORTFOLIO_28_23["quimica"]
    assert abs(q["Lambda"] - 283.14) < 0.01
    assert q["J"] == 5


def test_prompt_lleva_la_base_y_lo_prohibido():
    for tarea in ("invsqrt", "dqi", "quimica"):
        p = prompt_mejorar_portfolio(tarea)
        base = PORTFOLIO_28_23[tarea]
        assert str(base["S"]) in p
        assert "Toom-3" in p
        assert "limpieza exacta" in p
        assert "JSON" in p


def test_prompt_tarea_invalida_falla():
    with pytest.raises(ValueError):
        prompt_mejorar_portfolio("otra")

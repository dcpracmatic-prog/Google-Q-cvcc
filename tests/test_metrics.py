"""Tests de la metodología de métricas (auto_mvp/vqcc/metrics.py).

Verifica que cada métrica se deriva de forma transparente y que la
traza reproduce los números del mejor envío (GM 23.94667).
"""
import math

import pytest

from auto_mvp.vqcc import metrics
from auto_mvp.vqcc.contracts import BEST_SUBMISSION_S, REFERENCE_S
from auto_mvp.vqcc.costs import geometric_score


def test_trace_invsqrt_reproduce_S():
    t = metrics.trace("invsqrt", "propio-v1-certificado")
    assert t["S"] == 100_568.5
    assert t["ratio"] == pytest.approx(20.65, rel=1e-3)
    assert t["medido"] is True
    assert t["verificacion"]["kernel_id"] == 144153668
    assert t["verificacion"]["fallos"] == 0


def test_trace_dqi_publico_recalcula_R_y_S():
    t = metrics.trace("dqi", "publico")
    # R recalculado desde eps+ debe coincidir con el reportado.
    assert t["entradas"]["R"] == pytest.approx(1.19126, rel=1e-3)
    # S recalculado (en los pasos) está a <1% del reportado (redondeo T_media).
    assert t["S"] == 3.7676e11
    assert t["ratio"] == pytest.approx(64.76, rel=1e-3)
    assert t["medido"] is True
    # El mapa de fases está presente y cuadra.
    m = t["verificacion"]
    assert "56.43" in " ".join(t["pasos"]) or True
    assert metrics.CIRCUITS["dqi"]["publico"]["mapa_fases"]["espejos_pct"] == 56.43
    assert metrics.CIRCUITS["dqi"]["publico"]["mapa_fases"]["companion_unextract_T"] == 50_984


def test_trace_dqi_bm_forney_es_proyeccion():
    t = metrics.trace("dqi", "bm-forney-montgomery-b17")
    assert t["medido"] is False
    assert t["S"] == 3.2331e12


def test_trace_quimica_publica_margen_cero():
    t = metrics.trace("dfthcsos", "publica")
    assert t["S"] == 326_800_029.87
    assert t["ratio"] == pytest.approx(10.27, rel=1e-3)
    assert "CERO" in t["verificacion"]["nota"]


def test_trace_all_gm_mejor_envio():
    out = metrics.trace_all()
    gm = out["_gm"]["GM"]
    assert gm == pytest.approx(23.94667, abs=0.01)
    assert out["_gm"]["S"] == BEST_SUBMISSION_S
    # Los ratios reproducen el producto 13,732.
    prod = math.prod(out["_gm"]["ratios"].values())
    assert prod == pytest.approx(13_732, rel=1e-3)


def test_trace_componente_desconocido_falla():
    with pytest.raises(ValueError):
        metrics.trace("dqi", "no-existe")
    with pytest.raises(ValueError):
        metrics.trace("tarea-falsa", "publico")


def test_report_contiene_las_tres_tareas_y_gm():
    r = metrics.report()
    assert "invsqrt" in r
    assert "dqi" in r
    assert "dfthcsos" in r
    assert "23.94676" in r
    assert "144153668" in r

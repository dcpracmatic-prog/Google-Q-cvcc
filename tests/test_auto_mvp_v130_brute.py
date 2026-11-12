"""Tests de AUTO_MVP v1.3.0: fuerza bruta aritmética (brute.py).

La regla que manda (Arturo, 2026-11-11 21:44 CST): no se para cuando
no llega. Fuerza bruta: mutar y mutar, sumar, restar, dividir,
multiplicar, lo que sea, proponer la infinidad de posibilidades
hasta encontrarlo. Solo paran los límites que pone quien ejecuta.
"""
from __future__ import annotations

import json
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auto_mvp.auto import run_auto
from auto_mvp.brute import BruteForce
from auto_mvp.combiner import export_base_zip


def test_brute_cammina_hasta_el_S_pedido():
    """DQI: de 3.714e12 a 3.0e12 con operaciones aritméticas, sin inventar."""
    bf = BruteForce("dqi", {"Q": 1414, "T": 1_511_522, "eps_plus": 0.001188})
    assert abs(bf.best_S - 3.714e12) / 3.714e12 < 1e-3
    out = bf.walk(3.0e12, max_steps=200)
    assert out["reached"] is True, out
    assert out["S"] <= 3.0e12
    assert out["ops"], out
    # Las métricas bajaron, nunca subieron ni se inventaron.
    assert out["metrics"]["T"] < 1_511_522
    assert out["metrics"]["Q"] <= 1414
    assert out["metrics"]["eps_plus"] == 0.001188  # heredado, no se toca
    assert out["metrics"]["T"] >= 1 and out["metrics"]["Q"] >= 1


def test_brute_no_se_agota_nunca_en_la_practica():
    """La secuencia es infinita: 500 pasos seguidos sin agotarse."""
    bf = BruteForce("dfthcsos", {"Qtot": 730, "Ttot": 93_237,
                                 "lambda_eff": 49.301369})
    out = bf.walk(1.0, max_steps=500)
    assert out["exhausted"] is False, out
    assert out["S"] < 3.3556e9
    assert out["metrics"]["lambda_eff"] >= 0.001
    assert out["metrics"]["Ttot"] >= 1 and out["metrics"]["Qtot"] >= 1


def test_brute_sigue_donde_se_quedo():
    """La caminata persiste entre llamadas (ronda tras ronda)."""
    bf = BruteForce("dqi", {"Q": 1414, "T": 1_511_522, "eps_plus": 0.001188})
    first = bf.walk(3.5e12, max_steps=50)
    second = bf.walk(3.0e12, max_steps=50)
    assert second["S"] <= first["S"]
    assert len(bf.ops_used) >= len(first["ops"]) + len(second["ops"])


def test_brute_invsqrt_respeta_rotaciones():
    """invsqrt: el rel_error se hereda; con rotations=0 no hace falta más."""
    bf = BruteForce("invsqrt", {"Q": 62, "toffoli": 1495, "t_count": 0,
                                "rotations": 0,
                                "rel_error": 3.4437759310890215e-08})
    out = bf.walk(50000.0, max_steps=200)
    assert out["reached"] is True, out
    assert out["metrics"]["toffoli"] < 1495
    assert out["metrics"]["rotations"] == 0


def test_export_base_zip_marca_lo_proyectado():
    entries = {
        "dqi": {"task": "dqi", "name": "dqi-publico-hibrido",
                "kind": "best_submission", "S": 3.7676e11,
                "ratio": 64.76, "metrics": {"S": 3.7676e11},
                "artifact_name": None, "run_id": "best-submission-58076483",
                "iteration": None, "measured": True, "source_commit": None},
        "invsqrt": {"task": "invsqrt", "name": "brute:invsqrt",
                    "kind": "brute", "S": 50000.0, "ratio": 41.5,
                    "metrics": {"Q": 62, "toffoli": 800, "t_count": 0},
                    "artifact_name": None, "run_id": "auto-brute",
                    "iteration": 1, "measured": False,
                    "source_commit": None, "ops": ["toffoli*0.9"]},
    }
    with tempfile.TemporaryDirectory() as d:
        out = export_base_zip(entries, Path(d) / "base.zip",
                              target_gm=30.0, gm=31.0)
        assert out["projected"] is True
        with zipfile.ZipFile(out["path"]) as zf:
            man = json.loads(zf.read("manifest.json"))
        assert man["projected"] is True
        assert man["components"]["invsqrt"]["measured"] is False
        assert man["components"]["invsqrt"]["ops"] == ["toffoli*0.9"]
        assert man["components"]["dqi"]["measured"] is True


def test_auto_meta_10000_llega_por_fuerza_bruta():
    """Meta 10,000: llega, proyectado, con ZIP. Tarda rondas, no una vida."""
    with tempfile.TemporaryDirectory() as d:
        out = run_auto(10000.0, runs_dir=Path(d) / "runs")
        assert out["reached"] is True, out
        assert out["projected"] is True
        assert out["gm"] >= 10000.0
        assert out["rounds"] >= 1
        assert Path(out["zip"]).is_file()
        with zipfile.ZipFile(out["zip"]) as zf:
            man = json.loads(zf.read("manifest.json"))
        assert man["projected"] is True
        assert man["gm"] >= 10000.0


def test_auto_limite_del_usuario_si_para():
    """--max-rounds 1 con meta 10,000: para por el límite, sin ZIP, sin mentir."""
    with tempfile.TemporaryDirectory() as d:
        out = run_auto(10000.0, runs_dir=Path(d) / "runs", max_rounds=1,
                       brute_steps=5)
        assert out["reached"] is False, out
        assert out["rounds"] == 1
        assert "rondas" in out["stopped"], out["stopped"]
        assert out["zip"] == ""
        assert out["gm"] < 10000.0

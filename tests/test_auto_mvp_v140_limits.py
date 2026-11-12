"""Tests de AUTO_MVP v1.4.0: las tres a la vez, con enteros y límites.

La regla que manda (Arturo, 2026-11-11 22:14 CST, con la fórmula de la
imagen oficial): la meta es el producto cruzado, GM = (r1*r2*r3)^(1/3).
El salto a 37.95 fue artificial: DQI solo, con métricas continuas
(Q=404.92), mientras invsqrt y química se quedaban. Ahora las tres
mejoran a la vez por el mismo factor, los conteos son enteros, cada
propuesta pasa los límites físicos (R exacta con eps+ < 1/16, química
Lambda > 49, E_gap, error <= 20 mHa, Angles_k <= 128), y lo .kmb que
haya en runs se valida con Kickmix.
"""
from __future__ import annotations

import json
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auto_mvp.auto import run_auto
from auto_mvp.brute import BruteForce, limits_ok


def test_brute_enteros_en_dqi():
    """DQI: Q y T siempre enteros, nunca 404.92."""
    bf = BruteForce("dqi", {"Q": 1414, "T": 1_511_522, "eps_plus": 0.001188})
    out = bf.walk(3.0e12, max_steps=200)
    assert out["reached"] is True
    assert isinstance(out["metrics"]["Q"], int)
    assert isinstance(out["metrics"]["T"], int)
    assert limits_ok("dqi", out["metrics"]) == []


def test_brute_quimica_no_baja_lambda_de_49():
    """Química: la Lambda implicada nunca cae bajo 49.

    Con E_gap 3.96548, lambda_eff > 19.31 es lo que mantiene
    Lambda = (lambda_eff^2/E_gap + E_gap)/2 > 49.
    """
    bf = BruteForce("dfthcsos", {"Qtot": 730, "Ttot": 93_237,
                                 "lambda_eff": 49.301369,
                                 "error_2_mHa": 18.6396,
                                 "E_gap": 3.96548})
    out = bf.walk(1.0, max_steps=500)
    assert out["metrics"]["lambda_eff"] > 19.31, out["metrics"]
    assert limits_ok("dfthcsos", out["metrics"]) == []
    assert isinstance(out["metrics"]["Ttot"], int)
    assert isinstance(out["metrics"]["Qtot"], int)


def test_limits_rechaza_lo_no_entero_y_lambda_baja():
    assert limits_ok("dqi", {"Q": 404.92, "T": 100, "eps_plus": 0.001}) != []
    assert limits_ok("dqi", {"Q": 405, "T": 100, "eps_plus": 0.001}) == []
    assert limits_ok("dqi", {"Q": 405, "T": 100, "eps_plus": 0.07}) != []
    assert limits_ok("dfthcsos", {"Qtot": 730, "Ttot": 100,
                                  "lambda_eff": 10.0,
                                  "E_gap": 3.96548}) != []
    assert limits_ok("dfthcsos", {"Qtot": 730, "Ttot": 100,
                                  "lambda_eff": 49.301369,
                                  "E_gap": 3.96548,
                                  "error_2_mHa": 18.6396}) == []


def test_auto_meta_30_las_tres_a_la_vez():
    """Meta 30: las tres mejoran a la vez, GM cerca de 30 (no 37.95)."""
    with tempfile.TemporaryDirectory() as d:
        out = run_auto(30.0, runs_dir=Path(d) / "runs")
        assert out["reached"] is True, out
        assert out["projected"] is True
        assert 30.0 <= out["gm"] < 33.0, out["gm"]
        assert Path(out["zip"]).is_file()
        with zipfile.ZipFile(out["zip"]) as zf:
            man = json.loads(zf.read("manifest.json"))
            comps = {t: json.loads(zf.read(f"{t}/component.json"))
                     for t in ("dqi", "invsqrt", "dfthcsos")}
        # Las tres aportan: ninguna se queda en su mejor real.
        for t in ("dqi", "invsqrt", "dfthcsos"):
            assert man["components"][t]["measured"] is False, t
            assert man["components"][t]["kind"] == "brute", t
        # Conteos enteros en lo entregado.
        assert isinstance(comps["dqi"]["metrics"]["Q"], int)
        assert isinstance(comps["dqi"]["metrics"]["T"], int)
        assert isinstance(comps["dfthcsos"]["metrics"]["Ttot"], int)
        assert isinstance(comps["dfthcsos"]["metrics"]["Qtot"], int)
        assert isinstance(comps["invsqrt"]["metrics"]["Q"], int)
        # Cada una mejoró ~lo mismo respecto a su mejor real (reparto).
        real = {"dqi": 3.7676e11, "invsqrt": 100568.5, "dfthcsos": 3.268e8}
        factors = [real[t] / comps[t]["S"] for t in real]
        assert min(factors) > 1.0, factors
        assert max(factors) / min(factors) < 3.0, factors


def test_auto_kmb_sin_archivos_lo_dice():
    """Sin .kmb en runs, la validación lo dice y no tumba nada."""
    with tempfile.TemporaryDirectory() as d:
        out = run_auto(1.5, runs_dir=Path(d) / "runs")
        assert out["reached"] is True
        assert out["kmb_validation"]["present"] == []


def test_auto_kmb_basura_no_tumba_la_corrida():
    """Un .kmb falso en runs se reporta como no válido, sin crashear."""
    with tempfile.TemporaryDirectory() as d:
        runs = Path(d) / "runs"
        (runs / "dataset").mkdir(parents=True)
        (runs / "dataset" / "falso.kmb").write_text("esto no es un circuito")
        out = run_auto(1.5, runs_dir=runs)
        assert out["reached"] is True
        assert out["kmb_validation"]["present"], out["kmb_validation"]
        loaded = out["kmb_validation"]["loaded"]
        assert loaded, out["kmb_validation"]
        assert all(v["ok"] is False for v in loaded.values()), loaded

"""Tests de AUTO_MVP v1.2.0: el corredor autónomo (auto.py + seeds.py).

La regla que manda (Arturo): instalar, decir cuánto quieres, ejecutar.
Sin .kmb, sin número fijo, rondas 1-2-3-1-2-3. Cuando la combinación
llega a la meta, entrega el ZIP con las configuraciones y las métricas.
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
from auto_mvp.seeds import DEFAULT_SEEDS, default_seeds


def test_seeds_son_medidas_y_frescas():
    s1 = default_seeds()
    s2 = default_seeds()
    assert set(s1) == {"dqi", "invsqrt", "dfthcsos"}
    assert s1["dqi"]["base_metrics"] == {"Q": 1414, "T": 1_511_522,
                                         "eps_plus": 0.001188}
    assert s1["dqi"]["seed_graph"]["root"]["t_count"] == 1_511_522
    assert s1["invsqrt"]["base_metrics"]["Q"] == 62
    assert s1["dfthcsos"]["base_metrics"]["Qtot"] == 730
    # Frescas: mutar una no contamina la otra.
    s1["dqi"]["base_metrics"]["T"] = 1
    assert s2["dqi"]["base_metrics"]["T"] == 1_511_522
    assert DEFAULT_SEEDS["dqi"]["base_metrics"]["T"] == 1_511_522


def test_auto_meta_baja_llega_con_la_base_y_entrega_zip():
    """Meta 1.5: la base conocida (GM 23.94676) ya llega, sin correr nada."""
    with tempfile.TemporaryDirectory() as d:
        runs = Path(d) / "runs"
        out = run_auto(1.5, runs_dir=runs)
        assert out["reached"] is True, out
        assert out["rounds"] == 0
        assert abs(out["gm"] - 23.94676) / 23.94676 < 1e-4, out["gm"]
        assert out["zip"] != "" and Path(out["zip"]).is_file()
        with zipfile.ZipFile(out["zip"]) as zf:
            names = zf.namelist()
        assert "manifest.json" in names
        for task in ("dqi", "invsqrt", "dfthcsos"):
            assert f"{task}/component.json" in names, names
        assert not any(n.endswith((".kmb", ".kmx")) for n in names), names
        man = json.loads(
            zipfile.ZipFile(out["zip"]).read("manifest.json"))
        assert man["reached"] is True
        assert abs(man["gm"] - 23.94676) / 23.94676 < 1e-4
        assert man["components"]["dqi"]["S"] == 3.7676e11


def test_auto_meta_24_llega_por_fuerza_bruta():
    """Meta 24: lo real no llega (GM 23.94676), la fuerza bruta sí.

    v1.3.0: sin paro por estancamiento. La caminata aritmética baja
    las variables de costo hasta el S que cada tarea necesita y la
    combinación llega. El ZIP marca lo proyectado: lo real sigue
    siendo el mejor envío y lo demás es frontera, no medido.
    """
    with tempfile.TemporaryDirectory() as d:
        runs = Path(d) / "runs"
        out = run_auto(24.0, runs_dir=runs)
        assert out["reached"] is True, out
        assert out["projected"] is True, out
        assert out["gm"] >= 24.0, out["gm"]
        assert out["zip"] != "" and Path(out["zip"]).is_file()
        with zipfile.ZipFile(out["zip"]) as zf:
            names = zf.namelist()
            man = json.loads(zf.read("manifest.json"))
        assert man["reached"] is True
        assert man["projected"] is True
        assert not any(n.endswith((".kmb", ".kmx")) for n in names), names
        # Al menos un componente es fuerza bruta (proyectado, con ops).
        brute = [t for t, c in man["components"].items()
                 if not c["measured"]]
        assert brute, man["components"]
        for t in brute:
            assert man["components"][t]["kind"] == "brute"
            assert man["components"][t]["ops"], man["components"][t]


def test_auto_meta_invalida_falla_cerrado():
    with tempfile.TemporaryDirectory() as d:
        for bad in (0, -5, float("nan"), float("inf")):
            with pytest.raises(ValueError):
                run_auto(bad, runs_dir=Path(d) / "runs")


def test_auto_cli_target_requerido():
    import subprocess
    r = subprocess.run(
        [sys.executable, "-m", "auto_mvp.cli", "auto"],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True, text=True, timeout=60)
    assert r.returncode != 0
    assert "required" in r.stderr and "--target" in r.stderr

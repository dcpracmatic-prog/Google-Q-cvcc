"""AUTO_MVP v2.1 — verificación rápida DQI y química, protocolo oficial.

DQI: mismo chequeo y mismo costo que el verificador oficial, con
2,048 shots (con 256 aborta aunque haya 0 errores). El hash se toma
del ARCHIVO .kmb (para un .kmb es el mismo hash canónico: sha256 de
dqi_v1_logm7.kmb = a260f79a..., el oficial del v1-verify), porque el
``to_file`` del verificador falla en el venv de sandbox para
circuitos tamaño DQI.
Química: el verificador oficial vendido; 28 s por verificación y
reproduce el S de referencia exacto sobre el sample_submission.

Los tests que necesitan el dataset se saltan si no está (el dataset
vive fuera del repo, en el kit de la competencia o en /kaggle/input).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from auto_mvp.circuit import (ensure_dfthcsos_reference_data,
                              fast_verify_dfthcsos, fast_verify_dqi)

KIT = Path.home() / "workspace/sandbox-run/competition-kit"
KAGGLE_INPUT = Path("/kaggle/input")


def _dqi_reference_kmb() -> Path | None:
    for p in (KIT / "sample_submission/dqi.kmb",
              KAGGLE_INPUT / "google-verifiable-quantum-circuit-compilation"
              / "sample_submission/dqi.kmb"):
        if p.is_file():
            return p
    return None


def _dfthcsos_sample() -> Path | None:
    for p in (KIT / "sample_submission/dfthcsos",
              KAGGLE_INPUT / "google-verifiable-quantum-circuit-compilation"
              / "sample_submission/dfthcsos"):
        if (p / "submission.npz").is_file():
            return p
    return None


def test_fast_verify_dqi_reference():
    kmb = _dqi_reference_kmb()
    if kmb is None:
        pytest.skip("sin dataset: falta sample_submission/dqi.kmb")
    m = fast_verify_dqi(kmb, num_shots=2048, seed=1)
    assert m["valid"] is True, m.get("reason")
    assert m["qubits"] == 1893
    assert m["value_errors"] == 0 and m["phase_errors"] == 0
    assert m["eps_plus"] < 1 / 16
    assert m["S"] is not None and m["S"] > 0
    assert m["toffoli_count"] > 5_000_000


def test_fast_verify_dqi_v1():
    v1 = Path.home() / ("workspace/sandbox-run/dqi-ajustes/step2-q-mbuc"
                        "/work/dqi_v1_logm7.kmb")
    if not v1.is_file():
        pytest.skip("sin sandbox: falta dqi_v1_logm7.kmb")
    m = fast_verify_dqi(v1, num_shots=2048, seed=12345)
    assert m["valid"] is True, m.get("reason")
    assert m["qubits"] == 1888
    assert m["value_errors"] == 0 and m["phase_errors"] == 0
    # El smoke test oficial de V1: eps+ 0.0424, T 5,708,467.7, 37.2 s.
    assert abs(m["eps_plus"] - 0.0424) < 0.005
    assert abs(m["toffoli_count"] - 5708467.7) / 5708467.7 < 0.01


def test_fast_verify_dqi_truncated(tmp_path):
    kmb = _dqi_reference_kmb()
    if kmb is None:
        pytest.skip("sin dataset: falta sample_submission/dqi.kmb")
    bad = tmp_path / "bad.kmb"
    bad.write_bytes(kmb.read_bytes()[:1024])
    m = fast_verify_dqi(bad, num_shots=256)
    assert m["valid"] is False
    assert m["S"] is None


def test_fast_verify_dfthcsos_reference():
    sample = _dfthcsos_sample()
    if sample is None:
        pytest.skip("sin dataset: falta sample_submission/dfthcsos")
    m = fast_verify_dfthcsos(sample, sample / "submission.npz",
                             shots_per_address=1, seed=1)
    assert m["valid"] is True, m.get("reason")
    # El sample_submission puntúa EN la referencia (es el ejemplo).
    assert abs(m["S"] - 3355599588.3) / 3355599588.3 < 0.01
    assert m["num_circuits"] == 10


def test_ensure_dfthcsos_reference_data_missing(tmp_path, monkeypatch):
    # Sin fcidump en ningún lado: ni en el dir vendido ni en el dataset.
    import auto_mvp.circuit as circuit_mod
    monkeypatch.setattr(circuit_mod, "DFTHCSOS_DIR", tmp_path / "dfthcsos")
    monkeypatch.setattr(circuit_mod, "_dfthcsos_search_dirs",
                        lambda dataset_dir=None: [])
    with pytest.raises(RuntimeError):
        ensure_dfthcsos_reference_data(tmp_path / "no-existe")

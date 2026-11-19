"""Corredor LLM para DQI (llm_auto_dqi.py): el estratega mueve los
knobs del generador híbrido durante la ejecución.

El LLM propone deltas (batch, nslot, toom3); el generador
materializa y se mide Q/T/S; solo el menor S sobrevive. Sin llave,
el corredor sigue con los knobs por defecto.
"""
from __future__ import annotations

from auto_mvp.llm import LLMError
from auto_mvp.llm_auto_dqi import (
    _parse_deltas, dqi_S, run_llm_auto_dqi)


def _fake_llm_toom3(prompt):
    return {"deltas": [
        {"batch": 4, "nslot": 6, "toom3": True, "seed": 1,
         "reason": "toom3 baja T"},
        {"batch": 8, "nslot": 8, "toom3": True, "seed": 2,
         "reason": "batch 8 + toom3"},
    ]}

 

def _verified_small(**kwargs):
    """Mock válido para el flujo de búsqueda; la verificación real se prueba aparte."""
    n = int(kwargs["n"])
    nshots = int(kwargs.get("nshots", 8))
    nslot = n // 2 + 1
    return {
        "valid": True,
        "bm_sigma_correct": nslot * nshots,
        "bm_sigma_total": nslot * nshots,
        "scan_registers_intact": 2 * nslot * nshots,
        "scan_registers_total": 2 * nslot * nshots,
        "scan_phase_correct": nshots,
        "scan_phase_total": nshots,
        "scan_phase_errors": 0,
    }


def test_dqi_S_proyectado():
    # R * Q^2 * T con R=1.1912605.
    assert dqi_S(100, 1000) == 1.1912605 * 100 * 100 * 1000


def test_parse_deltas_dqi_valida_y_rechaza():
    ds = _parse_deltas(
        {"deltas": [{"batch": 17, "nslot": 36, "toom3": True,
                     "seed": 1, "reason": "x"}]}, 36)
    assert ds[0]["batch"] == 17 and ds[0]["toom3"] is True
    try:
        _parse_deltas(
            {"deltas": [{"batch": 17, "nslot": 10, "toom3": False,
                         "seed": 1}]}, 36)
    except ValueError as exc:
        assert "nslot" in str(exc)
    else:
        raise AssertionError("nslot bajo el mínimo debió fallar")


def test_llm_dqi_mejora_con_toom3(monkeypatch):
    import auto_mvp.llm_auto_dqi as dqi_module
    monkeypatch.setattr(dqi_module, "verify_small", _verified_small)
    # BARRIDO v2.17.6: antes de preguntar al LLM, el corredor mide
    # batch=1, 2, 3 con nslot mínimo. batch=1 da S=3.9983e10 (9.5%
    # mejor que la base 4.418e10) y es lo que guarda. El LLM
    # (falso) propone toom3, pero Toom-3 está DESACTIVADO (rompe
    # bm_backward): toom3=True ya no baja T, así que no lo supera.
    res = run_llm_auto_dqi(
        target_S=1e9, n=10, m=15, max_proposals=5,
        llm_client=_fake_llm_toom3, batch_size=2, verify=True,
        base_batch=4, base_nslot=6, base_toom3=False)
    assert res["llm_calls"] == 1
    assert res["llm_fallbacks"] == 0
    assert res["proposals"] == 5
    assert res["invalid"] == 0
    assert res["best_knobs"]["batch"] == 1
    assert res["best_knobs"]["nslot"] == 6
    assert res["best_knobs"]["toom3"] is False
    assert res["best_knobs"]["qubits"] == 1067
    assert res["best_knobs"]["toffoli_like"] == 29481
    assert res["best_S"] == 1.1912605 * 1067 ** 2 * 29481


def test_dqi_guarda_mejor_semilla_transparente(tmp_path, monkeypatch):
    import auto_mvp.llm_auto_dqi as dqi_module
    monkeypatch.setattr(dqi_module, "verify_small", _verified_small)
    # La semilla encontrada debe ser transparente: el circuito real
    # (.kmb) + la receta (JSON con knobs, Q/T/S y SHA256), para
    # reproducirla y evaluarla sin re-correr el LLM.
    import hashlib
    import json

    res = run_llm_auto_dqi(
        target_S=1e9, n=10, m=15, max_proposals=5,
        llm_client=_fake_llm_toom3, batch_size=2, verify=True,
        base_batch=4, base_nslot=6, base_toom3=False,
        output_dir=tmp_path)
    kmb = tmp_path / "mejor_semilla.kmb"
    recipe_p = tmp_path / "mejor_semilla.json"
    assert kmb.is_file() and kmb.stat().st_size > 0
    assert recipe_p.is_file()
    recipe = json.loads(recipe_p.read_text(encoding="utf-8"))
    # La receta trae todo lo necesario para reproducir y evaluar.
    # La mejor semilla es batch=1 (barrido v2.17.6), no la base.
    assert recipe["batch"] == 1 and recipe["nslot"] == 6
    assert recipe["toom3"] is False
    assert recipe["qubits"] == 1067
    assert recipe["toffoli_like"] == 29481
    assert abs(recipe["S"] - res["best_S"]) < 1e-6
    assert recipe["verify"] == {
        "bm_sigma": "48/48", "scan": "96/96", "phase": "8/8"}
    # El SHA256 de la receta es el del .kmb guardado.
    assert (hashlib.sha256(kmb.read_bytes()).hexdigest()
            == recipe["kmb_sha256"])
    assert res["semilla"]["kmb_sha256"] == recipe["kmb_sha256"]


def test_reproducir_semilla_coincide(tmp_path, monkeypatch):
    import auto_mvp.llm_auto_dqi as dqi_module
    monkeypatch.setattr(dqi_module, "verify_small", _verified_small)
    # Reconstruir con la receta da el mismo circuito (mismo SHA256):
    # la semilla es reproducible.
    from auto_mvp.llm_auto_dqi import reproducir_semilla

    res = run_llm_auto_dqi(
        target_S=1e9, n=10, m=15, max_proposals=5,
        llm_client=_fake_llm_toom3, batch_size=2, verify=True,
        base_batch=4, base_nslot=6, base_toom3=False,
        output_dir=tmp_path)
    out = reproducir_semilla(tmp_path / "mejor_semilla.json")
    assert out["coincide"] is True
    assert out["sha256"] == res["semilla"]["kmb_sha256"]
    assert out["qubits"] == 1067
    assert out["toffoli_like"] == 29481
    def no_key(prompt):
        raise LLMError("sin llave", no_key=True)

    res = run_llm_auto_dqi(
        target_S=1e9, n=10, m=15, max_proposals=5,
        llm_client=no_key, batch_size=2, verify=True,
        base_batch=4, base_nslot=6, base_toom3=False)
    assert res["llm_calls"] == 0
    assert res["llm_fallbacks"] == 1
    assert res["proposals"] == 5
    assert res["valid"] >= 2

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


def test_llm_dqi_mejora_con_toom3():
    res = run_llm_auto_dqi(
        target_S=1e9, n=10, m=15, max_proposals=2,
        llm_client=_fake_llm_toom3, batch_size=2, verify=True,
        base_batch=4, base_nslot=6, base_toom3=False)
    assert res["llm_calls"] == 1
    assert res["llm_fallbacks"] == 0
    assert res["proposals"] == 2
    assert res["invalid"] == 0
    # La base nativa (T=27264) es peor que el toom3 (T=22152):
    # el LLM propuso toom3 y el corredor lo guardó.
    assert res["best_knobs"]["toom3"] is True
    assert res["best_knobs"]["toffoli_like"] == 22152
    assert res["best_S"] < 1.1912605 * 1139 ** 2 * 27264


def test_dqi_guarda_mejor_semilla_transparente(tmp_path):
    # La semilla encontrada debe ser transparente: el circuito real
    # (.kmb) + la receta (JSON con knobs, Q/T/S y SHA256), para
    # reproducirla y evaluarla sin re-correr el LLM.
    import hashlib
    import json

    res = run_llm_auto_dqi(
        target_S=1e9, n=10, m=15, max_proposals=2,
        llm_client=_fake_llm_toom3, batch_size=2, verify=True,
        base_batch=4, base_nslot=6, base_toom3=False,
        output_dir=tmp_path)
    kmb = tmp_path / "mejor_semilla.kmb"
    recipe_p = tmp_path / "mejor_semilla.json"
    assert kmb.is_file() and kmb.stat().st_size > 0
    assert recipe_p.is_file()
    recipe = json.loads(recipe_p.read_text(encoding="utf-8"))
    # La receta trae todo lo necesario para reproducir y evaluar.
    assert recipe["batch"] == 4 and recipe["nslot"] == 6
    assert recipe["toom3"] is True
    assert recipe["qubits"] == 1139
    assert recipe["toffoli_like"] == 22152
    assert abs(recipe["S"] - res["best_S"]) < 1e-6
    assert recipe["verify"] == {"bm_sigma": "24/24", "scan": "12/12"}
    # El SHA256 de la receta es el del .kmb guardado.
    assert (hashlib.sha256(kmb.read_bytes()).hexdigest()
            == recipe["kmb_sha256"])
    assert res["semilla"]["kmb_sha256"] == recipe["kmb_sha256"]


def test_reproducir_semilla_coincide(tmp_path):
    # Reconstruir con la receta da el mismo circuito (mismo SHA256):
    # la semilla es reproducible.
    from auto_mvp.llm_auto_dqi import reproducir_semilla

    res = run_llm_auto_dqi(
        target_S=1e9, n=10, m=15, max_proposals=2,
        llm_client=_fake_llm_toom3, batch_size=2, verify=True,
        base_batch=4, base_nslot=6, base_toom3=False,
        output_dir=tmp_path)
    out = reproducir_semilla(tmp_path / "mejor_semilla.json")
    assert out["coincide"] is True
    assert out["sha256"] == res["semilla"]["kmb_sha256"]
    assert out["qubits"] == 1139
    assert out["toffoli_like"] == 22152
    def no_key(prompt):
        raise LLMError("sin llave", no_key=True)

    res = run_llm_auto_dqi(
        target_S=1e9, n=10, m=15, max_proposals=2,
        llm_client=no_key, batch_size=2, verify=True,
        base_batch=4, base_nslot=6, base_toom3=False)
    assert res["llm_calls"] == 0
    assert res["llm_fallbacks"] == 1
    assert res["proposals"] == 2
    assert res["valid"] >= 2

"""Generación autónoma de semillas (autonomous.py): el repo genera
circuitos de forma autónoma, sin base ni puntuación máxima.

El LLM propone la parametrización de cada semilla (batch, nslot,
toom3); el generador del repo materializa y mide Q/T/S; solo la que
baja el S respecto a la mejor hasta ahora sobrevive (mejora interna).
Sin modelo, sigue con los knobs por defecto.
"""
from __future__ import annotations

import json
from pathlib import Path

from auto_mvp.autonomous import (
    LocalLLM, run_autonomous, validate_code)


class _FakeLLM:
    """El modelo local falso: propone toom3 y una regla novel_nslot."""

    def __init__(self, code_ok: bool = True) -> None:
        self.code_ok = code_ok
        self.calls_json = 0
        self.calls_code = 0

    def complete_json(self, prompt, max_tokens=512):
        self.calls_json += 1
        return {"deltas": [
            {"batch": 4, "nslot": 6, "toom3": True, "seed": 1,
             "reason": "toom3 baja T"},
        ]}

    def complete_code(self, prompt, max_tokens=512):
        # Como LocalLLM.complete_code: devuelve el código YA extraído
        # (sin las cercas ```python). Si se devuelven las cercas, la
        # guarda lo rechaza por sintaxis (eso era un bug del falso).
        self.calls_code += 1
        if not self.code_ok:
            return ("def novel_nslot(n):\n"
                    "    return circ  # roto: circ no existe\n")
        return ("def novel_nslot(n):\n"
                "    return n // 2 + 2\n")


def test_validate_code_acepta_y_rechaza():
    ok, _ = validate_code(
        "def novel_nslot(n):\n    return n // 2 + 2\n",
        entry="novel_nslot")
    assert ok is True
    # import prohibido
    ok, reason = validate_code(
        "import os\n\ndef novel_nslot(n):\n    return n // 2 + 1\n",
        entry="novel_nslot")
    assert ok is False and "os" in reason
    # no define la función pedida
    ok, reason = validate_code(
        "def otra(n):\n    return n\n", entry="novel_nslot")
    assert ok is False and "novel_nslot" in reason
    # nombre prohibido
    ok, reason = validate_code(
        "def novel_nslot(n):\n    return eval('n')\n",
        entry="novel_nslot")
    assert ok is False and "eval" in reason
    # import fuera de la lista blanca
    ok, reason = validate_code(
        "import random\n\ndef novel_nslot(n):\n    return n // 2 + 1\n",
        entry="novel_nslot")
    assert ok is False and "random" in reason


def test_local_llm_sin_llama_cpp_falla_claro(tmp_path):
    # Sin llama-cpp-python instalado, construir el modelo debe
    # fallar con un mensaje claro (no con un ImportError crudo).
    # En este entorno llama-cpp-python NO está instalado (verificado
    # por el usuario: solo en Kaggle).
    try:
        import llama_cpp  # noqa: F401
    except ImportError:
        pass
    else:
        return  # si está instalado, el test no aplica
    try:
        LocalLLM(model_path=tmp_path / "no_existe.gguf")
    except RuntimeError as exc:
        assert "llama-cpp-python" in str(exc)
    else:
        raise AssertionError("sin llama-cpp-python debió fallar")


def test_autonomous_genera_semillas(tmp_path):
    fake = _FakeLLM(code_ok=True)
    res = run_autonomous(
        fake, n=10, m=15, n_semillas=3, time_budget_seconds=300,
        output_dir=tmp_path, seed=42, verify=True)
    # Semilla 0 + 3 propuestas + 1 con novel_nslot = 5 semillas.
    assert len(res["semillas"]) == 5
    assert res["llm_calls"] == 3
    assert res["llm_fallbacks"] == 0
    assert fake.calls_json == 3
    assert fake.calls_code == 1
    # Todas válidas (el generador del repo + verify_small).
    assert all(s["valid"] for s in res["semillas"])
    # La mejor es la de toom3 (T=22152 < T nativa=27264): el LLM
    # propuso toom3 y la corrida lo guardó.
    assert res["mejor"]["toom3"] is True
    assert res["mejor"]["toffoli_like"] == 22152
    # La parametrización nueva se midió y se guardó.
    assert res["param_nueva"]["status"] == "medido"
    assert res["param_nueva"]["nslot"] == 7  # 10//2+2
    # Los archivos de salida existen y traen las parametrizaciones.
    semillas = json.loads((tmp_path / "semillas.json").read_text())
    assert len(semillas["semillas"]) == 5
    assert semillas["semillas"][0]["origen"].startswith("primera")
    assert semillas["semillas"][1]["origen"] == "LLM local"
    veredicto = json.loads((tmp_path / "VEREDICTO.json").read_text())
    assert veredicto["n_semillas"] == 5
    assert veredicto["mejor_semilla"]["toom3"] is True


def test_autonomous_sin_llm_sigue_con_defecto(tmp_path):
    res = run_autonomous(
        None, n=10, m=15, n_semillas=2, time_budget_seconds=300,
        output_dir=tmp_path, seed=42, verify=True)
    # Sin modelo: 2 fallbacks, pero las semillas se generan igual.
    assert res["llm_calls"] == 0
    assert res["llm_fallbacks"] == 2
    assert len(res["semillas"]) >= 3  # 0 + 2 (sin param nueva)
    assert all(s["valid"] for s in res["semillas"])
    assert res["param_nueva"]["status"] == "falló"


def test_autonomous_codigo_roto_no_aborta(tmp_path):
    fake = _FakeLLM(code_ok=False)
    res = run_autonomous(
        fake, n=10, m=15, n_semillas=2, time_budget_seconds=300,
        output_dir=tmp_path, seed=42, verify=True)
    # El código roto de novel_nslot no aborta la corrida: las
    # semillas se generan igual y la parametrización queda en "falló".
    assert len(res["semillas"]) == 3  # 0 + 2 (sin la de novel_nslot)
    assert res["param_nueva"]["status"] == "falló"
    assert res["llm_calls"] == 2

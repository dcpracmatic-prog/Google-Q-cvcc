"""Generación autónoma de semillas (autonomous.py): el repo genera
circuitos de forma autónoma, sin base ni puntuación máxima.

El LLM propone la parametrización de cada semilla (batch, nslot,
toom3); el generador del repo materializa y mide Q/T/S; solo la que
baja el S respecto a la mejor hasta ahora sobrevive (mejora interna).
Sin modelo, sigue con los knobs por defecto.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from auto_mvp.autonomous import (
    LocalLLM, run_autonomous, run_tres_tareas, validate_code)


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


class _FakeLLMRepo:
    """Falso v2.17.5: knobs distintos cada vez y código que USA
    estructuras .py del repo (importa R_DQI de llm_auto_dqi)."""

    _KNOBS = [(4, 6, True), (8, 7, True), (17, 8, False),
              (36, 9, True), (4, 10, False), (8, 11, True)]
    _SEED = [(8, 3, False), (17, 4, True), (36, 5, True),
             (4, 6, False)]

    def __init__(self) -> None:
        self.calls_json = 0
        self.calls_code = 0

    def complete_json(self, prompt, max_tokens=512):
        b, s, t = self._KNOBS[self.calls_json % len(self._KNOBS)]
        self.calls_json += 1
        return {"deltas": [
            {"batch": b, "nslot": s, "toom3": t, "seed": 1,
             "reason": "distinto"},
        ]}

    def complete_code(self, prompt, max_tokens=512):
        self.calls_code += 1
        if "novel_seed" in prompt:
            b, off, t = self._SEED[
                (self.calls_code - 1) % len(self._SEED)]
            return (
                "from auto_mvp.llm_auto_dqi import R_DQI\n"
                "\n"
                "def novel_seed(n, m):\n"
                "    _ = R_DQI  # usa una estructura del repo\n"
                f"    return {{'batch': {b}, 'nslot': n // 2 + {off}, "
                f"'toom3': {t}}}\n")
        # novel_nslot: nslot distinto cada vez (10, 11, 12, ...).
        off = 5 + (self.calls_code - 1) % 4
        return f"def novel_nslot(n):\n    return n // 2 + {off}\n"


def test_import_autonomous_sin_kickmix():
    # Regresión v2.17.1 (bug que tumbó el Notebook v2 en Kaggle):
    # en Kaggle `import kickmix` trae un paquete VACÍO (sin
    # GF2Field) y `build_hybrid_bm` crea `km.GF2Field(...)` al
    # importarse. Importar autonomous NO debe tocar kickmix: el
    # import perezoso lo deja para `run_autonomous` (después de
    # `setup_kaggle`). Subproceso limpio con kickmix vacío.
    code = (
        "import sys, types\n"
        "sys.modules['kickmix'] = types.ModuleType('kickmix')\n"
        "from auto_mvp.autonomous import (LocalLLM, run_autonomous, "
        "setup_kaggle, validate_code)\n"
        "print('import autonomous OK sin kickmix')\n"
    )
    r = subprocess.run([sys.executable, "-c", code],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-800:]
    assert "import autonomous OK sin kickmix" in r.stdout


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
    # Toom-3 DESACTIVADO (rompe bm_backward): la mejor es la nativa
    # (T=33051, toom3=False); el knob toom3 ya no baja T.
    # v2.17.9: T 28587 -> 29481 (inversos directos, Montgomery
    # desactivado por fase; ver notes/v2.17.9.md).
    # v2.17.16: T 29481 -> 33051 (el arreglo limpia hist_mult e
    # is_zero de forma unitaria antes de liberarlos; ver el test
    # de regresión test_full_circuit_phase_with_random_masks).
    assert res["mejor"]["toom3"] is False
    assert res["mejor"]["toffoli_like"] == 33051
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
    assert veredicto["mejor_semilla"]["toom3"] is False


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


def test_autonomous_medicion_que_falla_no_tumba(tmp_path, monkeypatch):
    # v2.17.2: si la medición de UNA semilla falla, se registra como
    # inválida y la corrida sigue (antes tumbaba todo sin guardar
    # nada). Se simula fallando la 2ª medición.
    import auto_mvp.llm_auto_dqi as _dqi
    real_measure = _dqi._measure_knobs
    calls = {"n": 0}

    def flaky(n, m, batch, nslot, toom3, verify=True):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("falla simulada del generador")
        return real_measure(n, m, batch, nslot, toom3, verify=verify)

    monkeypatch.setattr(_dqi, "_measure_knobs", flaky)
    fake = _FakeLLM(code_ok=True)
    res = run_autonomous(
        fake, n=10, m=15, n_semillas=2, time_budget_seconds=300,
        output_dir=tmp_path, seed=42, verify=True)
    # La corrida terminó: semilla 0 válida, semilla 1 inválida
    # (medición falló), semilla 2 válida. No se tumbó.
    assert len(res["semillas"]) >= 3
    assert res["semillas"][0]["valid"] is True
    assert res["semillas"][1]["valid"] is False
    assert res["invalid"] >= 1
    assert res["mejor"]["valid"] is True
    # El progreso quedó en archivo (con flush) para diagnosticar.
    prog = (tmp_path / "progreso.txt").read_text()
    assert "semilla" in prog
    assert (tmp_path / "semillas.json").exists()


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


def test_no_repeticion_penaliza_y_no_mide_repetidas(tmp_path):
    # v2.17.5 (pedido de Arturo; la v4 en Kaggle repitió la mejor
    # semilla: la #13 era idéntica a la #1): el falso propone
    # SIEMPRE los mismos knobs (4,6,True). La 1ª vez se mide; las
    # siguientes son REPETIDAS: se cuentan y NO se miden (se busca
    # otro). Todas las semillas medidas son distintas.
    fake = _FakeLLM(code_ok=True)
    res = run_autonomous(
        fake, n=10, m=15, n_semillas=3, time_budget_seconds=300,
        output_dir=tmp_path, seed=42, verify=True)
    assert res["repetidas"] >= 2  # 2ª y 3ª propuesta repetidas
    knobs = [(s["batch"], s["nslot"], s["toom3"])
             for s in res["semillas"] if s.get("valid")]
    assert len(knobs) == len(set(knobs))
    assert res["unicas"] == len(set(knobs))
    assert res["mejor"]["valid"] is True


def test_codigo_repo_usa_estructuras_del_repo(tmp_path):
    # v2.17.5: el código novel_seed importa una estructura .py del
    # repo (R_DQI de llm_auto_dqi) y se ejecuta; los knobs que
    # devuelve se miden. validate_code acepta el import de auto_mvp.
    ok, _ = validate_code(
        "from auto_mvp.llm_auto_dqi import R_DQI\n"
        "\n"
        "def novel_seed(n, m):\n"
        "    _ = R_DQI\n"
        "    return {'batch': 8, 'nslot': n // 2 + 3, "
        "'toom3': False}\n",
        entry="novel_seed")
    assert ok is True
    fake = _FakeLLMRepo()
    res = run_tres_tareas(
        fake, n=10, m=15, n_objetivo=2, time_budget_seconds=300,
        output_dir=tmp_path, seed=42, verify=True)
    t2 = res["tareas"]["codigo_repo"]
    # La tarea 2 midió al menos 1 semilla desde código del repo.
    assert len(t2["semillas"]) >= 1
    assert all(s["origen"].startswith("codigo_repo")
               for s in t2["semillas"])
    assert all(s["valid"] for s in t2["semillas"])


def test_tres_tareas_completan_sin_repetir(tmp_path):
    # v2.17.5: las 3 tareas corren (knobs, codigo_repo,
    # param_nueva) a escala chica (2 circuitos distintos c/u) y
    # ninguna semilla medida se repite (el seen es global).
    fake = _FakeLLMRepo()
    res = run_tres_tareas(
        fake, n=10, m=15, n_objetivo=2, time_budget_seconds=300,
        output_dir=tmp_path, seed=42, verify=True)
    assert set(res["tareas"].keys()) == {
        "knobs", "codigo_repo", "param_nueva"}
    assert len(res["tareas"]["knobs"]["semillas"]) >= 3  # 0 + 2
    assert len(res["tareas"]["codigo_repo"]["semillas"]) >= 1
    assert len(res["tareas"]["param_nueva"]["semillas"]) >= 1
    # Ninguna semilla medida se repite (knobs distintos).
    knobs = [(s["batch"], s["nslot"], s["toom3"])
             for s in res["semillas"]
             if s.get("valid") and "batch" in s]
    assert len(knobs) == len(set(knobs))
    assert res["unicas"] == len(set(knobs))
    assert res["mejor"]["valid"] is True
    assert (tmp_path / "tres_tareas.json").exists()
    assert (tmp_path / "semillas.json").exists()
    assert (tmp_path / "VEREDICTO.json").exists()

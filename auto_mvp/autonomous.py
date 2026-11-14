"""AUTO_MVP v2.17 — generación AUTÓNOMA de semillas de circuitos
desde el repositorio (el ejecutor delgado).

Arturo (2026-11-14): el repositorio es lo que se está validando y el
Notebook solo debe ser un código de ejecución, automático: hace las
instalaciones y las importaciones, empieza a trabajar y entrega
circuitos. La lógica vive AQUÍ, en el repo, no en celdas amplias del
Notebook.

Lo que hace este módulo (todo desde el repo, sin baseline, sin
puntuación máxima):

1. `LocalLLM`: el LLM local Qwen2.5-Coder-1.5B-Instruct (GGUF Q4_K_M,
   llama-cpp-python, temp 0.7). Se instala y se descarga EN KAGGLE
   (el Notebook lo hace; el modelo de 1 GB NO va en el repo). Sin
   Gemini/Groq, sin llave. `llama_cpp` se importa perezoso: este
   módulo se importa aunque llama-cpp-python no esté instalado.
2. `validate_code`: guarda de imports para el código que propone el
   modelo (solo math/typing/auto_mvp/kickmix; nada de os/sys/
   subprocess/eval/exec). Nada que falle la guarda se ejecuta.
3. `setup_kaggle`: encuentra la competencia en /kaggle/input y deja
   `kickmix` con Circuit (el kickmix.so del dataset o pip
   force-reinstall). Es la parte Kaggle del repo.
4. `run_autonomous`: el bucle autónomo. Genera la primera semilla
   (sin base: es la primera, no una referencia) con el generador del
   repo (`build_hybrid_bm_circuit`) y la mide (Q/T/S + validez con
   `verify_small`). Después, el LLM propone la parametrización de
   cada semilla nueva (batch, nslot, toom3) y solo sobrevive la que
   baja el S respecto a la mejor hasta ahora (mejora interna,
   autónoma; no hay meta externa ni puntuación máxima). Al final,
   el LLM propone una parametrización nueva (una regla `novel_nslot`
   chica, no un circuito entero) y se mide una semilla con ella.
   Guarda `semillas.json` (las semillas + sus parametrizaciones),
   `param_nueva.json` y `VEREDICTO.json` en `output_dir`.

Uso desde el Notebook (delgado, 2 celdas de código)::

    # celda de instalación (Kaggle): clonar el repo, pip install
    # llama-cpp-python, bajar el GGUF Q4_K_M y verificar su SHA256.
    from auto_mvp.autonomous import LocalLLM, run_autonomous, setup_kaggle
    setup_kaggle()
    llm = LocalLLM(model_path="/kaggle/working/qwen2.5-coder-1.5b-instruct-q4_k_m.gguf")
    # celda de ejecución (una línea):
    result = run_autonomous(llm, n=30, m=255, n_semillas=12,
                            time_budget_seconds=1200,
                            output_dir="/kaggle/working")

Sin modelo (sin GGUF o sin llama-cpp-python), `run_autonomous`
acepta un cliente falso o None y sigue con los knobs por defecto:
la corrida nunca depende del modelo; el modelo solo la guía.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from .circuits.generators.build_hybrid_bm import (
    build_hybrid_bm_circuit, verify_small)
from .llm import LLMError
from .llm_auto_dqi import R_DQI, _measure_knobs, _parse_deltas, dqi_S

# GGUF Q4_K_M del Qwen2.5-Coder-1.5B-Instruct (HuggingFace). El
# Notebook lo baja EN Kaggle y verifica este SHA256; el archivo NO
# va en el repo (1 GB).
QWEN_GGUF_URL = (
    "https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF/"
    "resolve/main/qwen2.5-coder-1.5b-instruct-q4_k_m.gguf")
QWEN_GGUF_SHA256 = (
    "cc324af070c2ecbfd324a30884d2f951a7ff756aba85cb811a6ec436933bb046")
QWEN_GGUF_BYTES = 1117320768

# Temperatura del modelo: rango de Arturo (0.7-0.8). Creatividad
# matemática sin romper la estructura de importaciones de Python.
TEMP = 0.7

# Knobs por defecto (sin modelo): batch/nslot rotando, toom3
# alternando. Son los knobs que el LLM movería.
_DEFAULT_BATCH = (4, 8, 17, 36)
_DEFAULT_NSLOT_EXTRA = (0, 2, 6)

# Guarda de imports (sin romper la estructura de Python).
_ALLOWED = {"math", "typing", "dataclasses", "functools", "itertools",
            "collections", "enum", "auto_mvp", "kickmix"}
_BLOCKED_MOD = {"os", "sys", "subprocess", "socket", "urllib", "http",
                "pathlib", "shutil", "importlib", "builtins", "code",
                "ctypes", "inspect", "pkgutil", "runpy"}
_BLOCKED_NAMES = {"eval", "exec", "open", "compile", "__import__",
                  "globals", "locals", "vars", "input", "breakpoint",
                  "getattr", "setattr", "delattr", "hasattr"}
_BLOCKED_ATTRS = {"__class__", "__subclasses__", "__bases__", "__mro__",
                  "__dict__", "__globals__", "__code__", "__closure__"}


def validate_code(code: str, entry: str = "novel_nslot"
                  ) -> tuple[bool, str]:
    """(True, '') si el código pasa la guarda; (False, razón) si no.
    No ejecuta nada."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return False, f"sintaxis inválida: {exc}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in _BLOCKED_MOD:
                    return False, f"import prohibido: {alias.name}"
                if top not in _ALLOWED:
                    return False, ("import fuera de la lista blanca: "
                                   f"{alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                return False, "import relativo no permitido"
            top = node.module.split(".")[0]
            if top in _BLOCKED_MOD:
                return False, f"import prohibido: {node.module}"
            if top not in _ALLOWED:
                return False, ("import fuera de la lista blanca: "
                               f"{node.module}")
        elif isinstance(node, ast.Name):
            if node.id in _BLOCKED_NAMES:
                return False, f"nombre prohibido: {node.id}"
        elif isinstance(node, ast.Attribute):
            if node.attr in _BLOCKED_ATTRS:
                return False, f"atributo prohibido: {node.attr}"
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            return False, "global/nonlocal no permitido"
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    names = [f.name for f in funcs]
    if entry not in names:
        return False, f"no define {entry!r} (define: {names})"
    fn = next(f for f in funcs if f.name == entry)
    if not fn.args.args and not fn.args.vararg:
        return False, f"la función {entry!r} no tiene parámetros"
    return True, ""


class LocalLLM:
    """El LLM local Qwen2.5-Coder-1.5B-Instruct (GGUF Q4_K_M).

    `llama_cpp` se importa aquí (perezoso): el módulo se importa
    aunque llama-cpp-python no esté instalado; el error sale solo
    al construir el modelo. `model_path` es el GGUF ya descargado
    (el Notebook lo baja en Kaggle y verifica su SHA256).
    """

    def __init__(self, model_path: str | Path, n_ctx: int = 2048,
                 n_threads: int = 4, temp: float = TEMP) -> None:
        try:
            from llama_cpp import Llama
        except ImportError as exc:
            raise RuntimeError(
                "llama-cpp-python no está instalado: "
                "pip install llama-cpp-python (en Kaggle, en el "
                "Notebook)") from exc
        path = Path(model_path)
        if not path.exists():
            raise RuntimeError(f"el GGUF no existe: {path}")
        self._llm = Llama(model_path=str(path), n_ctx=int(n_ctx),
                          n_threads=int(n_threads), verbose=False)
        self.temp = float(temp)
        if not (0.7 <= self.temp <= 0.8):
            raise ValueError(f"temp={temp} fuera del rango 0.7-0.8")
        self.model_path = str(path)

    def complete(self, prompt: str, max_tokens: int = 1024) -> str:
        """Texto crudo del modelo (chat, temp 0.7)."""
        out = self._llm.create_chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=self.temp, max_tokens=int(max_tokens), stop=[])
        return out["choices"][0]["message"]["content"]

    def complete_json(self, prompt: str, max_tokens: int = 1024
                      ) -> dict[str, Any]:
        """El estratega local: devuelve un JSON (misma interfaz que
        auto_mvp.llm.complete_json)."""
        text = self.complete(prompt, max_tokens=max_tokens)
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError(
                f"el modelo local no devolvió un JSON: {text[:200]}")
        return json.loads(text[start:end + 1])

    def complete_code(self, prompt: str, max_tokens: int = 1024) -> str:
        """El creador local: devuelve código Python (primer bloque
        ```python)."""
        text = self.complete(prompt, max_tokens=max_tokens)
        m = re.search(r"```(?:python|py)?\s*\n(.*?)\n```", text, re.S)
        code = (m.group(1) if m else text).strip()
        if not code:
            raise ValueError("el modelo local no devolvió código Python")
        return code


def setup_kaggle(input_dir: str | Path = "/kaggle/input") -> Path:
    """Deja `kickmix` con Circuit en Kaggle (la parte Kaggle del repo).

    Encuentra la competencia en /kaggle/input (los montajes vienen
    ANIDADOS) y, si `import kickmix` trae un paquete VACÍO sin
    Circuit, carga el kickmix.so del dataset (o pip force-reinstall
    kickmix==1.0.0). Devuelve el directorio de la competencia.
    """
    inp = Path(input_dir)

    def _buscar(fragmento: str) -> Path | None:
        conocidos = [
            inp / "competitions"
            / "google-verifiable-quantum-circuit-compilation",
            inp / "google-verifiable-quantum-circuit-compilation",
        ]
        for cand in conocidos:
            if fragmento in cand.name and cand.exists():
                return cand
        if inp.exists():
            for cand in sorted(inp.rglob("*")):
                if cand.is_dir() and fragmento in cand.name.lower():
                    return cand
        return None

    comp = _buscar("verifiable") or _buscar("google")
    if comp is None:
        raise RuntimeError(
            "No se encontró el dataset de la competencia en "
            f"{input_dir}")

    def _km_ok() -> bool:
        try:
            import kickmix as _km
            return hasattr(_km, "Circuit") and hasattr(_km, "Simulator")
        except Exception:
            return False

    if not _km_ok():
        try:
            import shutil
            so = comp / "kickmix" / "kickmix.so"
            if so.exists():
                shutil.copy(str(so), "/kaggle/working/kickmix.so")
                sys.path.insert(0, "/kaggle/working")
                if "kickmix" in sys.modules:
                    del sys.modules["kickmix"]
                import kickmix  # noqa: F401
        except Exception:
            pass
    if not _km_ok():
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q",
             "--force-reinstall", "kickmix==1.0.0"],
            capture_output=True, text=True, timeout=300)
        if "kickmix" in sys.modules:
            del sys.modules["kickmix"]
        import kickmix  # noqa: F401
        if not _km_ok():
            raise RuntimeError(
                "kickmix sin Circuit tras pip install "
                f"(returncode={r.returncode}): no se pueden generar "
                "circuitos")
    return comp


def _prompt_autonomous(best: dict[str, Any],
                       history: list[dict[str, Any]],
                       n: int, m: int) -> str:
    """El prompt del estratega autónomo: propone UNA parametrización.

    Sin meta externa ni puntuación máxima: solo tratar de hacerlo
    mejor que la mejor semilla hasta ahora.
    """
    hist = "\n".join(
        f"- semilla {h.get('semilla')}: batch={h.get('batch')}, "
        f"nslot={h.get('nslot')}, toom3={h.get('toom3')}: "
        f"{'S=' + str(h.get('S')) if h.get('valid') else 'inválida'}"
        for h in history[-8:])
    return (
        "Eres el estratega de un generador autónomo de circuitos "
        "cuánticos (decodificador DQI híbrido). Responde SOLO con un "
        "JSON, sin texto fuera del JSON.\n\n"
        f"Tarea: generar la siguiente semilla (n={n}, m={m}). El "
        f"puntaje S es menor-mejor (S = R * Q^2 * T, R={R_DQI}). La "
        "mejor semilla hasta ahora es:\n"
        f"{json.dumps(best, ensure_ascii=False)}\n\n"
        "Lo ya generado:\n"
        f"{hist or '- nada todavía'}\n\n"
        "Propón UNA parametrización distinta como JSON: "
        '{"batch": 4|8|17|36, "nslot": <entero>, "toom3": true|false, '
        '"seed": <entero>, "reason": "<una frase>"}. '
        f"nslot debe ser >= {n // 2 + 1} (si no, el circuito no cabe). "
        "No hay meta externa ni puntuación máxima: solo trata de "
        "hacerlo mejor que la mejor semilla hasta ahora. Varía batch, "
        "nslot y toom3."
    )


def _prompt_novel_nslot(n: int) -> str:
    """El prompt de la parametrización nueva: UNA función chica."""
    return (
        "Escribe UNA función Python llamada novel_nslot(n) que devuelva "
        "el número de slots nslot para un decodificador DQI con n "
        "registros.\n\n"
        "Reglas:\n"
        "- Solo puedes importar math, typing, dataclasses, auto_mvp, "
        "kickmix. NO uses os, sys, subprocess, eval, exec, open, "
        "getattr.\n"
        "- La función recibe n (entero, número de registros) y "
        "devuelve un entero >= n//2+1 (si no, el circuito no cabe).\n"
        "- La regla por defecto es n//2+1. Propón una fórmula DISTINTA "
        "que creas que baje los Toffolis o los qubits: por ejemplo, un "
        "nslot que crezca más lento que n, o que dependa de la paridad "
        "de n, o que use un margen distinto.\n"
        "- Escribe SOLO la función, completa y funcional, sin "
        "comentarios de relleno ni '...' ni 'pass'.\n\n"
        "Responde SOLO con un bloque ```python con la función. Sin "
        "texto fuera del bloque."
    )


def _default_delta(round_no: int, min_nslot: int,
                   seed: int) -> dict[str, Any]:
    """Knobs por defecto (sin modelo): batch/nslot rotando, toom3
    alternando."""
    k = int(round_no)
    return {
        "batch": _DEFAULT_BATCH[k % len(_DEFAULT_BATCH)],
        "nslot": int(min_nslot) + _DEFAULT_NSLOT_EXTRA[
            k % len(_DEFAULT_NSLOT_EXTRA)],
        "toom3": bool(k % 2 == 0),
        "seed": int(seed) + k,
        "reason": "sin modelo: knobs por defecto rotando",
    }


def run_autonomous(llm: Any | None, n: int = 30, m: int = 255,
                   n_semillas: int = 12,
                   time_budget_seconds: float | None = 1200,
                   output_dir: str | Path | None = None,
                   seed: int = 42, verify: bool = True,
                   on_seed: Callable[[dict[str, Any]], None] | None = None
                   ) -> dict[str, Any]:
    """Generación AUTÓNOMA de semillas de circuitos (desde el repo).

    `llm` es el modelo local (LocalLLM) o un cliente con
    `complete_json(prompt)` y `complete_code(prompt)`; si es None,
    se generan las semillas con los knobs por defecto (la corrida
    nunca depende del modelo). No hay base, no hay baseline, no hay
    puntuación máxima: la primera semilla se genera y se mide, y
    cada semilla nueva solo trata de hacerlo mejor que la mejor
    hasta ahora (mejora interna, autónoma).

    Devuelve {n, m, R, llm_calls, llm_fallbacks, mejor, semillas,
    param_nueva}. Si `output_dir` se da, guarda `semillas.json`
    (las semillas + sus parametrizaciones), `param_nueva.json` y
    `VEREDICTO.json` ahí.
    """
    if n < 2 or m < 1:
        raise ValueError(f"n={n}, m={m} inválidos")
    min_nslot = (n // 2) + 1

    def _progress(entry: dict[str, Any]) -> None:
        print(f"[autónomo] {entry}", file=sys.stderr, flush=True)
        if on_seed is not None:
            on_seed(entry)

    started = time.monotonic()
    semillas: list[dict[str, Any]] = []
    llm_calls = 0
    llm_fallbacks = 0

    # Semilla 0: la primera, generada (sin base: es la primera
    # semilla, no una referencia).
    primera = _measure_knobs(n, m, 4, min_nslot, False, verify=verify)
    primera.update({"semilla": 0,
                    "origen": "primera generada (sin base)",
                    "mejora": False})
    if not primera["valid"]:
        raise RuntimeError(
            "la primera semilla no es válida: "
            f"{primera.get('reason', '')}")
    semillas.append(primera)
    mejor = dict(primera)
    best_S = float(primera["S"])
    _progress({"semilla": 0, "S": best_S, "valid": True,
               "knobs": {k: primera[k] for k in
                         ("batch", "nslot", "toom3")},
               "note": "primera generada"})

    # Semillas 1..n_semillas: el LLM propone la parametrización;
    # el repo genera y mide. Sin modelo, knobs por defecto.
    for i in range(1, int(n_semillas) + 1):
        if (time_budget_seconds is not None
                and time.monotonic() - started
                >= float(time_budget_seconds)):
            break
        llm_ok = False
        llm_error = ""
        try:
            if llm is None:
                raise LLMError("sin modelo", no_key=True)
            raw = llm.complete_json(
                _prompt_autonomous(mejor, semillas, n, m),
                max_tokens=512)
            delta = _parse_deltas(raw, min_nslot)[0]
            llm_ok = True
            llm_calls += 1
        except (LLMError, ValueError, KeyError, TypeError) as exc:
            llm_error = str(exc)[:200]
            delta = _default_delta(i, min_nslot, seed)
            llm_fallbacks += 1
        entry = _measure_knobs(n, m, delta["batch"], delta["nslot"],
                               delta["toom3"], verify=verify)
        entry.update({"semilla": int(i),
                      "origen": "LLM local" if llm_ok else "por defecto",
                      "reason_llm": delta.get("reason", "")})
        if llm_error:
            entry["llm_error"] = llm_error
        if not entry["valid"]:
            entry["mejora"] = False
            entry["note"] = "INVÁLIDA: no cuenta"
        elif entry["S"] < best_S:
            best_S = float(entry["S"])
            mejor = dict(entry)
            entry["mejora"] = True
            entry["note"] = "MEJORA: nueva mejor semilla"
        else:
            entry["mejora"] = False
            entry["note"] = "válida pero no mejora"
        semillas.append(entry)
        _progress(entry)

    # Parametrización nueva: el LLM propone una regla `novel_nslot`
    # (una función chica). Con guarda de imports; si falla, se
    # registra y se sigue (nunca aborta la corrida).
    param_nueva: dict[str, Any] = {"status": "no intentado"}
    try:
        if llm is None or not hasattr(llm, "complete_code"):
            raise LLMError("sin generador de código", no_key=True)
        code = llm.complete_code(_prompt_novel_nslot(n), max_tokens=512)
        ok, reason = validate_code(code, entry="novel_nslot")
        param_nueva.update({"guard_ok": bool(ok),
                            "guard_reason": reason,
                            "code_chars": len(code)})
        if not ok:
            param_nueva["status"] = "rechazado por la guarda"
        else:
            tmp = Path(output_dir) / "novel_nslot.py" \
                if output_dir is not None else Path("novel_nslot.py")
            tmp.write_text(code, encoding="utf-8")
            spec = importlib.util.spec_from_file_location(
                "novel_nslot", tmp)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            ns = mod.novel_nslot(n)
            if not isinstance(ns, int) or ns < min_nslot:
                raise ValueError(
                    f"novel_nslot devolvió {ns!r}, inválido "
                    f"(< {min_nslot} o no entero)")
            entry = _measure_knobs(n, m, mejor["batch"], int(ns),
                                   mejor["toom3"], verify=verify)
            entry.update({"semilla": len(semillas),
                          "origen": "parametrización nueva (novel_nslot)",
                          "mejora": bool(entry["valid"]
                                         and entry["S"] < best_S)})
            if entry["mejora"]:
                best_S = float(entry["S"])
                mejor = dict(entry)
            semillas.append(entry)
            param_nueva.update({"status": "medido", "nslot": int(ns),
                                "Q": entry["qubits"],
                                "T": entry["toffoli_like"],
                                "S": entry["S"], "valid": entry["valid"],
                                "mejora": entry["mejora"]})
            _progress(entry)
    except Exception as exc:
        param_nueva.update({"status": "falló",
                            "error": str(exc)[:300]})
        _progress({"note": "parametrización nueva falló",
                   "error": str(exc)[:200]})

    result: dict[str, Any] = {
        "n": int(n), "m": int(m), "R": R_DQI,
        "llm_calls": llm_calls, "llm_fallbacks": llm_fallbacks,
        "mejor": mejor, "semillas": semillas,
        "param_nueva": param_nueva,
    }
    if output_dir is not None:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "semillas.json").write_text(
            json.dumps(result, indent=2, default=str))
        (out / "param_nueva.json").write_text(
            json.dumps(param_nueva, indent=2, default=str))
        veredicto = {
            "repo": "https://github.com/dcpracmatic-prog/"
                    "Google-Q-cvcc.git",
            "n_semillas": len(semillas),
            "llm": "Qwen2.5-Coder-1.5B-Instruct Q4_K_M, temp 0.7, "
                   "local en Kaggle, sin Gemini/Groq",
            "llm_calls": llm_calls,
            "llm_fallbacks": llm_fallbacks,
            "mejor_semilla": mejor,
            "primera_semilla_S": semillas[0]["S"],
            "mejora_interna_ratio": semillas[0]["S"] / mejor["S"],
            "semillas": semillas,
        }
        (out / "VEREDICTO.json").write_text(
            json.dumps(veredicto, indent=2, default=str))
    return result


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m auto_mvp.autonomous --model <gguf> ..."""
    import argparse

    ap = argparse.ArgumentParser(
        description="Generación autónoma de semillas de circuitos "
                    "desde el repo (Qwen2.5-Coder local).")
    ap.add_argument("--model", type=str, default=None,
                    help="GGUF Q4_K_M ya descargado (si no se da, "
                         "corre sin modelo, con knobs por defecto)")
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--m", type=int, default=255)
    ap.add_argument("--n-semillas", type=int, default=12)
    ap.add_argument("--time-budget-s", type=float, default=1200)
    ap.add_argument("--output-dir", type=str, default=".")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-verify", action="store_true")
    args = ap.parse_args(argv)
    llm = LocalLLM(model_path=args.model) if args.model else None
    res = run_autonomous(
        llm, n=args.n, m=args.m, n_semillas=args.n_semillas,
        time_budget_seconds=args.time_budget_s,
        output_dir=args.output_dir, seed=args.seed,
        verify=not args.no_verify)
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

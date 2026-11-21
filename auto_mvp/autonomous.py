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
5. `run_tres_tareas` (v2.17.5): las 3 tareas de generación, cada
   una ~1 hora o 25 circuitos DIFERENTES (lo que llegue primero),
   con penalización de no repetición global (el `seen` se
   comparte): (1) knobs (batch/nslot/toom3), (2) código del repo
   (el LLM escribe `novel_seed(n, m)` usando las estructuras .py
   del repo mismo: build_hybrid_bm, toom3, dqi_S), (3) param nueva
   (`novel_nslot(n)` en bucle, cada una con un nslot distinto).
   Guarda `tres_tareas.json` + `semillas.json` + `VEREDICTO.json`.

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
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from .llm import LLMError
from .module_loading import load_module_from_path

# NOTA (v2.17.1, bug que tumbó el Notebook v2 en Kaggle): este módulo
# NO importa `build_hybrid_bm` ni `llm_auto_dqi` al cargarse, porque
# esos módulos crean `km.GF2Field(...)` al importarse y fallan si
# kickmix todavía es el paquete VACÍO de Kaggle (sin Circuit). Por
# eso `run_autonomous` los importa perezoso, DESPUÉS de que
# `setup_kaggle()` deja kickmix con Circuit. Importar este módulo
# (para `setup_kaggle`, `LocalLLM`, las constantes) es seguro sin
# kickmix; generar circuitos no (eso lo hace `run_autonomous`).

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
# AUDITORÍA v2.17.6: antes era (4, 8, 17, 36) y el LLM solo podía
# proponer esos batch. A n=10, m=15 el mejor batch ES 4 (la base),
# así que NUNCA había mejora. Medido: batch=1 da S=3.9983e10
# (9.5% mejor que la base 4.418e10) porque Q baja de 1139 a 1067
# y Q^2 domina S = R*Q^2*T. Se añaden 1, 2, 3.
# v2.17.9: el scan usa siempre inversos directos (Montgomery
# desactivado por fase), así que `batch` YA NO cambia Q/T/S: todos
# los batch dan Q=1067, T=29481, S=3.9983e10 a n=10 (el mejor
# anterior). El knob se conserva por compatibilidad.
# v2.17.16: T 29481 -> 33051, S 3.9983e10 -> 4.4825e10 (el arreglo
# limpia hist_mult e is_zero de forma unitaria antes de liberarlos).
_DEFAULT_BATCH = (1, 2, 3, 4, 8, 17, 36)
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


def setup_kaggle(input_dir: str | Path = "/kaggle/input") -> Path | None:
    """Deja `kickmix` con Circuit en Kaggle (la parte Kaggle del repo).

    Encuentra la competencia en /kaggle/input (los montajes vienen
    ANIDADOS) y, si `import kickmix` trae un paquete VACÍO sin
    Circuit, carga el kickmix.so del dataset (o pip force-reinstall
    kickmix==1.0.0). Devuelve el directorio de la competencia (o
    None si no se encontró: generar semillas no lo necesita, solo
    kickmix; solo se falla si kickmix sigue sin Circuit tras todos
    los intentos). Desde v2.17.10 el cheque también exige GF2Field,
    porque los generadores del repo lo crean al importarse.
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

    def _km_ok() -> bool:
        # v2.17.10: el repo también necesita GF2Field (build_hybrid_bm y
        # toom3 lo crean al importarse). Un kickmix con Circuit y Simulator
        # pero sin GF2Field pasaba este cheque y luego la suite fallaba en
        # la recolección (Kaggle v6: AttributeError en test_hybrid_bm y
        # test_llm_dqi, 0 pruebas corrieron).
        try:
            import kickmix as _km
            return (
                hasattr(_km, "Circuit")
                and hasattr(_km, "Simulator")
                and hasattr(_km, "GF2Field")
            )
        except Exception:
            return False

    if not _km_ok() and comp is not None:
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


# Estructuras .py del repo que el LLM puede usar para proponer una
# semilla nueva (tarea código-repo, v2.17.5). Se le dan en el prompt
# para que su función novel_seed(n, m) las importe y las use.
_REPO_ESTRUCTURAS = (
    "- auto_mvp.circuits.generators.build_hybrid_bm:\n"
    "  build_hybrid_bm_circuit(n=70, degree=12, m=4095, batch=17,\n"
    "  nslot=None, toom3=False) -> (circ, info): construye el\n"
    "  circuito híbrido (medición + descomputación clásica).\n"
    "  verify_small(n=10, m=15, batch=4, seed=12345, nshots=8,\n"
    "  toom3=False): verifica sigma, registros y fase DQI por shot.\n"
    "- auto_mvp.circuits.generators.toom3: FIELD12 = km.GF2Field(12),\n"
    "  FIELD4 = km.GF2Field(4), gf4_mul(a, b), gf4_pow(a, e),\n"
    "  gf4_inv(a), to_tower(v), from_tower(c), split_tower(c).\n"
    "- auto_mvp.llm_auto_dqi: R_DQI = 1.1912605,\n"
    "  dqi_S(qubits, toffoli_like) -> float (S = R * Q^2 * T).\n"
    "- auto_mvp.autonomous: _DEFAULT_BATCH = (1, 2, 3, 4, 8, 17, 36)."
)


class _NoRepetir:
    """Penalización de no repetición de semillas (v2.17.5, pedido de
    Arturo; la v4 en Kaggle repitió la mejor semilla: la #13 era
    idéntica a la #1, batch=4, nslot=16, toom3=True).

    Una semilla se identifica por sus knobs (batch, nslot, toom3)
    y, para las de código, por el hash del código. Si el LLM propone
    una ya probada, es REPETIDA: se cuenta la penalización y NO se
    mide (no se gasta tiempo en un circuito que ya se conoce).
    El `seen` es global a toda la corrida (las 3 tareas comparten
    el mismo: lo probado en una tarea no se repite en otra).
    """

    def __init__(self) -> None:
        self.knobs: set[tuple[int, int, bool]] = set()
        self.codigos: set[str] = set()
        self.nslots: set[int] = set()
        self.repetidas = 0

    def knob_repetido(self, batch: int, nslot: int, toom3: bool) -> bool:
        return (int(batch), int(nslot), bool(toom3)) in self.knobs

    def registrar_knob(self, batch: int, nslot: int,
                       toom3: bool) -> None:
        self.knobs.add((int(batch), int(nslot), bool(toom3)))

    def codigo_repetido(self, code: str) -> bool:
        h = hashlib.sha256(code.strip().encode("utf-8")).hexdigest()
        return h in self.codigos

    def registrar_codigo(self, code: str) -> None:
        h = hashlib.sha256(code.strip().encode("utf-8")).hexdigest()
        self.codigos.add(h)

    def nslot_repetido(self, nslot: int) -> bool:
        return int(nslot) in self.nslots

    def registrar_nslot(self, nslot: int) -> None:
        self.nslots.add(int(nslot))

    def resumen(self) -> dict[str, Any]:
        return {"knobs_probados": len(self.knobs),
                "codigos_probados": len(self.codigos),
                "nslots_probados": len(self.nslots),
                "repetidas_penalizadas": self.repetidas}


def _prompt_autonomous(best: dict[str, Any],
                       history: list[dict[str, Any]],
                       n: int, m: int, r_dqi: float,
                       ya_probados: list[tuple[int, int, bool]]
                       | None = None) -> str:
    """El prompt del estratega autónomo: propone UNA parametrización.

    Sin meta externa ni puntuación máxima: solo tratar de hacerlo
    mejor que la mejor semilla hasta ahora. Con penalización de no
    repetición (v2.17.5): se le dan los knobs ya probados para que
    NO los repita.
    """
    hist = "\n".join(
        f"- semilla {h.get('semilla')}: batch={h.get('batch')}, "
        f"nslot={h.get('nslot')}, toom3={h.get('toom3')}: "
        f"{'S=' + str(h.get('S')) if h.get('valid') else 'inválida'}"
        for h in history[-8:])
    probados = ""
    if ya_probados:
        lista = ", ".join(
            f"(batch={b}, nslot={s}, toom3={str(t).lower()})"
            for b, s, t in ya_probados[-12:])
        probados = (
            "\n\nYA PROBADOS (NO los repitas: repetir una semilla "
            "cuesta una penalización y no se mide):\n" + lista + "\n")
    return (
        "Eres el estratega de un generador autónomo de circuitos "
        "cuánticos (decodificador DQI híbrido). Responde SOLO con un "
        "JSON, sin texto fuera del JSON.\n\n"
        f"Tarea: generar la siguiente semilla (n={n}, m={m}). El "
        f"puntaje S es menor-mejor (S = R * Q^2 * T, R={r_dqi}). La "
        "mejor semilla hasta ahora es:\n"
        f"{json.dumps(best, ensure_ascii=False)}\n\n"
        "Lo ya generado:\n"
        f"{hist or '- nada todavía'}"
        f"{probados}\n"
        "Propón UNA parametrización DISTINTA a todas las ya probadas "
        "como JSON: "
        '{"batch": 1..64, "nslot": <entero>, "toom3": true|false, '
        '"seed": <entero>, "reason": "<una frase>"}. '
        f"nslot debe ser >= {n // 2 + 1} (si no, el circuito no cabe). "
        "Pista medida: S = R*Q^2*T y Q^2 domina; a escala chica "
        "un batch PEQUEÑO (1, 2, 3) baja Q y baja S aunque T suba "
        "un poco; nslot mínimo suele ser lo mejor. "
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


def _prompt_codigo_repo(n: int, m: int, r_dqi: float,
                        ya_probados: list[tuple[int, int, bool]]
                        | None = None) -> str:
    """El prompt de la tarea código-repo (v2.17.5): el LLM escribe
    UNA función `novel_seed(n, m)` que USA las estructuras .py del
    repositorio mismo (no solo una fórmula). Devuelve los knobs
    (batch, nslot, toom3) calculados por ese código.
    """
    probados = ""
    if ya_probados:
        lista = ", ".join(
            f"(batch={b}, nslot={s}, toom3={str(t).lower()})"
            for b, s, t in ya_probados[-12:])
        probados = (
            "\n\nYA PROBADOS (los knobs que devuelvas deben ser "
            "DISTINTOS a todos estos; repetir cuesta una "
            "penalización y no se mide):\n" + lista + "\n")
    return (
        "Escribe UNA función Python llamada novel_seed(n, m) que "
        "devuelva los knobs de una semilla nueva de un decodificador "
        "DQI híbrido (n registros, m síndromes).\n\n"
        "USA las estructuras de código .py del repositorio mismo "
        "(impórtalas y úsalas para calcular los knobs, no solo una "
        "fórmula a mano):\n"
        f"{_REPO_ESTRUCTURAS}\n"
        "Reglas:\n"
        "- Solo puedes importar math, typing, dataclasses, auto_mvp, "
        "kickmix. NO uses os, sys, subprocess, eval, exec, open, "
        "getattr.\n"
        "- La función recibe n y m (enteros) y devuelve un dict con "
        "las llaves 'batch' (1..64), 'nslot' (entero) y 'toom3' "
        "(true|false). nslot debe ser >= n//2+1. Usa True/False de "
        "Python (no true/false de JSON).\n"
        "- El puntaje S es menor-mejor (S = R * Q^2 * T, "
        f"R={r_dqi}). No hay meta externa ni puntuación máxima: solo "
        "trata de hacerlo mejor que la mejor semilla hasta ahora.\n"
        "- Escribe SOLO la función, completa y funcional, sin "
        "comentarios de relleno ni '...' ni 'pass'."
        f"{probados}\n"
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


def _default_delta_no_repetido(round_no: int, min_nslot: int,
                               seed: int,
                               tracker: _NoRepetir) -> dict[str, Any]:
    """Knobs por defecto que NO repiten ninguno ya probado: rota
    por los defaults y, si todos están usados, varía nslot."""
    for k in range(int(round_no), int(round_no) + 60):
        d = _default_delta(k, min_nslot, seed)
        if not tracker.knob_repetido(d["batch"], d["nslot"],
                                     d["toom3"]):
            return d
    # Todos los defaults están usados: nslot nuevo, batch rotando.
    base = _default_delta(round_no, min_nslot, seed)
    extra = 1
    while True:
        ns = int(min_nslot) + extra
        if not tracker.knob_repetido(base["batch"], ns,
                                     base["toom3"]):
            out = dict(base)
            out["nslot"] = ns
            out["reason"] = "sin modelo: nslot nuevo (defaults agotados)"
            return out
        extra += 1


def run_autonomous(llm: Any | None, n: int = 30, m: int = 255,
                   n_semillas: int = 12,
                   time_budget_seconds: float | None = 1200,
                   output_dir: str | Path | None = None,
                   seed: int = 42, verify: bool = True,
                   on_seed: Callable[[dict[str, Any]], None] | None = None,
                   tracker: _NoRepetir | None = None,
                   con_param_nueva: bool = True
                   ) -> dict[str, Any]:
    """Generación AUTÓNOMA de semillas de circuitos (desde el repo).

    `llm` es el modelo local (LocalLLM) o un cliente con
    `complete_json(prompt)` y `complete_code(prompt)`; si es None,
    se generan las semillas con los knobs por defecto (la corrida
    nunca depende del modelo). No hay base, no hay baseline, no hay
    puntuación máxima: la primera semilla se genera y se mide, y
    cada semilla nueva solo trata de hacerlo mejor que la mejor
    hasta ahora (mejora interna, autónoma).

    Robustez (v2.17.2, tras el error del Notebook v3 en Kaggle):
    cada semilla se mide dentro de try/except — si una medición
    falla (knobs que el generador rechaza, falta de memoria), se
    registra como inválida y se sigue con la siguiente, en vez de
    tumbar toda la corrida. Y si `output_dir` se da, cada semilla
    se escribe en `progreso.txt` (con flush) al medirse, para ver
    dónde se quedó la corrida si el kernel muere (Kaggle no da el
    mensaje de error).

    Penalización de no repetición (v2.17.5, pedido de Arturo):
    ninguna semilla se repite. Los knobs ya probados se le dan al
    LLM en el prompt y, si aun así propone uno repetido, se cuenta
    la penalización (`repetidas`) y NO se mide (se busca otro).
    El resultado trae `repetidas` y `unicas` (circuitos distintos
    medidos).

    Devuelve {n, m, R, llm_calls, llm_fallbacks, invalid,
    repetidas, unicas, mejor, semillas, param_nueva}. Si
    `output_dir` se da, guarda `semillas.json` (las semillas + sus
    parametrizaciones), `param_nueva.json` y `VEREDICTO.json` ahí.
    """
    if n < 2 or m < 1:
        raise ValueError(f"n={n}, m={m} inválidos")
    min_nslot = (n // 2) + 1
    # Import perezoso (v2.17.1): `llm_auto_dqi` importa
    # `build_hybrid_bm`, que crea `km.GF2Field(...)` al cargarse y
    # falla si kickmix todavía es el paquete VACÍO de Kaggle. Por
    # eso se importa AQUÍ, después de `setup_kaggle()`.
    from .llm_auto_dqi import R_DQI, _measure_knobs, _parse_deltas

    if tracker is None:
        tracker = _NoRepetir()
    # `con_param_nueva=False` lo usa run_tres_tareas (la tarea 3
    # hace la parametrización nueva en bucle, no una sola aquí).

    out_dir = Path(output_dir) if output_dir is not None else None
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)

    def _log_progreso(msg: str) -> None:
        """Progreso a archivo (con flush) + stderr: si el kernel
        muere, el archivo dice dónde se quedó."""
        line = f"[autónomo] {msg}"
        print(line, file=sys.stderr, flush=True)
        if out_dir is not None:
            with open(out_dir / "progreso.txt", "a",
                      encoding="utf-8") as _fh:
                _fh.write(line + "\n")

    def _progress(entry: dict[str, Any]) -> None:
        _log_progreso(json.dumps(entry, ensure_ascii=False, default=str))
        if on_seed is not None:
            on_seed(entry)

    def _medir_seguro(batch: int, nslot: int, toom3: bool,
                      seed_i: int) -> dict[str, Any] | None:
        """Mide UNA semilla; si la medición falla, devuelve None
        (se registra y se sigue, no se tumba la corrida)."""
        try:
            return _measure_knobs(n, m, int(batch), int(nslot),
                                  bool(toom3), verify=verify)
        except Exception as exc:
            _log_progreso(
                f"semilla {seed_i} (batch={batch}, nslot={nslot}, "
                f"toom3={toom3}): MEDICIÓN FALLÓ: "
                f"{type(exc).__name__}: {str(exc)[:200]}")
            return None

    started = time.monotonic()
    semillas: list[dict[str, Any]] = []
    llm_calls = 0
    llm_fallbacks = 0
    invalid = 0

    # Semilla 0: la primera, generada (sin base: es la primera
    # semilla, no una referencia).
    primera = _medir_seguro(4, min_nslot, False, 0)
    if primera is None or not primera["valid"]:
        raise RuntimeError(
            "la primera semilla no se pudo medir o no es válida: "
            f"{(primera or {}).get('reason', '')}")
    tracker.registrar_knob(4, min_nslot, False)
    primera.update({"semilla": 0,
                    "origen": "primera generada (sin base)",
                    "mejora": False})
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
                _prompt_autonomous(mejor, semillas, n, m, R_DQI,
                                   ya_probados=sorted(tracker.knobs)),
                max_tokens=512)
            delta = _parse_deltas(raw, min_nslot)[0]
            llm_ok = True
            llm_calls += 1
        except (LLMError, ValueError, KeyError, TypeError) as exc:
            llm_error = str(exc)[:200]
            delta = _default_delta_no_repetido(i, min_nslot, seed,
                                               tracker)
            llm_fallbacks += 1
        # Penalización de no repetición (v2.17.5): si el LLM propone
        # knobs ya probados, se cuenta y NO se mide; se busca otro.
        if tracker.knob_repetido(delta["batch"], delta["nslot"],
                                 delta["toom3"]):
            tracker.repetidas += 1
            _log_progreso(
                f"semilla {i}: REPETIDA "
                f"(batch={delta['batch']}, nslot={delta['nslot']}, "
                f"toom3={delta['toom3']}): penalización, no se mide")
            delta = _default_delta_no_repetido(i, min_nslot, seed,
                                               tracker)
        tracker.registrar_knob(delta["batch"], delta["nslot"],
                               delta["toom3"])
        entry = _medir_seguro(delta["batch"], delta["nslot"],
                              delta["toom3"], i)
        if entry is None:
            invalid += 1
            semillas.append({"semilla": int(i),
                             "batch": int(delta["batch"]),
                             "nslot": int(delta["nslot"]),
                             "toom3": bool(delta["toom3"]),
                             "valid": False,
                             "origen": "LLM local" if llm_ok else "por defecto",
                             "reason_llm": delta.get("reason", ""),
                             "mejora": False,
                             "note": "MEDICIÓN FALLÓ: no cuenta"})
            continue
        entry.update({"semilla": int(i),
                      "origen": "LLM local" if llm_ok else "por defecto",
                      "reason_llm": delta.get("reason", "")})
        if llm_error:
            entry["llm_error"] = llm_error
        if not entry["valid"]:
            invalid += 1
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
    if con_param_nueva:
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
                mod = load_module_from_path("novel_nslot", tmp)
                ns = mod.novel_nslot(n)
                if not isinstance(ns, int) or ns < min_nslot:
                    raise ValueError(
                        f"novel_nslot devolvió {ns!r}, inválido "
                        f"(< {min_nslot} o no entero)")
                # Penalización de no repetición (v2.17.5): si el nslot
                # ya se probó, no se mide (es repetido, no un fallo).
                if tracker.nslot_repetido(ns):
                    tracker.repetidas += 1
                    param_nueva.update(
                        {"status": "repetido",
                         "nslot": int(ns),
                         "error": "nslot ya probado: penalización, "
                                  "no se mide"})
                    _log_progreso(
                        f"parametrización nueva: nslot={ns} REPETIDO")
                else:
                    tracker.registrar_nslot(ns)
                    # La semilla es (mejor batch, ns, mejor toom3):
                    # se registra el knob completo (si ya se probó,
                    # es repetida aunque el nslot sea nuevo).
                    if tracker.knob_repetido(mejor["batch"], int(ns),
                                             mejor["toom3"]):
                        tracker.repetidas += 1
                        param_nueva.update(
                            {"status": "repetido",
                             "nslot": int(ns),
                             "error": "knobs ya probados: penalización"})
                        _log_progreso(
                            "parametrización nueva: knobs REPETIDOS")
                    else:
                        tracker.registrar_knob(mejor["batch"], int(ns),
                                               mejor["toom3"])
                        entry = _medir_seguro(mejor["batch"], int(ns),
                                              mejor["toom3"],
                                              len(semillas))
                        if entry is None:
                            param_nueva.update(
                                {"status": "falló",
                                 "error": "la medición de la semilla "
                                          "con novel_nslot falló"})
                            _log_progreso(
                                "parametrización nueva: medición falló")
                        else:
                            entry.update(
                                {"semilla": len(semillas),
                                 "origen": "parametrización nueva "
                                           "(novel_nslot)",
                                 "mejora": bool(entry["valid"]
                                                and entry["S"] < best_S)})
                            if entry["mejora"]:
                                best_S = float(entry["S"])
                                mejor = dict(entry)
                            semillas.append(entry)
                            param_nueva.update(
                                {"status": "medido", "nslot": int(ns),
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
        "invalid": invalid,
        "repetidas": tracker.repetidas,
        "unicas": len(tracker.knobs),
        "mejor": mejor, "semillas": semillas,
        "param_nueva": param_nueva,
    }
    if out_dir is not None:
        (out_dir / "semillas.json").write_text(
            json.dumps(result, indent=2, default=str))
        (out_dir / "param_nueva.json").write_text(
            json.dumps(param_nueva, indent=2, default=str))
        veredicto = {
            "repo": "https://github.com/dcpracmatic-prog/"
                    "Google-Q-cvcc.git",
            "n_semillas": len(semillas),
            "llm": "Qwen Code 1.5 (Qwen2.5-Coder-1.5B-Instruct Q4_K_M), temp 0.7, "
                   "local en Kaggle, sin Gemini/Groq",
            "llm_calls": llm_calls,
            "llm_fallbacks": llm_fallbacks,
            "invalid": invalid,
            "repetidas": tracker.repetidas,
            "unicas": len(tracker.knobs),
            "mejor_semilla": mejor,
            "primera_semilla_S": semillas[0]["S"],
            "mejora_interna_ratio": semillas[0]["S"] / mejor["S"],
            "semillas": semillas,
        }
        (out_dir / "VEREDICTO.json").write_text(
            json.dumps(veredicto, indent=2, default=str))
    return result


def run_tres_tareas(llm: Any | None, n: int = 30, m: int = 255,
                    n_objetivo: int = 25,
                    time_budget_seconds: float | None = 3600,
                    output_dir: str | Path | None = None,
                    seed: int = 42, verify: bool = True,
                    on_seed: Callable[[dict[str, Any]], None] | None = None
                    ) -> dict[str, Any]:
    """Las 3 tareas de generación autónoma (v2.17.5, pedido de
    Arturo): cada tarea corre ~1 hora o 25 circuitos DIFERENTES
    (lo que llegue primero), con penalización de no repetición
    global (el `seen` se comparte: lo probado en una tarea no se
    repite en otra).

    - Tarea 1 "knobs": el LLM propone (batch, nslot, toom3)
      (run_autonomous, sin la param nueva suelta).
    - Tarea 2 "codigo_repo": el LLM escribe `novel_seed(n, m)` que
      USA las estructuras .py del repo mismo (build_hybrid_bm,
      toom3, dqi_S) para calcular los knobs.
    - Tarea 3 "param_nueva": el LLM escribe `novel_nslot(n)` en
      bucle, cada una con un nslot distinto.

    Sin modelo, las 3 usan knobs por defecto (la corrida nunca
    depende del modelo). Devuelve {n, m, R, tareas: {knobs,
    codigo_repo, param_nueva}, mejor, semillas, repetidas,
    unicas}. Guarda `tres_tareas.json` en output_dir.
    """
    if n < 2 or m < 1:
        raise ValueError(f"n={n}, m={m} inválidos")
    min_nslot = (n // 2) + 1
    from .llm_auto_dqi import R_DQI, _measure_knobs, _parse_deltas

    tracker = _NoRepetir()
    out_dir = Path(output_dir) if output_dir is not None else None
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
    started_all = time.monotonic()
    semillas: list[dict[str, Any]] = []
    llm_calls = 0
    llm_fallbacks = 0
    invalid = 0

    def _log(msg: str) -> None:
        line = f"[3 tareas] {msg}"
        print(line, file=sys.stderr, flush=True)
        if out_dir is not None:
            with open(out_dir / "progreso.txt", "a",
                      encoding="utf-8") as _fh:
                _fh.write(line + "\n")

    def _progress(entry: dict[str, Any]) -> None:
        _log(json.dumps(entry, ensure_ascii=False, default=str))
        if on_seed is not None:
            on_seed(entry)

    def _medir(batch: int, nslot: int, toom3: bool,
               seed_i: int) -> dict[str, Any] | None:
        try:
            return _measure_knobs(n, m, int(batch), int(nslot),
                                  bool(toom3), verify=verify)
        except Exception as exc:
            _log(f"semilla {seed_i} (batch={batch}, nslot={nslot}, "
                 f"toom3={toom3}): MEDICIÓN FALLÓ: "
                 f"{type(exc).__name__}: {str(exc)[:200]}")
            return None

    def _anotar(entry: dict[str, Any], mejor: dict[str, Any],
                best_S: float) -> tuple[dict[str, Any], float, bool]:
        """Anota una semilla medida: actualiza mejor si baja el S.
        Devuelve (mejor, best_S, es_mejora)."""
        if not entry["valid"]:
            entry["mejora"] = False
            entry["note"] = "INVÁLIDA: no cuenta"
            return mejor, best_S, False
        if entry["S"] < best_S:
            entry["mejora"] = True
            entry["note"] = "MEJORA: nueva mejor semilla"
            return dict(entry), float(entry["S"]), True
        entry["mejora"] = False
        entry["note"] = "válida pero no mejora"
        return mejor, best_S, False

    # --- Tarea 1: knobs (run_autonomous, sin param nueva suelta).
    _log("tarea 1/3 (knobs): el LLM propone batch/nslot/toom3")
    res1 = run_autonomous(
        llm, n=n, m=m, n_semillas=int(n_objetivo),
        time_budget_seconds=time_budget_seconds,
        output_dir=(out_dir / "tarea1_knobs") if out_dir else None,
        seed=seed, verify=verify, on_seed=on_seed, tracker=tracker,
        con_param_nueva=False)
    semillas.extend(res1["semillas"])
    llm_calls += res1["llm_calls"]
    llm_fallbacks += res1["llm_fallbacks"]
    invalid += res1["invalid"]
    mejor = dict(res1["mejor"])
    best_S = float(res1["mejor"]["S"])
    _log(f"tarea 1/3 lista: {len(res1['semillas'])} semillas, "
         f"mejor S={best_S:.4e}, repetidas={tracker.repetidas}")

    # --- Tarea 2: código del repo (novel_seed usa estructuras .py).
    _log("tarea 2/3 (codigo_repo): el LLM escribe novel_seed(n, m) "
         "usando las estructuras .py del repo")
    t2: dict[str, Any] = {"tarea": "codigo_repo", "semillas": [],
                          "llm_calls": 0, "fallbacks": 0,
                          "invalid": 0, "repetidas": 0}
    started2 = time.monotonic()
    intentos2 = 0
    while (len(t2["semillas"]) < int(n_objetivo)
           and (time_budget_seconds is None
                or time.monotonic() - started2
                < float(time_budget_seconds))):
        intentos2 += 1
        if intentos2 > int(n_objetivo) * 4 + 10:
            break
        try:
            if llm is None or not hasattr(llm, "complete_code"):
                raise LLMError("sin generador de código", no_key=True)
            code = llm.complete_code(
                _prompt_codigo_repo(n, m, R_DQI,
                                    ya_probados=sorted(tracker.knobs)),
                max_tokens=1024)
            t2["llm_calls"] += 1
            llm_calls += 1
        except Exception as exc:
            t2["fallbacks"] += 1
            llm_fallbacks += 1
            _log(f"tarea 2: el LLM no dio código ({str(exc)[:120]}); "
                 "se sigue con knobs por defecto")
            d = _default_delta_no_repetido(intentos2, min_nslot,
                                           seed, tracker)
            tracker.registrar_knob(d["batch"], d["nslot"], d["toom3"])
            entry = _medir(d["batch"], d["nslot"], d["toom3"],
                           len(semillas))
            if entry is None:
                invalid += 1
                t2["invalid"] += 1
                continue
            entry.update({"semilla": len(semillas),
                          "origen": "codigo_repo (por defecto)",
                          "reason_llm": d.get("reason", "")})
            mejor, best_S, _ = _anotar(entry, mejor, best_S)
            semillas.append(entry)
            t2["semillas"].append(entry)
            _progress(entry)
            continue
        ok, reason = validate_code(code, entry="novel_seed")
        if not ok:
            t2["fallbacks"] += 1
            _log(f"tarea 2: código rechazado por la guarda: {reason}")
            continue
        if tracker.codigo_repetido(code):
            tracker.repetidas += 1
            t2["repetidas"] += 1
            _log("tarea 2: código REPETIDO: penalización, no se mide")
            continue
        tracker.registrar_codigo(code)
        try:
            tmp = (out_dir / "novel_seed.py") if out_dir else Path(
                "novel_seed.py")
            tmp.write_text(code, encoding="utf-8")
            mod = load_module_from_path("novel_seed", tmp)
            knobs = mod.novel_seed(n, m)
            if not isinstance(knobs, dict):
                raise ValueError("novel_seed no devolvió un dict")
            b = int(knobs.get("batch", 4))
            s = int(knobs.get("nslot", min_nslot))
            t = bool(knobs.get("toom3", False))
            # batch 1..64 (se limita al rango válido, sin forzar
            # un valor discreto: antes se redondeaba al más cercano
            # de (4, 8, 17, 36) y nunca se probaba batch 1, 2, 3).
            b = max(1, min(64, b))
            s = max(s, min_nslot)
        except Exception as exc:
            t2["fallbacks"] += 1
            _log(f"tarea 2: novel_seed no se pudo ejecutar: "
                 f"{str(exc)[:150]}")
            continue
        if tracker.knob_repetido(b, s, t):
            tracker.repetidas += 1
            t2["repetidas"] += 1
            _log(f"tarea 2: knobs REPETIDOS (batch={b}, nslot={s}, "
                 f"toom3={t}): penalización, no se mide")
            continue
        tracker.registrar_knob(b, s, t)
        entry = _medir(b, s, t, len(semillas))
        if entry is None:
            invalid += 1
            t2["invalid"] += 1
            continue
        entry.update({"semilla": len(semillas),
                      "origen": "codigo_repo (novel_seed)",
                      "codigo": code[:400]})
        mejor, best_S, _ = _anotar(entry, mejor, best_S)
        semillas.append(entry)
        t2["semillas"].append(entry)
        _progress(entry)
    _log(f"tarea 2/3 lista: {len(t2['semillas'])} semillas nuevas, "
         f"mejor S={best_S:.4e}, repetidas={tracker.repetidas}")

    # --- Tarea 3: parametrización nueva en bucle (novel_nslot).
    _log("tarea 3/3 (param_nueva): el LLM escribe novel_nslot(n) "
         "en bucle, cada una con un nslot distinto")
    t3: dict[str, Any] = {"tarea": "param_nueva", "semillas": [],
                          "llm_calls": 0, "fallbacks": 0,
                          "invalid": 0, "repetidas": 0}
    started3 = time.monotonic()
    intentos3 = 0
    while (len(t3["semillas"]) < int(n_objetivo)
           and (time_budget_seconds is None
                or time.monotonic() - started3
                < float(time_budget_seconds))):
        intentos3 += 1
        if intentos3 > int(n_objetivo) * 4 + 10:
            break
        try:
            if llm is None or not hasattr(llm, "complete_code"):
                raise LLMError("sin generador de código", no_key=True)
            code = llm.complete_code(_prompt_novel_nslot(n),
                                     max_tokens=512)
            t3["llm_calls"] += 1
            llm_calls += 1
        except Exception as exc:
            t3["fallbacks"] += 1
            llm_fallbacks += 1
            _log(f"tarea 3: el LLM no dio código ({str(exc)[:120]}); "
                 "se sigue con nslot por defecto")
            ns = min_nslot + len(t3["semillas"])
            if tracker.nslot_repetido(ns):
                continue
            if tracker.knob_repetido(mejor["batch"], ns,
                                     mejor["toom3"]):
                tracker.repetidas += 1
                t3["repetidas"] += 1
                continue
            tracker.registrar_nslot(ns)
            tracker.registrar_knob(mejor["batch"], ns, mejor["toom3"])
            entry = _medir(mejor["batch"], ns, mejor["toom3"],
                           len(semillas))
            if entry is None:
                invalid += 1
                t3["invalid"] += 1
                continue
            entry.update({"semilla": len(semillas),
                          "origen": "param_nueva (por defecto)"})
            mejor, best_S, _ = _anotar(entry, mejor, best_S)
            semillas.append(entry)
            t3["semillas"].append(entry)
            _progress(entry)
            continue
        ok, reason = validate_code(code, entry="novel_nslot")
        if not ok:
            t3["fallbacks"] += 1
            _log(f"tarea 3: código rechazado por la guarda: {reason}")
            continue
        if tracker.codigo_repetido(code):
            tracker.repetidas += 1
            t3["repetidas"] += 1
            _log("tarea 3: código REPETIDO: penalización, no se mide")
            continue
        tracker.registrar_codigo(code)
        try:
            tmp = (out_dir / "novel_nslot.py") if out_dir else Path(
                "novel_nslot.py")
            tmp.write_text(code, encoding="utf-8")
            mod = load_module_from_path("novel_nslot", tmp)
            ns = mod.novel_nslot(n)
            if not isinstance(ns, int) or ns < min_nslot:
                raise ValueError(f"novel_nslot devolvió {ns!r}")
        except Exception as exc:
            t3["fallbacks"] += 1
            _log(f"tarea 3: novel_nslot no se pudo ejecutar: "
                 f"{str(exc)[:150]}")
            continue
        if tracker.nslot_repetido(ns):
            tracker.repetidas += 1
            t3["repetidas"] += 1
            _log(f"tarea 3: nslot={ns} REPETIDO: penalización")
            continue
        if tracker.knob_repetido(mejor["batch"], ns, mejor["toom3"]):
            tracker.repetidas += 1
            t3["repetidas"] += 1
            _log("tarea 3: knobs REPETIDOS: penalización")
            continue
        tracker.registrar_nslot(ns)
        tracker.registrar_knob(mejor["batch"], ns, mejor["toom3"])
        entry = _medir(mejor["batch"], ns, mejor["toom3"],
                       len(semillas))
        if entry is None:
            invalid += 1
            t3["invalid"] += 1
            continue
        entry.update({"semilla": len(semillas),
                      "origen": "param_nueva (novel_nslot)",
                      "codigo": code[:400]})
        mejor, best_S, _ = _anotar(entry, mejor, best_S)
        semillas.append(entry)
        t3["semillas"].append(entry)
        _progress(entry)
    _log(f"tarea 3/3 lista: {len(t3['semillas'])} semillas nuevas, "
         f"mejor S={best_S:.4e}, repetidas={tracker.repetidas}")

    result: dict[str, Any] = {
        "n": int(n), "m": int(m), "R": R_DQI,
        "n_objetivo_por_tarea": int(n_objetivo),
        "time_budget_por_tarea_s": time_budget_seconds,
        "llm_calls": llm_calls, "llm_fallbacks": llm_fallbacks,
        "invalid": invalid,
        "repetidas": tracker.repetidas,
        "unicas": len(tracker.knobs),
        "mejor": mejor, "semillas": semillas,
        "tareas": {"knobs": res1, "codigo_repo": t2,
                   "param_nueva": t3},
        "tiempo_total_s": round(time.monotonic() - started_all, 1),
    }
    if out_dir is not None:
        (out_dir / "tres_tareas.json").write_text(
            json.dumps(result, indent=2, default=str))
        (out_dir / "semillas.json").write_text(
            json.dumps(result, indent=2, default=str))
        veredicto = {
            "repo": "https://github.com/dcpracmatic-prog/"
                    "Google-Q-cvcc.git",
            "n_semillas": len(semillas),
            "llm": "Qwen Code 1.5 (Qwen2.5-Coder-1.5B-Instruct Q4_K_M), temp 0.7, "
                   "local en Kaggle, sin Gemini/Groq",
            "llm_calls": llm_calls,
            "llm_fallbacks": llm_fallbacks,
            "invalid": invalid,
            "repetidas": tracker.repetidas,
            "unicas": len(tracker.knobs),
            "mejor_semilla": mejor,
            "primera_semilla_S": semillas[0]["S"],
            "mejora_interna_ratio": semillas[0]["S"] / mejor["S"],
            "por_tarea": {k: len(v["semillas"])
                          for k, v in result["tareas"].items()},
            "semillas": semillas,
        }
        (out_dir / "VEREDICTO.json").write_text(
            json.dumps(veredicto, indent=2, default=str))
    return result


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m auto_mvp.autonomous --model <gguf> ...
    Con --tres-tareas corre las 3 tareas (knobs, codigo_repo,
    param_nueva), 1 hora o 25 circuitos distintos c/u."""
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
    ap.add_argument("--n-objetivo", type=int, default=25,
                    help="circuitos distintos por tarea "
                         "(solo --tres-tareas)")
    ap.add_argument("--tres-tareas", action="store_true",
                    help="corre las 3 tareas (knobs, codigo_repo, "
                         "param_nueva)")
    ap.add_argument("--time-budget-s", type=float, default=1200)
    ap.add_argument("--output-dir", type=str, default=".")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-verify", action="store_true")
    args = ap.parse_args(argv)
    llm = LocalLLM(model_path=args.model) if args.model else None
    if args.tres_tareas:
        res = run_tres_tareas(
            llm, n=args.n, m=args.m, n_objetivo=args.n_objetivo,
            time_budget_seconds=args.time_budget_s,
            output_dir=args.output_dir, seed=args.seed,
            verify=not args.no_verify)
    else:
        res = run_autonomous(
            llm, n=args.n, m=args.m, n_semillas=args.n_semillas,
            time_budget_seconds=args.time_budget_s,
            output_dir=args.output_dir, seed=args.seed,
            verify=not args.no_verify)
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

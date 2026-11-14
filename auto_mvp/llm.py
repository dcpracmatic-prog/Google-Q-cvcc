"""AUTO_MVP v2.17 — el modelo de lenguaje LOCAL del corredor.

Arturo (2026-11-14): quitar Gemini/Groq (API, llave) y usar el modelo
local Qwen2.5-Coder-1.5B-Instruct (GGUF Q4_K_M, llama-cpp-python,
temperatura 0.7-0.8). El modelo corre EN la máquina (Kaggle o sandbox),
sin llave, sin red, sin API. Por eso el corredor ya no pide nada para
funcionar: el modelo está en la máquina, no en una API.

El modelo es el ESTRATEGA, no el constructor: lee la mejor semilla
(compacta, en JSON) y el historial medido, y propone el siguiente
movimiento como un JSON chico. NUNCA propone compuertas ni circuitos:
las compuertas las ponen los operadores verificados (sa_windows, los
generadores) y la validez la impone el verificador oficial. Así el
modelo no puede inventar un circuito inválido.

El modelo (GGUF ~1.0 GB) NO va en el repo: se baja de HuggingFace
la primera vez que se usa (o se pone en `LLM_MODEL_PATH`). La
descarga verifica el SHA256. En Kaggle, el Notebook lo baja a
`/kaggle/working/`. En sandbox, a `~/workspace/models/`.

Temperatura 0.7 (rango de Arturo: 0.7-0.8): creatividad matemática
para circuitos inéditos fuera del mainstream, sin romper la
estructura de importaciones de Python. Aquí el modelo solo propone
JSON de knobs (nunca código), así que la estructura no está en juego;
la guarda de imports vive en el Notebook que genera código nuevo.
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from pathlib import Path
from typing import Any

# Qwen2.5-Coder-1.5B-Instruct, GGUF Q4_K_M (mismo que el Notebook,
# verificado en Kaggle v5: 3 llamadas, 0 fallbacks).
MODEL_URL = ("https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF"
             "/resolve/main/qwen2.5-coder-1.5b-instruct-q4_k_m.gguf")
MODEL_SHA256 = ("cc324af070c2ecbfd324a30884d2f951a7ff756aba85cb811a6ec436933bb046")
MODEL_FILENAME = "qwen2.5-coder-1.5b-instruct-q4_k_m.gguf"

# Temperatura de Arturo: 0.7-0.8. 0.7 es el valor por defecto.
DEFAULT_TEMPERATURE = 0.7

# GGUF alternativo (Q8_0, más preciso, ~1.6 GB) si Arturo lo pide:
# "https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF/resolve/main/qwen2.5-coder-1.5b-instruct-q8_0.gguf"


class LLMError(RuntimeError):
    """El modelo local no respondió (no instalado, sin archivo, o error).

    `no_model=True` cuando el modelo no está disponible (falta el
    archivo GGUF o llama-cpp-python no está instalado): el corredor
    cae a los knobs por defecto y sigue. `no_key` y `rate_limited`
    se mantienen por compatibilidad con clientes falsos de los tests;
    el modelo local no tiene llave ni límite de API.
    """

    def __init__(self, message: str, *, no_key: bool = False,
                 rate_limited: bool = False, no_model: bool = False):
        super().__init__(message)
        self.no_key = no_key
        self.rate_limited = rate_limited
        self.no_model = no_model


def model_path() -> Path:
    """Dónde está (o se baja) el GGUF.

    Orden: `LLM_MODEL_PATH` > `/kaggle/working/<archivo>` >
    `~/workspace/models/<archivo>` > `./<archivo>`. El primero que
    exista gana; si ninguno existe, se usa el primero de la lista
    para bajarlo.
    """
    env = os.environ.get("LLM_MODEL_PATH", "").strip()
    if env:
        return Path(env).expanduser()
    cands = [
        Path("/kaggle/working") / MODEL_FILENAME,
        Path.home() / "workspace" / "models" / MODEL_FILENAME,
        Path.cwd() / MODEL_FILENAME,
    ]
    for c in cands:
        if c.is_file():
            return c
    return cands[0]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_model(path: Path | None = None) -> Path:
    """Baja el GGUF si no está, y verifica su SHA256.

    Devuelve la ruta del archivo. Levanta LLMError(no_model=True)
    si no se puede bajar o el SHA256 no coincide.
    """
    p = Path(path) if path is not None else model_path()
    if p.is_file():
        if _sha256(p) != MODEL_SHA256:
            raise LLMError(
                f"el GGUF en {p} no es el Q4_K_M esperado (SHA256 "
                "no coincide); bórralo y deja que se baje de nuevo",
                no_model=True)
        return p
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        urllib.request.urlretrieve(MODEL_URL, str(p))
    except Exception as exc:
        raise LLMError(
            f"no se pudo bajar el modelo local de HuggingFace: {exc}",
            no_model=True) from exc
    if _sha256(p) != MODEL_SHA256:
        raise LLMError(
            "el GGUF bajado no coincide con el SHA256 esperado",
            no_model=True)
    return p


_LLM = None


def get_llm():
    """El modelo local cargado (singleton, perezoso).

    Levanta LLMError(no_model=True) si llama-cpp-python no está
    instalado o el GGUF no está (con el mensaje de cómo conseguirlo).
    """
    global _LLM
    if _LLM is not None:
        return _LLM
    try:
        from llama_cpp import Llama
    except ImportError as exc:
        raise LLMError(
            "llama-cpp-python no está instalado: "
            "pip install llama-cpp-python",
            no_model=True) from exc
    p = ensure_model()
    n_threads = int(os.environ.get("LLM_THREADS", "4"))
    _LLM = Llama(model_path=str(p), n_ctx=2048, n_threads=n_threads,
                 verbose=False)
    return _LLM


def complete(prompt: str, *, max_tokens: int = 1024,
             temperature: float = DEFAULT_TEMPERATURE) -> str:
    """Una respuesta de texto del modelo local (Qwen2.5-Coder).

    Devuelve el texto de la primera opción. Levanta LLMError si el
    modelo no está disponible o la respuesta no trae texto. No usa
    red ni llave: todo corre en la máquina.
    """
    llm = get_llm()
    try:
        out = llm.create_chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=float(temperature), max_tokens=int(max_tokens),
            stop=[])
    except Exception as exc:
        raise LLMError(f"el modelo local falló: {exc}") from exc
    try:
        text = out["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(
            "el modelo local devolvió una respuesta sin texto: "
            f"{json.dumps(out)[:300]}") from exc
    if not isinstance(text, str) or not text.strip():
        raise LLMError("el modelo local devolvió texto vacío")
    return text


def complete_json(prompt: str, **kwargs: Any) -> dict[str, Any]:
    """Como complete(), pero la respuesta debe ser un JSON.

    Acepta el JSON aunque venga envuelto en ```json ... ``` o con
    texto alrededor: toma el primer { ... } balanceado. Levanta
    LLMError si no hay un JSON válido.
    """
    text = complete(prompt, **kwargs)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise LLMError(f"el modelo no devolvió un JSON: {text[:300]}")
    try:
        obj = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise LLMError(
            f"el JSON del modelo no se pudo leer: {exc} "
            f"(texto: {text[:300]})") from exc
    if not isinstance(obj, dict):
        raise LLMError(f"el modelo devolvió un JSON que no es un "
                       f"objeto: {text[:300]}")
    return obj

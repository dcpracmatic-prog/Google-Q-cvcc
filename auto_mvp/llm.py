"""AUTO_MVP v2.2 — el modelo de lenguaje gratis del corredor.

Arturo (2026-11-12): meter un modelo de lenguaje GRATIS y BUENO.
El modelo es el ESTRATEGA, no el constructor: lee la mejor semilla
(compacta, en JSON) y el historial medido, y propone el siguiente
movimiento como un JSON chico. NUNCA propone compuertas ni circuitos:
las compuertas las ponen los operadores verificados (sa_windows, los
generadores) y la validez la impone el verificador oficial. Así el
modelo no puede inventar un circuito inválido.

PROVEEDORES GRATIS (medidos contra la documentación pública,
octubre-noviembre 2026; los límites cambian, se vuelven a mirar en
la consola del proveedor antes de depender de ellos):

- **Gemini (por defecto)**: la API de Google AI Studio. Los modelos
  Flash (2.5 Flash, 3.6 Flash, 3.8 Flash, Flash-Lite) y Gemma son
  gratis, sin tarjeta. Es el nivel gratis más generoso por capacidad
  (modelo de un laboratorio frontera, contexto de 1M). Los límites
  exactos los muestra AI Studio por proyecto. La llave es gratis
  (cuenta de Google, sin tarjeta).
- **Groq (respaldo)**: plan gratis, sin tarjeta, endpoint compatible
  con OpenAI, rapidísimo (300-800 tokens/s). `openai/gpt-oss-120b`:
  30 peticiones/min, 1,000/día, 8,000 tokens/min, 200,000 tokens/día.
  (Los Llama pasaron a Enterprise en 2026: ya no están en el nivel
  gratis de autoservicio; el sustituto es gpt-oss-120b.)

La llave NUNCA va en el repo: se lee de variables de entorno
(`GEMINI_API_KEY` / `GROQ_API_KEY` / `LLM_API_KEY`). En Kaggle se
pone como secreto del notebook (Add-ons → Secrets). Sin llave, el
cliente levanta `LLMError(no_key=True)` y el corredor sigue con
sa_windows: la corrida nunca depende del modelo.

Uso de tokens: cada propuesta es un prompt chico (la semilla son
kilobytes, el historial son líneas). Con Groq, 200K tokens/día dan
para ~100 propuestas/día a ~2K tokens cada una; con Gemini el nivel
gratis es más amplio. Si el proveedor responde 429 (límite), el
corredor anota el límite y sigue con sa_windows.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

PROVIDERS: dict[str, dict[str, str]] = {
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.5-flash",
        "key_env": "GEMINI_API_KEY",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "openai/gpt-oss-120b",
        "key_env": "GROQ_API_KEY",
    },
}

DEFAULT_PROVIDER = "gemini"


class LLMError(RuntimeError):
    """El modelo no respondió (sin llave, límite, red, o error)."""

    def __init__(self, message: str, *, no_key: bool = False,
                 rate_limited: bool = False):
        super().__init__(message)
        self.no_key = no_key
        self.rate_limited = rate_limited


def _resolve(provider: str | None, model: str | None,
             api_key: str | None) -> tuple[str, str, str, str]:
    name = (provider or os.environ.get("LLM_PROVIDER")
            or DEFAULT_PROVIDER).strip().lower()
    if name not in PROVIDERS:
        raise LLMError(
            f"proveedor desconocido: {name!r} (usa 'gemini' o 'groq')")
    cfg = PROVIDERS[name]
    model = (model or os.environ.get("LLM_MODEL") or cfg["model"]).strip()
    key = (api_key or os.environ.get(cfg["key_env"])
           or os.environ.get("LLM_API_KEY") or "").strip()
    if not key:
        raise LLMError(
            f"sin llave para {name}: pon {cfg['key_env']} (o LLM_API_KEY) "
            "como variable de entorno; en Kaggle, como secreto del "
            "notebook. Sin llave el corredor sigue con sa_windows.",
            no_key=True)
    return name, cfg["base_url"], model, key


def complete(prompt: str, *, provider: str | None = None,
             model: str | None = None, api_key: str | None = None,
             timeout_s: float = 60.0, max_tokens: int = 1024,
             temperature: float = 0.7) -> str:
    """Una respuesta de texto del modelo (endpoint compatible OpenAI).

    Devuelve el texto de la primera opción. Levanta LLMError si no hay
    llave, si el proveedor limita (429, rate_limited=True) o si la
    respuesta no trae texto.
    """
    name, base_url, model_name, key = _resolve(provider, model, api_key)
    body = json.dumps({
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": int(max_tokens),
        "temperature": float(temperature),
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=float(timeout_s)) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise LLMError(
                f"{name} limitó la llamada (429): se llegó al tope "
                "gratis del día o del minuto; el corredor sigue con "
                "sa_windows", rate_limited=True) from exc
        raise LLMError(
            f"{name} devolvió HTTP {exc.code}: "
            f"{exc.read().decode('utf-8', 'replace')[:300]}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise LLMError(f"no se pudo hablar con {name}: {exc}") from exc
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(
            f"{name} devolvió una respuesta sin texto: "
            f"{json.dumps(data)[:300]}") from exc
    if not isinstance(text, str) or not text.strip():
        raise LLMError(f"{name} devolvió texto vacío")
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

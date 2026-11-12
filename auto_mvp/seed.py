"""AUTO_MVP v2.2 — la SEMILLA: lo único que sale del Notebook.

Arturo (2026-11-12): NO construir .kmx en el Notebook, porque no
cabe: todas las iteraciones + todo el respaldo de las semillas son
gigas (el .kmx de DQI pesa 1.5 GB). Lo que se saca en esta parte son
NADA MÁS LAS SEMILLAS.

Una semilla es la RECETA COMPACTA (un JSON de kilobytes) con la que
se reconstruye el circuito después, fuera del Notebook:

- **invsqrt**: la base (`invsqrt_pub`) + las operaciones de
  sa_windows aplicadas (ventana + reemplazo). El .kmx se reconstruye
  aplicando esas ops a la base vendida en el repo.
- **DQI**: la base (`dqi_v1`) + los parámetros del generador
  (ancho de punteros, familia del multiplicador, b de Montgomery...).
  El circuito se reconstruye corriendo el generador con esos
  parámetros.
- **dfthcsos**: la base (`sample`) + los parámetros de la
  factorización (rank, inicialización, lr, epochs...). La submission
  se reconstruye entrenando con esos parámetros.

El corredor materializa el circuito en un directorio TEMPORAL para
validarlo y medirlo, y lo BORRA al terminar la ronda: en `runs/`
quedan solo las semillas (JSON) y el ledger. Un .kmx nunca sale del
Notebook ni se guarda en `runs/seeds/`.

Formato (todo JSON, todo en simple)::

    {
      "task": "invsqrt",
      "S": 100568.5, "Q": 62, "T": 1325.48,
      "recipe": {"base": "invsqrt_pub", "K": 6, "ops": [...]},
      "parent": null, "notes": "semilla vendida, medida"
    }

El `id` de una semilla es un hash corto de TODO su contenido
(tarea, S, Q, T, receta, padre, notas): si se toca cualquier campo,
el id ya no coincide y la semilla se rechaza.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

TASKS = ("invsqrt", "dqi", "dfthcsos")

# La receta mínima por tarea: qué campos tiene que traer.
RECIPE_KEYS: dict[str, tuple[str, ...]] = {
    "invsqrt": ("base",),
    "dqi": ("base",),
    "dfthcsos": ("base",),
}


def seed_id(seed: dict[str, Any]) -> str:
    """Id corto y determinista de una semilla (hash de TODO su contenido).

    El id cubre tarea, S, Q, T, receta, padre y notas: si se toca
    CUALQUIER campo (por ejemplo, inflar el S medido), el id ya no
    coincide y `validate_seed` la rechaza.
    """
    content = {k: v for k, v in seed.items() if k != "id"}
    blob = json.dumps(content, sort_keys=True,
                      ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:12]


def new_seed(task: str, S: float, Q: int, T: float,
             recipe: dict[str, Any], parent: str | None = None,
             notes: str = "") -> dict[str, Any]:
    """Una semilla nueva (todavía no guardada)."""
    if task not in TASKS:
        raise ValueError(f"tarea desconocida: {task!r} (usa {TASKS})")
    if not isinstance(recipe, dict) or not recipe:
        raise ValueError("la receta es un objeto JSON no vacío")
    for key in RECIPE_KEYS[task]:
        if key not in recipe:
            raise ValueError(
                f"la receta de {task} necesita el campo {key!r}")
    seed = {"task": task, "S": float(S), "Q": int(Q), "T": float(T),
            "recipe": recipe, "parent": parent, "notes": str(notes)}
    seed["id"] = seed_id(seed)
    return seed


def validate_seed(seed: dict[str, Any]) -> None:
    """La semilla trae lo que dice el formato, o no es una semilla."""
    if not isinstance(seed, dict):
        raise ValueError("la semilla es un objeto JSON")
    for key in ("task", "S", "Q", "T", "recipe", "id"):
        if key not in seed:
            raise ValueError(f"a la semilla le falta {key!r}")
    if seed["task"] not in TASKS:
        raise ValueError(f"tarea desconocida: {seed['task']!r}")
    if seed["id"] != seed_id(seed):
        raise ValueError(
            f"el id {seed['id']!r} no es el hash de la receta "
            f"(debería ser {seed_id(seed)!r}): la semilla fue tocada")
    new_seed(seed["task"], seed["S"], seed["Q"], seed["T"],
             seed["recipe"])


def seeds_dir(runs_dir: str | Path, task: str) -> Path:
    return Path(runs_dir) / "seeds" / task


def save_seed(seed: dict[str, Any], runs_dir: str | Path) -> Path:
    """Guarda SOLO la semilla (JSON, kilobytes). Nunca un .kmx."""
    validate_seed(seed)
    d = seeds_dir(runs_dir, seed["task"])
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{seed['id']}.json"
    p.write_text(json.dumps(seed, indent=1, ensure_ascii=False),
                 encoding="utf-8")
    return p


def load_seed(path: str | Path) -> dict[str, Any]:
    seed = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_seed(seed)
    return seed


def list_seeds(runs_dir: str | Path, task: str) -> list[dict[str, Any]]:
    """Todas las semillas guardadas de una tarea, mejor S primero."""
    d = seeds_dir(runs_dir, task)
    out = []
    if d.is_dir():
        for p in sorted(d.glob("*.json")):
            try:
                out.append(load_seed(p))
            except Exception:
                continue
    return sorted(out, key=lambda s: s["S"])

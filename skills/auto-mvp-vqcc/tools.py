"""AUTO_MVP v0.7.0 — funciones para ChatGPT (Code Interpreter) y Grok.

Las 6 operaciones reales del repo como funciones Python planas, para
cargarlas en una sesión de Code Interpreter (ChatGPT) o Grok: sube
este archivo junto con el repo (o instala el paquete) y haz
``from tools import evaluate_candidate, ...``. El esquema de
function calling (OpenAI / Grok) está en functions.json, con los
mismos nombres y parámetros.

Si auto_mvp no está instalado, se añade la raíz del repo (dos
niveles arriba de este archivo) al path, así funciona desde un
git clone sin pip install.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

try:
    import auto_mvp  # noqa: F401
except ImportError:
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from auto_mvp.operations import (apply_morph_tunnel as _apply_morph_tunnel,
                                 check_integrity as _check_integrity,
                                 decode_json_config as _decode_json_config,
                                 evaluate_candidate as _evaluate_candidate,
                                 export_module as _export_module,
                                 promotion_gate as _promotion_gate,
                                 run_orchestrator as _run_orchestrator,
                                 validate_submission as _validate_submission)

__all__ = [
    "evaluate_candidate",
    "apply_morph_tunnel",
    "decode_json_config",
    "run_orchestrator",
    "check_integrity",
    "export_module",
    "validate_submission",
    "promotion_gate",
]


def evaluate_candidate(candidate: dict[str, Any], meta_mvp: float = 30.0,
                       margin: float = 0.10, best_S: float | None = None
                       ) -> dict[str, Any]:
    """Evalúa un candidato VQCC (proxy + puerta): S, GM, si promueve."""
    return _evaluate_candidate(candidate, meta_mvp=meta_mvp, margin=margin,
                               best_S=best_S)


def apply_morph_tunnel(call_graph: dict[str, Any],
                       rules: list[dict[str, Any]] | None = None,
                       method: str = "greedy") -> dict[str, Any]:
    """Tunela un grafo de llamadas (MORPH): T/Q antes y después."""
    return _apply_morph_tunnel(call_graph, rules=rules, method=method)


def decode_json_config(config: dict[str, Any]) -> dict[str, Any]:
    """Decodifica una config JSON con directivas en lenguaje natural."""
    return _decode_json_config(config)


def run_orchestrator(candidates: list[dict[str, Any]],
                     config: dict[str, Any] | None = None,
                     best_S: dict[str, float] | None = None
                     ) -> dict[str, Any]:
    """Corre el orquestador adaptativo sobre candidatos + config."""
    return _run_orchestrator(candidates, config=config, best_S=best_S)


def check_integrity(evidence: dict[str, Any]) -> dict[str, Any]:
    """Filtro de integridad obligatorio sobre una evidencia."""
    return _check_integrity(evidence)


def export_module(record: dict[str, Any],
                  runs_dir: str | None = None) -> dict[str, Any]:
    """Exporta e inyecta un módulo promovido al dataset de trabajo."""
    return _export_module(record, runs_dir=runs_dir)


def validate_submission(path: str,
                        task_statuses: dict[str, str] | None = None,
                        mode: str = "full") -> dict[str, Any]:
    """Valida el formato de un submission.zip (o su directorio)."""
    return _validate_submission(path, task_statuses=task_statuses, mode=mode)


def promotion_gate(meta_mvp: float = 30.0,
                   S: dict[str, float] | None = None) -> dict[str, Any]:
    """La puerta de promoción: lo que exige meta_mvp (y la GM con S)."""
    return _promotion_gate(meta_mvp, S=S)

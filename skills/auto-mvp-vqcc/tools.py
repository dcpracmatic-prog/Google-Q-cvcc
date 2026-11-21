"""AUTO_MVP — funciones para ChatGPT (Code Interpreter) y Grok (desde v0.7.0).

Las 12 operaciones reales del repo como funciones Python planas, para
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
                                 combine_best as _combine_best,
                                 decode_json_config as _decode_json_config,
                                 evaluate_candidate as _evaluate_candidate,
                                 export_module as _export_module,
                                 export_notebook as _export_notebook,
                                 mutate as _mutate,
                                 promotion_gate as _promotion_gate,
                                 run_orchestrator as _run_orchestrator,
                                 run_serial as _run_serial,
                                 run_vqcc_chain as _run_vqcc_chain,
                                 validate_submission as _validate_submission)

__all__ = [
    "evaluate_candidate",
    "apply_morph_tunnel",
    "decode_json_config",
    "run_orchestrator",
    "run_vqcc_chain",
    "check_integrity",
    "export_module",
    "validate_submission",
    "combine_best",
    "promotion_gate",
    "mutate",
    "run_serial",
    "export_notebook",
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


def run_vqcc_chain(config: dict[str, Any] | None = None,
                   candidates: list[dict[str, Any]] | None = None,
                   best_S: dict[str, float] | None = None
                   ) -> dict[str, Any]:
    """La cadena completa en una llamada: directiva JSON -> orquestador
    -> túnel MORPH -> pipeline -> verificador oficial (con veto)."""
    return _run_vqcc_chain(config=config, candidates=candidates,
                           best_S=best_S)


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


def combine_best(target_gm: float = 30.0, runs_dir: str | None = None,
                 export: bool = False) -> dict[str, Any]:
    """La guía: el mejor por tarea, entre corridas, contra el objetivo."""
    return _combine_best(target_gm, runs_dir=runs_dir, export=export)


def promotion_gate(meta_mvp: float = 30.0,
                   S: dict[str, float] | None = None) -> dict[str, Any]:
    """La puerta de promoción: lo que exige meta_mvp (y la GM con S)."""
    return _promotion_gate(meta_mvp, S=S)


def mutate(seed_graph: dict[str, Any], task: str,
           base_metrics: dict[str, Any], n: int = 10, seed: int = 42,
           rules: list[str] | None = None) -> dict[str, Any]:
    """El mutador autónomo: genera candidatos mutando la semilla."""
    return _mutate(seed_graph, task, base_metrics, n=n, seed=seed, rules=rules)


def run_serial(jobs: list[dict[str, Any]], target_gm: float = 30.0,
               runs_dir: str | None = None,
               export_notebook: bool = False) -> dict[str, Any]:
    """La orquestación en serie con compensación global."""
    return _run_serial(jobs, target_gm=target_gm, runs_dir=runs_dir,
                       export_notebook=export_notebook)


def export_notebook(runs_dir: str | None = None,
                    out_path: str | None = None,
                    target_gm: float | None = None) -> dict[str, Any]:
    """Exporta los tres módulos ganadores a un .ipynb ejecutable."""
    return _export_notebook(runs_dir=runs_dir, out_path=out_path,
                            target_gm=target_gm)

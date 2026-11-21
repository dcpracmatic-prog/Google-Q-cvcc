"""AUTO_MVP v1.1.0 — exportar los ganadores a un Notebook ejecutable.

El entregable final del Solucionador Morfológico: cuando la
combinación de los tres mejores componentes cruza la meta global,
el orquestador exporta un .ipynb autocontenido con los tres
módulos ganadores, listos para la compilación pesada (fase 3).

El notebook es nbformat 4 (JSON, solo stdlib):
- Celda 0 (markdown): título, objetivo, GM y si se llegó.
- Una celda de código por tarea (invsqrt, dqi, dfthcsos): incrusta
  el module.py del dataset (estructura + código ejecutable) y lo
  carga con importlib desde un directorio temporal; si el
  componente no tiene módulo en el dataset (ej. el mejor envío
  sembrado), incrusta su component.json como fallback. Cada celda
  deja su módulo en _TASK_MODULES[task] y corre verify().
- Celda final (código): llama a verify() de los tres módulos,
  recomputa la GM con las fórmulas oficiales y la imprime junto
  con el objetivo.

Las celdas son autocontenidas y se ejecutan en orden: cada celda
de tarea define build()/verify() (vía el módulo cargado) y la
final las llama.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .combiner import TASKS, combine
from .vqcc.contracts import REFERENCE_S

NBFORMAT = 4
NBFORMAT_MINOR = 5

_MODULE_CELL = '''# __TASK__ — __NAME__ (S=__S__, __RUN__, medido=__MEASURED__)
# Módulo del dataset: estructura + código ejecutable (module.py).
import importlib.util
import json
import tempfile
from pathlib import Path

try:
    _TASK_MODULES
except NameError:
    _TASK_MODULES = {}

_TMP = Path(tempfile.mkdtemp(prefix="auto_mvp___TASK___"))
(_TMP / "structure.json").write_text(__STRUCTURE__, encoding="utf-8")
(_TMP / "module.py").write_text(__MODULE__, encoding="utf-8")
_SPEC = importlib.util.spec_from_file_location("module___TASK__", _TMP / "module.py")
_MOD = importlib.util.module_from_spec(_SPEC)
import sys as _sys
_sys.modules["module___TASK__"] = _MOD  # sin esto, @dataclass revienta (v2.17.24)
_SPEC.loader.exec_module(_MOD)
_TASK_MODULES["__TASK__"] = _MOD
print(json.dumps(_MOD.verify(), indent=2, ensure_ascii=False))
'''

_FALLBACK_CELL = '''# __TASK__ — __NAME__ (S=__S__, __RUN__, medido=__MEASURED__)
# Sin module.py en el dataset: fallback del ledger (component.json).
import json
from types import SimpleNamespace

try:
    _TASK_MODULES
except NameError:
    _TASK_MODULES = {}

_ENTRY = json.loads(__ENTRY__)

def _verify(_e=_ENTRY):
    return {"name": _e.get("name"), "task": _e.get("task"),
            "S": float(_e["S"]), "gm": None, "has_call_graph": False,
            "ok": True,
            "reasons": ["sin module.py en el dataset: S tomado del ledger"]}

_TASK_MODULES["__TASK__"] = SimpleNamespace(
    verify=_verify, build=lambda: (None, _ENTRY.get("metrics", {})))
print(json.dumps(_TASK_MODULES["__TASK__"].verify(), indent=2, ensure_ascii=False))
'''

_FINAL_CELL = '''# Verificación: la GM recomputada desde los tres módulos ganadores.
import json
import math

REFERENCE_S = __REFERENCE_S__
TARGET_GM = __TARGET_GM__
RECORDED_GM = __RECORDED_GM__

_MODS = globals().get("_TASK_MODULES", {})
S = {}
for task in ("invsqrt", "dqi", "dfthcsos"):
    mod = _MODS.get(task)
    if mod is None:
        print(task + ": sin módulo (la celda no corrió)")
        continue
    S[task] = float(mod.verify()["S"])
    print(task + ": S = %.6g  ratio = %.4f" % (S[task], REFERENCE_S[task] / S[task]))

if len(S) == 3:
    gm = math.exp(sum(math.log(REFERENCE_S[t] / s) for t, s in S.items()) / 3.0)
    if RECORDED_GM is None:
        print("GM recomputada = %.5f  (sin GM registrada)" % gm)
    else:
        print("GM recomputada = %.5f  (registrada %.5f)" % (gm, RECORDED_GM))
    if gm >= TARGET_GM:
        print("LLEGA al objetivo %.2f" % TARGET_GM)
    else:
        print("NO llega al objetivo %.2f" % TARGET_GM)
else:
    print("Faltan tareas: no se puede recomputar la GM")
'''


def _quote(text: str) -> str:
    """Un literal de cadena triple que no choque con el contenido."""
    if not text.endswith("\n"):
        text += "\n"
    for q in ("'''", '"""'):
        if q not in text:
            return f"{q}{text}{q}"
    return repr(text)


def _src(text: str) -> list[str]:
    return text.splitlines(keepends=True)


def _md_cell(lines: list[str]) -> dict[str, Any]:
    return {"cell_type": "markdown", "metadata": {}, "source": lines}


def _code_cell(code: str) -> dict[str, Any]:
    return {"cell_type": "code", "execution_count": None,
            "metadata": {}, "outputs": [], "source": _src(code)}


def _intro_lines(combo: dict[str, Any]) -> list[str]:
    lines = [
        "# AUTO_MVP — notebook de los ganadores\n",
        "\n",
        "Los tres mejores componentes por tarea, listos para la "
        "compilación pesada (fase 3).\n",
        "\n",
        f"- Objetivo (meta_mvp): {combo['target']:.2f}\n",
        (f"- GM de la combinación: {combo['gm']:.5f}\n"
         if combo["gm"] is not None else "- GM de la combinación: sin datos\n"),
        f"- Llega al objetivo: {'SÍ' if combo['reached'] else 'NO'}\n",
        f"- Proyectado (algún componente sin medir): "
        f"{'SÍ' if combo['projected'] else 'NO'}\n",
        "\n",
        "| tarea | componente | S | ratio | corrida | iteración | medido |\n",
        "|---|---|---|---|---|---|---|\n",
    ]
    for task in TASKS:
        e = combo["components"].get(task)
        if e is None:
            continue
        lines.append(
            f"| {task} | {e.get('name')} | {float(e['S']):.6g} | "
            f"{float(e.get('ratio', 0)):.4f} | {e.get('run_id')} | "
            f"{e.get('iteration')} | {'sí' if e.get('measured') else 'no'} |\n")
    lines.append("\nCada celda de tarea carga su módulo y corre verify(); "
                 "la última celda recomputa la GM desde los tres S.\n")
    return lines


def _task_cell(task: str, entry: dict[str, Any],
               dataset_root: str | Path) -> str:
    """La celda de una tarea: module.py del dataset o fallback."""
    subs = {"__TASK__": task, "__NAME__": str(entry.get("name", task)),
            "__S__": f"{float(entry['S']):.6g}",
            "__RUN__": str(entry.get("run_id", "")),
            "__MEASURED__": "sí" if entry.get("measured") else "no"}
    art = entry.get("artifact_name")
    mod_dir = Path(dataset_root) / str(art) if art else None
    mod_path = mod_dir / "module.py" if mod_dir else None
    struct_path = mod_dir / "structure.json" if mod_dir else None
    if mod_path and mod_path.is_file() and struct_path.is_file():
        tpl = _MODULE_CELL
        subs["__STRUCTURE__"] = _quote(
            struct_path.read_text(encoding="utf-8"))
        subs["__MODULE__"] = _quote(mod_path.read_text(encoding="utf-8"))
    else:
        tpl = _FALLBACK_CELL
        subs["__ENTRY__"] = _quote(json.dumps(entry, ensure_ascii=False))
    for k, v in subs.items():
        tpl = tpl.replace(k, v)
    return tpl


def _final_cell(target: float, gm: float | None) -> str:
    return (_FINAL_CELL
            .replace("__REFERENCE_S__", repr(dict(REFERENCE_S)))
            .replace("__TARGET_GM__", repr(float(target)))
            .replace("__RECORDED_GM__", repr(gm)))


def export_winner_notebook(ledger, dataset_root: str | Path,
                           out_path: str | Path,
                           target_gm: float | None = None) -> dict[str, Any]:
    """Exporta los tres mejores componentes en un .ipynb ejecutable.

    ledger: BestLedger (best_per_task.json). dataset_root: el
    dataset de trabajo (<runs_dir>/dataset). Devuelve path, files,
    gm, reached, target y tasks (las tareas incluidas).
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    target = (float(target_gm) if target_gm is not None
              else (ledger.combined_gm() or 0.0))
    combo = combine(ledger, target)
    cells: list[dict[str, Any]] = [_md_cell(_intro_lines(combo))]
    tasks: list[str] = []
    for task in TASKS:
        entry = ledger.entries.get(task)
        if entry is None:
            continue
        cells.append(_code_cell(_task_cell(task, entry, dataset_root)))
        tasks.append(task)
    cells.append(_code_cell(_final_cell(target, combo["gm"])))
    nb = {
        "nbformat": NBFORMAT,
        "nbformat_minor": NBFORMAT_MINOR,
        "metadata": {
            "kernelspec": {"display_name": "Python 3",
                           "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3"},
        },
        "cells": cells,
    }
    out_path.write_text(json.dumps(nb, indent=1, ensure_ascii=False),
                        encoding="utf-8")
    return {"path": str(out_path), "files": [str(out_path)],
            "gm": combo["gm"], "reached": combo["reached"],
            "target": target, "tasks": tasks}

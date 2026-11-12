"""AUTO_MVP — orquestación en serie por tarea con compensación global (desde v1.1.0).

El combiner ya guarda el mejor por tarea y calcula la GM combinada.
Lo que faltaba: correr las tres tareas EN SERIE con el mismo ledger
y aceptar el balance GLOBAL de forma automática — si una tarea se
queda ligeramente rezagada pero las otras dos superan el umbral,
el orquestador acepta la combinación y lo registra en el ranking
dinámico, en vez de exigir que cada tarea llegue sola a su objetivo.

La aceptación es la GM combinada contra meta_mvp (no por tarea).
Cada tarea corre su mutador + pipeline; después de cada una se
recalcula la combinación y, si llega, se para y se exporta la base
de auditoría (y el Notebook, si se pide).
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from .combiner import TASKS, BestLedger, combine, export_audit_zip
from .mutator import Mutator
from .pipeline import Pipeline
from .proxy import MetadataProxy
from .vqcc.contracts import SPECS


def run_serial(jobs: list[dict[str, Any]], target_gm: float = 30.0,
               runs_dir: str | Path = "runs",
               margin: float = 0.10,
               export_notebook: bool = False) -> dict[str, Any]:
    """Corre las tareas en serie con el mismo ledger y compensación global.

    ``jobs``: lista de dicts por tarea con ``task``, ``seed_graph``
    (CallGraph o dict), ``base_metrics`` y opcionalmente ``rules``,
    ``mutator_kwargs`` y ``n`` (candidatos por tarea, por defecto 10).
    Devuelve {target, gm, reached, per_task, compensation, audit_zip,
    notebook}.
    """
    runs_dir = Path(runs_dir)
    ledger = BestLedger(runs_dir / "best_per_task.json")
    per_task: list[dict[str, Any]] = []
    compensation: dict[str, Any] = {
        "accepted": False, "lagging_tasks": [], "compensating_tasks": []}
    audit_zip = ""
    notebook_path = ""
    for job in jobs:
        task = job["task"]
        spec = SPECS[task]()
        proxy = MetadataProxy(spec, hard_caps={"max_qubits": 2000},
                              margin=margin)
        pipe = Pipeline(proxy, runs_dir=runs_dir, meta_mvp=target_gm,
                        run_id=f"serial-{task}")
        mut = Mutator(job["seed_graph"], task, job["base_metrics"],
                      rules=job.get("rules"),
                      **job.get("mutator_kwargs", {}))
        res = pipe.run(mut.propose(job.get("n", 10)))
        combo = combine(ledger, target_gm)
        entry = {
            "task": task, "promoted": res.promoted,
            "screened": res.screened, "proxy_rejected": res.proxy_rejected,
            "best_S": (res.best or {}).get("S", {}),
            "combined_gm": combo["gm"], "reached": combo["reached"]}
        per_task.append(entry)
        if combo["reached"]:
            # Compensación global: la combinación llega aunque alguna
            # tarea siga por debajo de su S requerido individual.
            gaps = combo.get("required", {}) if isinstance(combo, dict) else {}
            for t in TASKS:
                cur = ledger.best().get(t, {}).get("S")
                req = gaps.get(t, {}).get("required_S") if isinstance(gaps, dict) else None
                if cur is None or req is None:
                    continue
                if cur > req:
                    compensation["lagging_tasks"].append(
                        {"task": t, "S": cur, "required_S": req})
                else:
                    compensation["compensating_tasks"].append(
                        {"task": t, "S": cur, "required_S": req})
            compensation["accepted"] = True
            break
    combo = combine(ledger, target_gm)
    if combo["reached"]:
        audit = export_audit_zip(
            ledger, runs_dir / f"audit-base-{combo['gm']:.2f}.zip",
            dataset_root=runs_dir / "dataset", target_gm=target_gm)
        audit_zip = audit["path"]
        if export_notebook:
            from .notebook import export_winner_notebook
            nb = export_winner_notebook(
                ledger, runs_dir / "dataset",
                runs_dir / f"winners-gm-{combo['gm']:.2f}.ipynb",
                target_gm=target_gm)
            notebook_path = nb["path"]
    return {
        "target": target_gm, "gm": combo["gm"], "reached": combo["reached"],
        "per_task": per_task, "compensation": compensation,
        "audit_zip": audit_zip, "notebook": notebook_path}

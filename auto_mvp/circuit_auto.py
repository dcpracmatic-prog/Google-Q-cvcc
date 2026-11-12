"""AUTO_MVP v2.0 — el corredor de circuitos: proponer, validar, medir, repetir.

La DIRECTIVA v2.0 de Arturo (2026-11-11 23:47 CST): fuerza bruta
sobre CIRCUITOS. El corredor propone circuitos reales (sa_windows
sobre la semilla), los VALIDA con el protocolo oficial (si no es
válido, no cuenta, no es nada), los MIDE simulando (el S sale de la
medición, no de una fórmula sobre números inventados), guarda el
mejor CON SU CIRCUITO (.kmx en runs/best/), y repite. Solo paran los
límites que ponga quien ejecuta (propuestas/tiempo) o llegar a la
meta. Nunca se para por estancamiento. Me vale madre si tarda un año.

Uso::

    python -m auto_mvp.circuit_auto --target-S 90000 --max-proposals 10

v2.0 cubre invsqrt (semilla vendida en el repo, operador sa_windows,
verificador oficial vendido). DQI y química usan la misma forma
(proponer → validar → medir → repetir) con sus semillas y sus
verificadores; sus semillas viven en el dataset de la competencia
(dqi_ref.kmx pesa 1.5 GB y no cabe en el repo; los angle_k .kmb
también), así que se pasan con --dataset.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Callable

from .circuit import (SEED_INVSQRT, fast_verify_invsqrt, propose_sa_windows)

# El S certificado de la semilla invsqrt (verificador oficial).
SEED_S = {"invsqrt": 100568.5}


def _ledger_path(runs_dir: Path) -> Path:
    return runs_dir / "circuit_ledger.json"


def _load_ledger(runs_dir: Path, task: str) -> dict[str, Any]:
    p = _ledger_path(runs_dir)
    if p.is_file():
        try:
            led = json.loads(p.read_text(encoding="utf-8"))
            if led.get("task") == task and led.get("best"):
                return led
        except Exception:
            pass
    return {"task": task, "best": None, "proposals": 0, "valid": 0,
            "invalid": 0, "rejected": []}


def _save_ledger(runs_dir: Path, led: dict[str, Any]) -> None:
    runs_dir.mkdir(parents=True, exist_ok=True)
    _ledger_path(runs_dir).write_text(
        json.dumps(led, indent=1, ensure_ascii=False), encoding="utf-8")


def run_circuit_auto(target_S: float, task: str = "invsqrt",
                     runs_dir: str | Path = "runs",
                     max_proposals: int | None = None,
                     time_budget_seconds: float | None = None,
                     sa_budget_s: float = 60.0,
                     sa_K: tuple[int, ...] = (5, 6, 7),
                     fast_max_x: int = 1024,
                     seed: int = 42,
                     on_proposal: Callable[[dict[str, Any]], None] | None = None
                     ) -> dict[str, Any]:
    """Fuerza bruta sobre circuitos hasta la meta (o hasta el límite).

    ``target_S`` es el S medido que se quiere (un número: si se quiere
    S <= 90,000, se dice 90,000). Solo paran ``max_proposals`` /
    ``time_budget_seconds`` (los límites de quien ejecuta) o llegar a
    la meta. Devuelve {task, target_S, best_S, best_circuit, reached,
    proposals, valid, invalid, runs_dir}.
    """
    if task != "invsqrt":
        raise ValueError(
            f"v2.0 cubre invsqrt; {task} usa la misma forma con su "
            "semilla y su verificador (pendiente: DQI y química)")
    target = float(target_S)
    if not (math.isfinite(target) and target > 0):
        raise ValueError(f"target_S debe ser finito y > 0, got {target_S!r}")
    runs_dir = Path(runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    best_dir = runs_dir / "best"
    best_dir.mkdir(parents=True, exist_ok=True)
    cand_dir = runs_dir / "candidates"
    cand_dir.mkdir(parents=True, exist_ok=True)
    progress_path = runs_dir / "circuit-progress.jsonl"
    started = time.monotonic()

    def _progress(entry: dict[str, Any]) -> None:
        with progress_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(f"[circuito] {entry}", file=sys.stderr, flush=True)
        if on_proposal is not None:
            on_proposal(entry)

    led = _load_ledger(runs_dir, task)
    if led["best"] is None:
        # La semilla, medida: el punto de partida es un circuito real
        # y válido, con su S medido, no un número supuesto.
        seed_measure = fast_verify_invsqrt(SEED_INVSQRT, max_x=fast_max_x)
        if not seed_measure["valid"]:
            raise RuntimeError(
                "la semilla vendida no es válida: "
                f"{seed_measure.get('reason')}")
        best_path = (best_dir / "invsqrt.kmx").resolve()
        shutil.copyfile(SEED_INVSQRT, best_path)
        led["best"] = {
            "S": seed_measure["S"], "circuit": str(best_path),
            "operator": "seed", "proposal": 0,
            "measure": seed_measure,
        }
        _save_ledger(runs_dir, led)
        _progress({"proposal": 0, "operator": "seed",
                   "S": seed_measure["S"], "valid": True,
                   "note": "semilla medida"})
    best_S = float(led["best"]["S"])
    best_path = Path(led["best"]["circuit"])
    if best_S <= target:
        return {"task": task, "target_S": target, "best_S": best_S,
                "best_circuit": str(best_path), "reached": True,
                "proposals": 0, "valid": led["valid"],
                "invalid": led["invalid"], "runs_dir": str(runs_dir),
                "stopped": "la semilla ya llega a la meta"}

    proposals = 0
    stopped = "límite alcanzado"
    while True:
        proposals += 1
        i = proposals
        K = sa_K[(i - 1) % len(sa_K)]
        op_seed = int(seed) + i
        cand_path = cand_dir / f"invsqrt_p{i:04d}_k{K}_s{op_seed}.kmx"
        log_path = cand_dir / f"invsqrt_p{i:04d}_k{K}_s{op_seed}.json"
        prop = propose_sa_windows(best_path, cand_path, log_path,
                                  K=K, budget_s=float(sa_budget_s),
                                  seed=op_seed)
        entry: dict[str, Any] = {"proposal": i, "K": K, "seed": op_seed,
                                 "operator": "sa_windows",
                                 "gain_reported": prop.get("gain", 0)}
        if not prop["ok"]:
            entry.update({"valid": False, "reason": prop.get("reason", ""),
                          "note": "el operador falló, no es un circuito"})
            led["invalid"] += 1
            led["rejected"].append(entry)
            _save_ledger(runs_dir, led)
            _progress(entry)
        else:
            measure = fast_verify_invsqrt(cand_path, max_x=fast_max_x)
            entry["valid"] = bool(measure["valid"])
            if not measure["valid"]:
                entry["reason"] = measure.get("reason", "")
                entry["note"] = "INVÁLIDO: no cuenta, no es nada"
                led["invalid"] += 1
                led["rejected"].append(entry)
                _save_ledger(runs_dir, led)
                _progress(entry)
            else:
                led["valid"] += 1
                entry["S"] = measure["S"]
                entry["toffoli_count"] = measure["toffoli_count"]
                if measure["S"] < best_S:
                    new_best = (best_dir / "invsqrt.kmx").resolve()
                    shutil.copyfile(cand_path, new_best)
                    best_S = float(measure["S"])
                    best_path = new_best
                    led["best"] = {"S": best_S, "circuit": str(new_best),
                                   "operator": "sa_windows", "proposal": i,
                                   "measure": measure}
                    entry["note"] = "MEJORA: nuevo mejor"
                else:
                    entry["note"] = "válido pero no mejora"
                led["proposals"] = proposals
                _save_ledger(runs_dir, led)
                _progress(entry)
        if best_S <= target:
            stopped = "meta alcanzada"
            break
        if max_proposals is not None and proposals >= int(max_proposals):
            stopped = f"límite de propuestas ({max_proposals})"
            break
        if (time_budget_seconds is not None
                and time.monotonic() - started >= float(time_budget_seconds)):
            stopped = f"presupuesto de tiempo ({time_budget_seconds}s)"
            break
    led["proposals"] = proposals
    _save_ledger(runs_dir, led)
    return {"task": task, "target_S": target, "best_S": best_S,
            "best_circuit": str(best_path),
            "reached": bool(best_S <= target), "proposals": proposals,
            "valid": led["valid"], "invalid": led["invalid"],
            "runs_dir": str(runs_dir), "stopped": stopped}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Corredor de circuitos v2.0 (invsqrt): proponer, "
                    "validar, medir, repetir.")
    ap.add_argument("--target-S", type=float, required=True,
                    help="el S medido que se quiere (p. ej. 90000)")
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--max-proposals", type=int, default=None)
    ap.add_argument("--time-budget", type=float, default=None,
                    help="segundos; si no, hasta llegar o cancelar")
    ap.add_argument("--sa-budget-s", type=float, default=60.0)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args(argv)
    res = run_circuit_auto(
        args.target_S, runs_dir=args.runs_dir,
        max_proposals=args.max_proposals,
        time_budget_seconds=args.time_budget, sa_budget_s=args.sa_budget_s,
        seed=args.seed)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0 if res["reached"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""AUTO_MVP — el corredor autónomo: instalar, decir cuánto quieres, ejecutar.

Uso (después de instalar el paquete, o desde el repo)::

    python -m auto_mvp.auto --target 25
    auto-mvp auto --target 25 --runs-dir runs

O en Python::

    from auto_mvp.auto import run_auto
    run_auto(25.0)

Esto NO es la solución de la competencia ni la construye: no crea
.circuits .kmb, no compila, no envía nada a Kaggle. Lo que hace es
encontrar la BASE para que se cree una solución: las configuraciones
y las métricas de las tres tareas que, juntas y según la puntuación
de la competencia (media geométrica de los ratios contra el baseline
oficial), llegan a la meta que se le diga.

Cómo funciona, en simple:

- La meta (``target``) la dice quien ejecuta. No hay número fijo:
  1.5, 25, 10_000, lo que se quiera. El sistema lo intenta hasta
  encontrarlo; si no llega, sigue intentando. Solo paran los límites
  que ponga quien ejecuta (--max-rounds, --time-budget) o llegar a
  la meta. Nunca se para por "ya no mejora".
- Rondas 1, 2, 3, 1, 2, 3...: en cada ronda cada tarea corre dos
  búsquedas en paralelo:
  (a) el mutador real (morph, ventana SA, salto Lévy, MWIS) sobre su
  semilla (``seeds.py``, números medidos, nada inventado), por el
  pipeline (proxy + puerta + integridad); lo que mejora el S medido
  queda en el ledger;
  (b) la fuerza bruta (``brute.py``): las variables de costo de cada
  tarea se bajan con operaciones aritméticas, de menor a mayor cambio
  (restar 1, 10, 100..., multiplicar por 0.99, 0.9, 0.5, dividir entre
  2...), LAS TRES A LA VEZ: cada una mejora por el mismo factor
  (la meta es el producto cruzado, GM = (r1*r2*r3)^(1/3)), no una sola
  cargando toda la meta mientras las otras se quedan. Cerca del
  objetivo solo se usan pasos finos, para no pasar de largo de un
  salto. Los conteos son enteros (un circuito no tiene 404.92
  cúbits) y cada propuesta pasa los límites físicos del contrato
  oficial (DQI eps+ < 1/16 con su R exacta, química Lambda > 49,
  E_gap > 3.914898, error <= 20 mHa, Angles_k <= 128 cúbits).
  Son propuestas de números, no circuitos: nunca entran al ledger y
  van marcadas como proyectado.
- Después de cada tarea se recalcula la combinación de los mejores
  por tarea (lo mejor real o lo mejor de fuerza bruta, lo que sea
  menor). Cuando la combinación llega a la meta, se para y se entrega
  un ZIP con las configuraciones y las métricas de cada componente
  (``component.json`` + ``manifest.json`` por tarea): la base para
  auditar y diseñar la solución real. Sin .kmb dentro. El manifest
  dice qué componente es medido y cuál es proyectado (fuerza bruta).
  Además se entrega el Notebook de los ganadores
  (``winners-gm-<gm>.ipynb``, los tres módulos listos para la
  compilación pesada) y el balance global de la compensación: la
  aceptación es la GM combinada, así que una tarea puede ir rezagada
  si las otras dos compensan, y queda registrado quién va rezagado
  y quién compensa. Si en runs hay .kmb/.kmx, se cargan con el
  compilador oficial de Kickmix (``km.Circuit.from_file``) y el
  resultado va en ``kmb_validation``: la base no lleva .kmb, pero
  lo que haya se valida.

Solo stdlib. No instala nada, no baja nada, no necesita Qualtran
(el puente lo importa bajo demanda solo si se usa) ni el dataset
de la competencia: las semillas y las fórmulas de costo ya viven
en el repo. El dataset inmutable de la competencia se usa después,
fuera de aquí, para compilar y verificar la solución real.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from .brute import BruteForce
from .combiner import (REFERENCE_S, TASKS, BestLedger, combine,
                       export_audit_zip, export_base_zip)
from .mutator import Mutator
from .notebook import export_winner_notebook
from .pipeline import Pipeline
from .proxy import MetadataProxy
from .seeds import default_seeds
from .serial import compensation_record
from .vqcc.contracts import SPECS

# El orden de las rondas: tarea 1, 2, 3, 1, 2, 3...
ROUND_ORDER: tuple[str, ...] = ("dqi", "invsqrt", "dfthcsos")


def _check_target(target: float) -> float:
    """La meta: un número finito mayor que 0. Sin número fijo."""
    t = float(target)
    if not (math.isfinite(t) and t > 0):
        raise ValueError(f"target debe ser finito y > 0, got {target!r}")
    return t


def _fresh_ledger(runs_dir: Path) -> BestLedger:
    """El ledger tal como está guardado en disco (fuente de verdad)."""
    return BestLedger(runs_dir / "best_per_task.json")


def _gm_of_S(S: dict[str, float]) -> float:
    """Media geométrica de los ratios contra el baseline oficial."""
    rs = [REFERENCE_S[t] / s for t, s in S.items()]
    return math.exp(sum(math.log(r) for r in rs) / len(rs))


def _balanced_need(best_S: dict[str, float], task: str,
                   target: float, gm: float) -> float:
    """El S que esta tarea necesitaría si las tres mejoran a la vez.

    La meta es el producto cruzado: GM = (r1*r2*r3)^(1/3). Para llegar
    a la meta con las tres tareas a la vez, cada una tiene que mejorar
    por el mismo factor g = (target/GM)^(1/3): su S tiene que bajar a
    S/g. Nada de cargar toda la meta en una sola tarea mientras las
    otras dos se quedan como están: eso era el salto artificial
    (DQI solo, GM 37.95 para meta 30).
    """
    g = (float(target) / float(gm)) ** (1.0 / len(TASKS))
    return float(best_S[task]) / g


def _check_kmb_files(runs_dir: Path) -> dict[str, Any]:
    """Valida los .kmb/.kmx que haya en runs con el compilador Kickmix.

    La base que entrega el corredor NO lleva .kmb (son configuraciones
    y métricas, no circuitos). Pero si en runs hay .kmb/.kmx (porque
    alguien los dejó ahí o porque se compilaron desde la base), se
    cargan con km.Circuit.from_file (el compilador oficial) y se
    reporta si pasan o no. Sin kickmix instalado, se dice así.
    Nunca tumba la corrida: esto es un chequeo, no la entrega.
    """
    found = sorted(str(p) for p in runs_dir.rglob("*")
                   if p.is_file() and p.suffix.lower() in (".kmb", ".kmx"))
    out: dict[str, Any] = {"present": found, "loaded": {}}
    if not found:
        return out
    try:
        import kickmix as km
    except Exception:
        out["kickmix"] = "no disponible en este entorno"
        return out
    for f in found:
        try:
            km.Circuit.from_file(f, format="auto")
            out["loaded"][f] = {"ok": True}
        except Exception as exc:
            out["loaded"][f] = {"ok": False, "error": str(exc)[:300]}
    return out


def _notebook_and_compensation(
        runs_dir: Path, entries: dict[str, dict[str, Any]],
        target: float, gm: float) -> tuple[str, dict[str, Any]]:
    """El Notebook de los ganadores + el balance global de la entrega.

    El Notebook se arma desde un ledger TEMPORAL con las entradas
    entregadas (reales o de fuerza bruta): el ledger real NUNCA
    recibe las de fuerza bruta, pero el Notebook debe mostrar la
    combinación entregada, no solo lo real. La compensación dice qué
    tarea va rezagada y cuál compensa (la aceptación es la GM global).
    """
    with tempfile.TemporaryDirectory() as tmp:
        delivered = BestLedger(Path(tmp) / "delivered.json")
        for task, entry in entries.items():
            delivered.record(task, entry)
        nb = export_winner_notebook(
            delivered, runs_dir / "dataset",
            runs_dir / f"winners-gm-{gm:.2f}.ipynb", target_gm=target)
        return str(nb["path"]), compensation_record(delivered, target)


def run_auto(target: float,
             runs_dir: str | Path = "runs",
             n_per_task: int = 10,
             brute_steps: int = 200,
             max_rounds: int | None = None,
             time_budget_seconds: float | None = None,
             seed: int = 42,
             margin: float = 0.10,
             on_round: Callable[[dict[str, Any]], None] | None = None
             ) -> dict[str, Any]:
    """Corre el buscador autónomo hasta la meta (o hasta el límite).

    ``target`` es obligatorio: la puntuación que se quiere (1.5, 25,
    10_000...). ``n_per_task``: mutantes reales por tarea y ronda.
    ``brute_steps``: operaciones aritméticas de fuerza bruta por tarea
    y ronda. ``max_rounds`` / ``time_budget_seconds``: los únicos
    límites de parada que pone quien ejecuta (si no, hasta llegar).
    Devuelve {target, gm, reached, projected, rounds, stopped,
    per_round, zip, notebook, compensation, runs_dir, best_S, brute}.
    """
    target = _check_target(target)
    runs_dir = Path(runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    seeds = default_seeds()
    per_round: list[dict[str, Any]] = []
    progress_path = runs_dir / "auto-progress.jsonl"

    def _progress(entry: dict[str, Any]) -> None:
        per_round.append(entry)
        with progress_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        if on_round is not None:
            on_round(entry)

    def _best_S(ledger: BestLedger,
                brute_best: dict[str, dict[str, Any] | None]
                ) -> dict[str, float]:
        out = dict(ledger.combined_S())
        for task, b in brute_best.items():
            if b is not None and b["S"] is not None:
                if task not in out or b["S"] < out[task]:
                    out[task] = float(b["S"])
        return out

    def _entries(ledger: BestLedger,
                 brute_best: dict[str, dict[str, Any] | None],
                 rounds: int) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for task in TASKS:
            real = ledger.entries.get(task)
            brute = brute_best.get(task)
            if (brute is not None and brute["S"] is not None
                    and (real is None
                         or float(brute["S"]) < float(real["S"]))):
                out[task] = {
                    "task": task,
                    "name": f"brute:{task}",
                    "kind": "brute",
                    "S": float(brute["S"]),
                    "ratio": REFERENCE_S[task] / float(brute["S"]),
                    "metrics": brute["metrics"],
                    "artifact_name": None,
                    "run_id": "auto-brute",
                    "iteration": rounds,
                    "measured": False,
                    "source_commit": None,
                    "ops": brute["ops"],
                }
            elif real is not None:
                out[task] = dict(real)
        return out

    # Ronda 0: la base conocida ya puede llegar (el ledger parte del
    # mejor envío). Si llega, se entrega sin correr nada.
    ledger = _fresh_ledger(runs_dir)
    combo = combine(ledger, target)
    if combo["reached"]:
        gm = float(combo["gm"])
        audit = export_audit_zip(
            ledger, runs_dir / f"audit-base-{gm:.2f}.zip",
            dataset_root=runs_dir / "dataset", target_gm=target)
        notebook_path, compensation = _notebook_and_compensation(
            runs_dir, {t: dict(e) for t, e in ledger.entries.items()},
            target, gm)
        return {
            "target": target, "gm": gm, "reached": True,
            "projected": False, "rounds": 0,
            "stopped": "la base conocida ya llega a la meta",
            "per_round": per_round, "zip": str(audit["path"]),
            "notebook": notebook_path, "compensation": compensation,
            "runs_dir": str(runs_dir),
            "best_S": ledger.combined_S(), "brute": {},
            "kmb_validation": _check_kmb_files(runs_dir),
        }

    # Mutadores reales persistentes por tarea + caminatas de fuerza
    # bruta persistentes (siguen donde se quedaron, ronda tras ronda).
    mutators: dict[str, Mutator] = {}
    pipes: dict[str, Pipeline] = {}
    brutes: dict[str, BruteForce] = {}
    brute_best: dict[str, dict[str, Any] | None] = {}
    for task in ROUND_ORDER:
        mutators[task] = Mutator(
            seeds[task]["seed_graph"], task, seeds[task]["base_metrics"],
            seed=seed)
        spec = SPECS[task]()
        pipes[task] = Pipeline(
            MetadataProxy(spec, hard_caps={"max_qubits": 2000},
                          margin=margin),
            runs_dir=runs_dir, meta_mvp=target, run_id=f"auto-{task}")
        brutes[task] = BruteForce(task, seeds[task]["base_metrics"])
        brute_best[task] = None

    rounds = 0
    while True:
        rounds += 1
        round_entry: dict[str, Any] = {"round": rounds, "tasks": {}}
        for task in ROUND_ORDER:
            # (a) mutación real sobre la semilla.
            res = pipes[task].run(mutators[task].propose(n_per_task))
            ledger = _fresh_ledger(runs_dir)
            best = _best_S(ledger, brute_best)
            gm = _gm_of_S(best)
            if gm >= target:
                entries = _entries(ledger, brute_best, rounds)
                projected = any(not e.get("measured", False)
                                for e in entries.values())
                audit = export_base_zip(
                    entries, runs_dir / f"audit-base-{gm:.2f}.zip",
                    target_gm=target, gm=gm,
                    required=ledger.gaps(target))
                notebook_path, compensation = _notebook_and_compensation(
                    runs_dir, entries, target, gm)
                round_entry["tasks"][task] = {
                    "screened": res.screened, "promoted": res.promoted,
                    "proxy_rejected": res.proxy_rejected,
                    "brute_steps": 0, "brute_exhausted": False,
                    "gm": gm, "reached": True,
                }
                _progress(round_entry)
                return {
                    "target": target, "gm": gm, "reached": True,
                    "projected": projected, "rounds": rounds,
                    "stopped": "meta alcanzada",
                    "per_round": per_round, "zip": str(audit["path"]),
                    "notebook": notebook_path,
                    "compensation": compensation,
                    "runs_dir": str(runs_dir), "best_S": best,
                    "brute": {t: (None if b is None else {
                        "S": b["S"], "ops": b["ops"]})
                        for t, b in brute_best.items()},
                    "kmb_validation": _check_kmb_files(runs_dir),
                }
            # (b) fuerza bruta: las tres a la vez, cada una hacia su
            # parte equilibrada de la meta (no una sola cargando todo).
            need = _balanced_need(best, task, target, gm)
            walk = brutes[task].walk(need, max_steps=brute_steps)
            if walk["S"] is not None:
                cur = brute_best[task]
                if cur is None or walk["S"] < cur["S"]:
                    brute_best[task] = {
                        "S": walk["S"], "metrics": walk["metrics"],
                        "ops": list(brutes[task].ops_used),
                    }
            best = _best_S(ledger, brute_best)
            gm = _gm_of_S(best)
            round_entry["tasks"][task] = {
                "screened": res.screened, "promoted": res.promoted,
                "proxy_rejected": res.proxy_rejected,
                "brute_steps": walk["steps_used"],
                "brute_exhausted": walk["exhausted"],
                "gm": gm, "reached": gm >= target,
            }
            if gm >= target:
                entries = _entries(ledger, brute_best, rounds)
                projected = any(not e.get("measured", False)
                                for e in entries.values())
                audit = export_base_zip(
                    entries, runs_dir / f"audit-base-{gm:.2f}.zip",
                    target_gm=target, gm=gm,
                    required=ledger.gaps(target))
                notebook_path, compensation = _notebook_and_compensation(
                    runs_dir, entries, target, gm)
                _progress(round_entry)
                return {
                    "target": target, "gm": gm, "reached": True,
                    "projected": projected, "rounds": rounds,
                    "stopped": "meta alcanzada",
                    "per_round": per_round, "zip": str(audit["path"]),
                    "notebook": notebook_path,
                    "compensation": compensation,
                    "runs_dir": str(runs_dir), "best_S": best,
                    "brute": {t: (None if b is None else {
                        "S": b["S"], "ops": b["ops"]})
                        for t, b in brute_best.items()},
                    "kmb_validation": _check_kmb_files(runs_dir),
                }
        _progress(round_entry)
        if max_rounds is not None and rounds >= int(max_rounds):
            stopped = f"límite de rondas ({max_rounds})"
            break
        if (time_budget_seconds is not None
                and time.monotonic() - started >= float(time_budget_seconds)):
            stopped = f"presupuesto de tiempo ({time_budget_seconds}s)"
            break
        # Solo se para sin llegar si YA NO HAY NADA QUE PROBAR: la
        # fuerza bruta llegó a los pisos en las tres tareas (T=1, Q=1...).
        # Para cualquier meta realista los pisos están lejísimos; esto
        # es un hecho aritmético, no rendirse: con esos pisos ningún
        # circuito real podría tener un S menor.
        if all(brutes[t].exhausted for t in ROUND_ORDER):
            stopped = ("frontera aritmética: ni con T=1, Q=1 se llega")
            break
    ledger = _fresh_ledger(runs_dir)
    best = _best_S(ledger, brute_best)
    _entries_final = _entries(ledger, brute_best, rounds)
    with tempfile.TemporaryDirectory() as tmp:
        _delivered = BestLedger(Path(tmp) / "delivered.json")
        for _task, _entry in _entries_final.items():
            _delivered.record(_task, _entry)
        compensation = compensation_record(_delivered, target)
    return {
        "target": target, "gm": _gm_of_S(best), "reached": False,
        "projected": False, "rounds": rounds, "stopped": stopped,
        "per_round": per_round, "zip": "", "notebook": "",
        "compensation": compensation,
        "runs_dir": str(runs_dir), "best_S": best,
        "brute": {t: (None if b is None else {
            "S": b["S"], "ops": b["ops"]}) for t, b in brute_best.items()},
        "gaps": ledger.gaps(target),
        "kmb_validation": _check_kmb_files(runs_dir),
    }


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada: python -m auto_mvp.auto --target <meta>."""
    p = argparse.ArgumentParser(
        prog="auto-mvp auto",
        description="Buscador autónomo: dime cuánto quieres y busca la base.")
    p.add_argument("--target", type=float, required=True,
                   help="puntuación a alcanzar (ej. 25, 1.5, 10000)")
    p.add_argument("--runs-dir", default="runs",
                   help="dónde guardar runs y el ZIP (por defecto runs)")
    p.add_argument("--n", type=int, default=10,
                   help="mutantes por tarea y ronda (por defecto 10)")
    p.add_argument("--brute-steps", type=int, default=200,
                   help="operaciones de fuerza bruta por tarea y ronda")
    p.add_argument("--max-rounds", type=int, default=None,
                   help="límite de rondas (si no, hasta llegar)")
    p.add_argument("--time-budget", type=float, default=None,
                   help="presupuesto de tiempo en segundos")
    p.add_argument("--seed", type=int, default=42,
                   help="semilla del generador (determinista)")
    args = p.parse_args(argv)

    def _show(entry: dict[str, Any]) -> None:
        # A stderr, no a stdout: la salida estándar es solo el JSON final.
        gms = {t: round(v["gm"], 4)
               for t, v in entry["tasks"].items()}
        print(f"ronda {entry['round']}: GM por tarea {gms}",
              file=sys.stderr, flush=True)

    try:
        out = run_auto(args.target, runs_dir=args.runs_dir, n_per_task=args.n,
                       brute_steps=args.brute_steps,
                       max_rounds=args.max_rounds,
                       time_budget_seconds=args.time_budget,
                       seed=args.seed, on_round=_show)
    except ValueError as exc:
        json.dump({"error": str(exc)}, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return 2
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

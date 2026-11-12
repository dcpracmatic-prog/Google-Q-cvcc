"""AUTO_MVP v2.3 — el corredor con modelo de lenguaje + prefilter:
solo salen semillas.

Arturo (2026-11-12): meter un modelo de lenguaje GRATIS y BUENO, y
NO construir .kmx en el Notebook: no cabe (todas las iteraciones +
todo el respaldo de las semillas son gigas). Lo que se saca en esta
parte son NADA MÁS LAS SEMILLAS. Y compilar cada mutación en crudo
es un callejón sin salida: primero el prefilter barato, y solo los
sobrevivientes llegan a kickmix.

Cómo funciona:

1. **El modelo es el estratega.** Lee la mejor semilla (un JSON de
   kilobytes) y el historial medido, y propone un LOTE de movimientos
   como JSON chico: qué K probar y con qué semilla
   (`{"deltas": [{"K": 6, "seed": 123, "reason": "..."}, ...]}`).
   Nunca propone compuertas: las pone sa_windows, y la validez la
   impone el verificador oficial.
2. **El prefilter es la puerta.** Ordena el lote en milisegundos
   (proxy + MWIS, `auto_mvp/prefilter.py`): descarta el 99% de la
   basura sin tocar kickmix; solo los 1-2 mejores ganan el paso
   caro. El proxy nunca pone el puntaje: el S que cuenta es el
   MEDIDO con el verificador.
3. **El circuito vive solo en TEMPORAL.** El mejor circuito actual
   se guarda en un directorio temporal durante la corrida; cada
   candidato se materializa ahí, se valida, se mide y se BORRA.
   Al terminar la corrida el temporal se elimina: en `runs/` quedan
   solo las semillas (`runs/seeds/<tarea>/<id>.json`) y el ledger.
   Un .kmx nunca sale del Notebook ni se guarda en `runs/seeds/`.
3. **La semilla es la receta.** Cada mejora guarda su semilla con
   la receta que la reconstruye: para invsqrt, la base
   (`invsqrt_pub`) + (K, seed) del operador. Re-correr el operador
   con los mismos (K, seed) sobre el circuito del padre reproduce
   el circuito (el operador es determinista con su semilla; hay un
   test que lo comprueba). La cadena de padres llega hasta la base.
4. **Sin llave, no se para.** Si no hay llave del modelo, si el
   proveedor limita (429) o si el modelo devuelve un JSON malo, el
   corredor sigue con sa_windows (K rotando). La corrida nunca
   depende del modelo; el modelo solo la guía.

Uso::

    python -m auto_mvp.llm_auto --target-S 90000 --max-proposals 10

La llave va en el entorno (`GEMINI_API_KEY` o `GROQ_API_KEY`; en
Kaggle, como secreto del notebook). Sin llave, corre igual con
sa_windows y lo dice en el ledger (`llm: "sin llave"`).

v2.2 cubre invsqrt de punta a punta. DQI y química tienen su formato
de semilla (`auto_mvp/seed.py`) pero sus materializadores (generador
DQI, entrenador de factorización) están pendientes.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from .circuit import SEED_INVSQRT, fast_verify_invsqrt, propose_sa_windows
from .llm import LLMError, complete_json
from .prefilter import rank_deltas
from .seed import list_seeds, new_seed, save_seed

SEED_S = {"invsqrt": 100568.5}


def _ledger_path(runs_dir: Path) -> Path:
    return runs_dir / "seed_ledger.json"


def _rebuild_best(task: str, best: dict[str, Any], runs_dir: Path,
                    work: Path, sa_budget_s: float) -> dict[str, Any]:
    """Reconstruye el circuito de la mejor semilla desde su cadena.

    Camina de la semilla a su padre hasta la base (`invsqrt_pub`) y
    re-corre el operador con los (K, seed, budget_s) guardados en
    cada receta. Después MIDE el circuito reconstruido: si su S no
    coincide con el S guardado en la semilla (1%), la reconstrucción
    no es fiel (el operador usa presupuesto de TIEMPO: en otra
    máquina puede probar otro número de ventanas) y se vuelve a la
    semilla base, diciéndolo claro. Nunca se trabaja con un circuito
    que no es el de la semilla.
    """
    by_id = {s["id"]: s for s in list_seeds(runs_dir, task)}
    chain: list[dict[str, Any]] = []
    cur = best
    while cur is not None:
        chain.append(cur)
        parent = cur.get("parent")
        cur = by_id.get(parent) if parent else None
    chain.reverse()
    if not chain or chain[0]["recipe"].get("base") != "invsqrt_pub":
        raise RuntimeError("la cadena de la semilla no llega a la base")
    if len(chain) == 1:
        shutil.copyfile(SEED_INVSQRT, work)
        return best
    tmp = work.parent
    current = tmp / "chain_0000.kmx"
    shutil.copyfile(SEED_INVSQRT, current)
    for step_i, step in enumerate(chain[1:], start=1):
        nxt = tmp / f"chain_{step_i:04d}.kmx"
        log = tmp / f"chain_{step_i:04d}.json"
        recipe = step["recipe"]
        prop = propose_sa_windows(
            current, nxt, log, K=int(recipe["K"]),
            budget_s=float(recipe.get("budget_s", sa_budget_s)),
            seed=int(recipe["seed"]))
        if not prop["ok"]:
            raise RuntimeError(
                f"no se pudo reconstruir el paso {step_i} de la cadena "
                f"(semilla {step['id']}): {prop.get('reason', '')}")
        current = nxt
    measure = fast_verify_invsqrt(current, max_x=1024)
    if (not measure["valid"]
            or abs(measure["S"] - float(best["S"])) / float(best["S"]) > 0.01):
        raise RuntimeError(
            "el circuito reconstruido no mide como la semilla "
            f"(S={measure.get('S')} vs guardado {best['S']})")
    shutil.copyfile(current, work)
    return best


def _load_ledger(runs_dir: Path, task: str) -> dict[str, Any]:
    p = _ledger_path(runs_dir)
    if p.is_file():
        try:
            led = json.loads(p.read_text(encoding="utf-8"))
            if led.get("task") == task and led.get("best_seed"):
                return led
        except Exception:
            pass
    return {"task": task, "best_seed": None, "proposals": 0, "valid": 0,
            "invalid": 0, "llm_calls": 0, "llm_fallbacks": 0,
            "rejected": [], "measured": [],
            "prefilter_ranked": 0, "prefilter_discarded": 0,
            "prefilter_winners": 0}


def _save_ledger(runs_dir: Path, led: dict[str, Any]) -> None:
    runs_dir.mkdir(parents=True, exist_ok=True)
    _ledger_path(runs_dir).write_text(
        json.dumps(led, indent=1, ensure_ascii=False), encoding="utf-8")


def _prompt(task: str, best: dict[str, Any],
            history: list[dict[str, Any]], batch_size: int = 5) -> str:
    """El prompt del estratega: la mejor semilla + lo ya probado.

    Pide un LOTE de deltas (no uno solo): el prefilter los ordena en
    milisegundos y solo los mejores ganan el paso caro.
    """
    hist = "\n".join(
        f"- K={h.get('K')}, seed={h.get('seed')}: "
        f"{'S=' + str(h.get('S')) if h.get('valid') else 'inválido/no mejora'}"
        for h in history[-8:])
    return (
        "Eres el estratega de un optimizador de circuitos cuánticos. "
        "Responde SOLO con un JSON, sin texto fuera del JSON.\n\n"
        f"Tarea: {task}. El puntaje S es menor-mejor. La mejor semilla "
        "medida hasta ahora es:\n"
        f"{json.dumps(best, ensure_ascii=False)}\n\n"
        "Lo ya probado (K = tamaño de ventana, seed = azar del operador):\n"
        f"{hist or '- nada todavía'}\n\n"
        f"Propón un LOTE de hasta {int(batch_size)} movimientos distintos "
        "como JSON: "
        '{"deltas": [{"K": 5|6|7, "seed": <entero>, '
        '"reason": "<una frase>"}, ...]}. '
        "Varía K y seed respecto a lo ya probado; si un K ya dio 0 "
        "varias veces, prueba otro. No propongas compuertas ni "
        "circuitos: solo K y seed; el operador construye y el "
        "verificador oficial decide si vale."
    )


def _parse_deltas(obj: dict[str, Any]) -> list[dict[str, Any]]:
    """Un lote de deltas desde lo que devolvió el modelo.

    Acepta {"deltas": [...]}, un solo {"K", "seed"} y una lista
    directa. Cada delta necesita K en {5,6,7} y seed entero.
    """
    if isinstance(obj, dict) and "deltas" in obj:
        raw = obj["deltas"]
    elif isinstance(obj, dict) and "K" in obj:
        raw = [obj]
    elif isinstance(obj, list):
        raw = obj
    else:
        raise ValueError(f"el modelo no devolvió deltas: {str(obj)[:200]}")
    if not isinstance(raw, list) or not raw:
        raise ValueError("el lote de deltas está vacío")
    out = []
    for d in raw:
        K = int(d["K"])
        if K not in (5, 6, 7):
            raise ValueError(f"K={K} fuera de {5, 6, 7}")
        out.append({"K": K, "seed": int(d["seed"]),
                    "reason": str(d.get("reason", ""))[:200]})
    return out


def run_llm_auto(target_S: float, task: str = "invsqrt",
                 runs_dir: str | Path = "runs",
                 max_proposals: int | None = None,
                 time_budget_seconds: float | None = None,
                 sa_budget_s: float = 60.0,
                 llm_client: Callable[[str], dict[str, Any]] | None = None,
                 provider: str | None = None,
                 seed: int = 42,
                 batch_size: int = 5,
                 expensive_per_round: int = 1,
                 prefilter_margin: float = 0.25,
                 on_proposal: Callable[[dict[str, Any]], None] | None = None
                 ) -> dict[str, Any]:
    """Corredor con modelo de lenguaje + prefilter (v2.3); solo salen semillas.

    Por ronda el modelo propone un LOTE de deltas; el prefilter
    (proxy + MWIS) los ordena en milisegundos y solo los
    ``expensive_per_round`` mejores ganan el paso caro (construir +
    medir con kickmix). Devuelve {task, target_S, best_S, best_seed,
    reached, proposals, valid, invalid, llm_calls, llm_fallbacks,
    prefilter_ranked, prefilter_discarded, prefilter_winners,
    runs_dir, stopped}. ``llm_client`` es una función prompt -> dict
    (por defecto, el cliente real de auto_mvp.llm); los tests le pasan
    una falsa.
    """
    if task != "invsqrt":
        raise ValueError(
            f"v2.2 cubre invsqrt; {task} tiene su formato de semilla "
            "pero su materializador está pendiente (DQI: generador; "
            "química: entrenador de factorización)")
    target = float(target_S)
    if not (math.isfinite(target) and target > 0):
        raise ValueError(f"target_S debe ser finito y > 0, got {target_S!r}")
    runs_dir = Path(runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    progress_path = runs_dir / "seed-progress.jsonl"
    started = time.monotonic()
    if llm_client is None:
        def _real(prompt: str) -> dict[str, Any]:
            return complete_json(prompt, provider=provider)
        llm_client = _real

    def _progress(entry: dict[str, Any]) -> None:
        with progress_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(f"[semilla] {entry}", file=sys.stderr, flush=True)
        if on_proposal is not None:
            on_proposal(entry)

    led = _load_ledger(runs_dir, task)
    if led["best_seed"] is None:
        # La semilla base, medida: el punto de partida es un circuito
        # real y válido, con su S medido, no un número supuesto.
        measure = fast_verify_invsqrt(SEED_INVSQRT, max_x=1024)
        if not measure["valid"]:
            raise RuntimeError(
                "la semilla vendida no es válida: "
                f"{measure.get('reason')}")
        best = new_seed(task, measure["S"], measure["qubits"],
                        measure["toffoli_count"],
                        {"base": "invsqrt_pub"},
                        notes="semilla vendida, medida")
        save_seed(best, runs_dir)
        led["best_seed"] = best
        _save_ledger(runs_dir, led)
        _progress({"proposal": 0, "operator": "seed", "S": best["S"],
                   "valid": True, "seed_id": best["id"],
                   "note": "semilla medida, solo sale la semilla"})
    best = led["best_seed"]
    best_S = float(best["S"])
    if best_S <= target:
        return {"task": task, "target_S": target, "best_S": best_S,
                "best_seed": best, "reached": True, "proposals": 0,
                "valid": led["valid"], "invalid": led["invalid"],
                "llm_calls": led["llm_calls"],
                "llm_fallbacks": led["llm_fallbacks"],
                "prefilter_ranked": led.get("prefilter_ranked", 0),
                "prefilter_discarded": led.get("prefilter_discarded", 0),
                "prefilter_winners": led.get("prefilter_winners", 0),
                "runs_dir": str(runs_dir),
                "stopped": "la semilla ya llega a la meta"}

    proposals = 0
    stopped = "límite alcanzado"
    # El historial del estimador: lo medido + lo rechazado (de esta
    # corrida y de las anteriores, vía el ledger).
    history: list[dict[str, Any]] = list(led.get("measured", []))
    history.extend(led.get("rejected", []))
    # El mejor circuito vive SOLO en temporal: se borra al terminar.
    with tempfile.TemporaryDirectory(prefix="llm-auto-") as tmp:
        work = Path(tmp) / "best.kmx"
        try:
            _rebuild_best(task, best, runs_dir, work, float(sa_budget_s))
        except RuntimeError as exc:
            # La semilla derivada no se pudo reconstruir fielmente:
            # se vuelve a la base y se dice claro (fail-closed).
            base = list_seeds(runs_dir, task)
            base = [s for s in base if s.get("parent") is None]
            if not base:
                raise
            best = base[0]
            best_S = float(best["S"])
            led["best_seed"] = best
            _save_ledger(runs_dir, led)
            shutil.copyfile(SEED_INVSQRT, work)
            _progress({"proposal": 0, "operator": "rebuild",
                       "S": best_S, "valid": True, "seed_id": best["id"],
                       "note": f"reconstrucción falló ({exc}); "
                               "se vuelve a la semilla base"})
        # El mejor al arrancar es la base o la derivada reconstruida.
        while True:
            round_no = proposals + 1
            # 1. El estratega propone un LOTE (o sa_windows si no hay
            # modelo). El prefilter ordena el lote en milisegundos y
            # solo los ganadores llegan al paso caro.
            llm_ok = False
            llm_error = ""
            try:
                raw = llm_client(_prompt(task, best, history,
                                         int(batch_size)))
                batch = _parse_deltas(raw)
                llm_ok = True
                led["llm_calls"] += 1
            except (LLMError, ValueError, KeyError, TypeError) as exc:
                llm_error = str(exc)[:200]
                batch = [{"K": (5, 6, 7)[(round_no + j - 1) % 3],
                          "seed": int(seed) + round_no + j,
                          "reason": "sin modelo: sa_windows con K rotando"}
                         for j in range(int(batch_size))]
                led["llm_fallbacks"] += 1
            ranked = rank_deltas(
                batch, task, best_S, best, history,
                margin=float(prefilter_margin),
                top_k=int(expensive_per_round))
            led["prefilter_ranked"] += len(batch)
            led["prefilter_discarded"] += len(ranked["discarded"])
            led["prefilter_winners"] += len(ranked["winners"])
            for d, reason in ranked["discarded"]:
                _progress({"round": round_no, "operator": "prefilter",
                           "K": d.get("K"), "seed": d.get("seed"),
                           "valid": None, "note": "descartado barato: "
                           + str(reason)[:200]})
            winners = ranked["winners"]
            explored = False
            if not winners and ranked["ranked"]:
                # Sin historial el proxy no tiene señal: se explora
                # con el mejor estimado y la medición CREA el
                # historial. Sin esto, la primera ronda rechazaría
                # todo y el corredor se quedaría quieto.
                winners = [ranked["ranked"][0]]
                explored = True
            if not winners:
                _progress({"round": round_no, "operator": "prefilter",
                           "valid": None,
                           "note": "el lote no pasó la puerta: "
                                   "ninguno gana el paso caro"})
            for delta, verdict in winners:
                proposals += 1
                i = proposals
                K = int(delta["K"])
                op_seed = int(delta["seed"])
                reason = str(delta.get("reason", ""))[:200]
                # 2. El operador construye en temporal (se borra).
                cand = Path(tmp) / f"cand_p{i:04d}.kmx"
                log = Path(tmp) / f"cand_p{i:04d}.json"
                prop = propose_sa_windows(work, cand, log, K=K,
                                          budget_s=float(sa_budget_s),
                                          seed=op_seed)
                entry: dict[str, Any] = {
                    "proposal": i, "K": K, "seed": op_seed, "llm": llm_ok,
                    "reason_llm": reason, "operator": "sa_windows",
                    "gain_reported": prop.get("gain", 0),
                    "prefilter_S_est": verdict.s_estimate,
                    "prefilter": ("exploración sin historial"
                                  if explored else "ganador del prefilter")}
                if llm_error:
                    entry["llm_error"] = llm_error
                if not prop["ok"]:
                    entry.update({"valid": False,
                                  "reason": prop.get("reason", ""),
                                  "note": "el operador falló, no es un circuito"})
                    led["invalid"] += 1
                    led["rejected"].append(entry)
                    history.append({**entry, "S": None})
                    _save_ledger(runs_dir, led)
                    _progress(entry)
                else:
                    measure = fast_verify_invsqrt(cand, max_x=1024)
                    entry["valid"] = bool(measure["valid"])
                    if not measure["valid"]:
                        entry["reason"] = measure.get("reason", "")
                        entry["note"] = "INVÁLIDO: no cuenta, no es nada"
                        led["invalid"] += 1
                        led["rejected"].append(entry)
                        history.append({**entry, "S": None})
                        _save_ledger(runs_dir, led)
                        _progress(entry)
                    else:
                        led["valid"] += 1
                        entry["S"] = measure["S"]
                        entry["toffoli_count"] = measure["toffoli_count"]
                        led.setdefault("measured", []).append(
                            {"K": K, "seed": op_seed,
                             "gain_reported": prop.get("gain", 0),
                             "S": measure["S"], "valid": True})
                        if measure["S"] < best_S:
                            # Solo sale la SEMILLA (JSON, kilobytes).
                            new_best = new_seed(
                                task, measure["S"], measure["qubits"],
                                measure["toffoli_count"],
                                {"base": "invsqrt_pub", "K": K,
                                 "seed": op_seed, "gain": prop.get("gain", 0),
                                 "budget_s": float(sa_budget_s)},
                                parent=best["id"],
                                notes=f"propuesta {i} (K={K}, seed={op_seed})")
                            save_seed(new_best, runs_dir)
                            shutil.copyfile(cand, work)
                            best_S = float(measure["S"])
                            best = new_best
                            led["best_seed"] = best
                            entry["seed_id"] = best["id"]
                            entry["note"] = "MEJORA: nueva mejor semilla"
                        else:
                            entry["note"] = "válido pero no mejora"
                        history.append({**entry, "S": entry.get("S")})
                        led["proposals"] = proposals
                        _save_ledger(runs_dir, led)
                        _progress(entry)
                if best_S <= target:
                    stopped = "meta alcanzada"
                    break
                if (max_proposals is not None
                        and proposals >= int(max_proposals)):
                    stopped = f"límite de propuestas ({max_proposals})"
                    break
                if (time_budget_seconds is not None
                        and time.monotonic() - started
                        >= float(time_budget_seconds)):
                    stopped = f"presupuesto de tiempo ({time_budget_seconds}s)"
                    break
            if stopped != "límite alcanzado":
                break
            if (max_proposals is not None
                    and proposals >= int(max_proposals)):
                stopped = f"límite de propuestas ({max_proposals})"
                break
            if (time_budget_seconds is not None
                    and time.monotonic() - started
                    >= float(time_budget_seconds)):
                stopped = f"presupuesto de tiempo ({time_budget_seconds}s)"
                break
            if not winners and not ranked["ranked"]:
                # El lote venía vacío o nada era estimable: no hay
                # nada que probar.
                stopped = "lote vacío"
                break
    led["proposals"] = proposals
    _save_ledger(runs_dir, led)
    return {"task": task, "target_S": target, "best_S": best_S,
            "best_seed": best, "reached": bool(best_S <= target),
            "proposals": proposals, "valid": led["valid"],
            "invalid": led["invalid"], "llm_calls": led["llm_calls"],
            "llm_fallbacks": led["llm_fallbacks"],
            "prefilter_ranked": led.get("prefilter_ranked", 0),
            "prefilter_discarded": led.get("prefilter_discarded", 0),
            "prefilter_winners": led.get("prefilter_winners", 0),
            "runs_dir": str(runs_dir), "stopped": stopped}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Corredor con modelo de lenguaje + prefilter v2.3 "
                    "(invsqrt): el modelo propone un lote, el prefilter "
                    "ordena y solo los mejores ganan el paso caro; "
                    "solo salen semillas.")
    ap.add_argument("--target-S", type=float, required=True,
                    help="el S medido que se quiere (p. ej. 90000)")
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--max-proposals", type=int, default=None)
    ap.add_argument("--time-budget", type=float, default=None,
                    help="segundos; si no, hasta llegar o cancelar")
    ap.add_argument("--sa-budget-s", type=float, default=60.0)
    ap.add_argument("--provider", default=None,
                    help="gemini (por defecto) o groq")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--batch-size", type=int, default=5,
                    help="deltas por lote que propone el modelo")
    ap.add_argument("--expensive-per-round", type=int, default=1,
                    help="ganadores del prefilter que llegan a kickmix")
    ap.add_argument("--prefilter-margin", type=float, default=0.25,
                    help="margen calibrado del proxy (def. 0.25)")
    args = ap.parse_args(argv)
    res = run_llm_auto(
        args.target_S, runs_dir=args.runs_dir,
        max_proposals=args.max_proposals,
        time_budget_seconds=args.time_budget,
        sa_budget_s=args.sa_budget_s, provider=args.provider,
        seed=args.seed, batch_size=args.batch_size,
        expensive_per_round=args.expensive_per_round,
        prefilter_margin=args.prefilter_margin)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0 if res["reached"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

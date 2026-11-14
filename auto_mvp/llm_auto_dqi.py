"""AUTO_MVP v2.16 — el corredor LLM para DQI (el estratega optimiza el
generador híbrido DURANTE la ejecución).

Arturo (2026-11-14): el LLM se metió para que optimice durante la
ejecución. Hasta v2.15 el corredor (`llm_auto.py`) solo cubría
invsqrt porque el materializador DQI estaba pendiente; ahora que
existe `build_hybrid_bm.py`, el LLM ya puede correr para DQI.

Cómo funciona (igual que invsqrt, pero con el generador híbrido):

1. **El modelo es el estratega.** Lee los mejores knobs medidos
   (batch, nslot, toom3) con su Q/T/S y el historial, y propone un
   LOTE de deltas como JSON chico:
   `{"deltas": [{"batch": 17, "nslot": 36, "toom3": true,
   "seed": 123, "reason": "..."}, ...]}`.
   Nunca propone compuertas: las pone el generador verificado
   (`build_hybrid_bm.py`) y la validez la impone la verificación
   a escala chica (`verify_small`). Así el modelo no puede inventar
   un circuito inválido.
2. **El materializador es el generador.** Cada delta se materializa
   con `build_hybrid_bm_circuit(n, m, batch, nslot, toom3)` y se
   mide Q/T (conteo estático) y S proyectado = R * Q^2 * T
   (R = 1.1912605, medido en el DQI de referencia a 102,400 shots).
   Solo el mejor (menor S) sobrevive.
3. **La semilla es la receta.** Cada mejora guarda sus knobs
   (batch, nslot, toom3) + Q/T/S: re-correr el generador con los
   mismos knobs reproduce el circuito (el generador es
   determinista). No se guarda ningún .kmb/.kmx.
4. **Sin llave, no se para.** Si no hay llave del modelo, si el
   proveedor limita (429) o si el modelo devuelve un JSON malo, el
   corredor sigue con deltas por defecto (batch/nslot rotando,
   toom3 alternando). La corrida nunca depende del modelo; el
   modelo solo la guía.

Uso::

    python -m auto_mvp.llm_auto_dqi --target-S 1e13 --max-proposals 6

La llave va en el entorno (`GEMINI_API_KEY` o `GROQ_API_KEY`; en
Kaggle, como secreto del notebook). Sin llave, corre igual con los
deltas por defecto y lo dice en el resultado (`llm_fallbacks`).

Los knobs que mueve el LLM (deltas DQI):
  batch: tamaño del lote Montgomery (T; más grande = menos
    inversiones, más multiplicaciones por lote).
  nslot: slots C/B (Q; debe ser >= Lmax+1 = n//2+1).
  toom3: True usa el multiplicador Toom-3 (45 T/mult) en vez del
    nativo (63 T/mult); False usa el nativo.
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Callable

from .circuits.generators.build_hybrid_bm import (
    build_hybrid_bm_circuit, verify_small)
from .llm import LLMError, complete_json

# R(ε+) medido en el DQI de referencia a 102,400 shots (kernel
# 144307906); es el R del S comparable. El S que cuenta es el
# proyectado con este R (la verificación oficial es el paso caro).
R_DQI = 1.1912605

# Deltas por defecto (sin modelo): batch y nslot rotando, toom3
# alternando. Son los knobs que el LLM movería.
_DEFAULT_BATCH = (4, 8, 17, 36)
_DEFAULT_NSLOT_EXTRA = (0, 2, 6)


def dqi_S(qubits: int, toffoli_like: int) -> float:
    """S proyectado del DQI: R * Q^2 * T (menor es mejor)."""
    return float(R_DQI) * float(qubits) ** 2 * float(toffoli_like)


def _prompt(best: dict[str, Any], history: list[dict[str, Any]],
            n: int, m: int, batch_size: int = 5) -> str:
    """El prompt del estratega DQI: los mejores knobs + lo ya probado."""
    hist = "\n".join(
        f"- batch={h.get('batch')}, nslot={h.get('nslot')}, "
        f"toom3={h.get('toom3')}: "
        f"{'S=' + str(h.get('S')) if h.get('valid') else 'inválido/no mejora'}"
        for h in history[-8:])
    return (
        "Eres el estratega de un optimizador de circuitos cuánticos "
        "(decodificador DQI híbrido). Responde SOLO con un JSON, sin "
        "texto fuera del JSON.\n\n"
        f"Tarea: dqi (n={n}, m={m}). El puntaje S es menor-mejor "
        "(S = R * Q^2 * T, R=1.1912605). Los mejores knobs medidos "
        "hasta ahora son:\n"
        f"{json.dumps(best, ensure_ascii=False)}\n\n"
        "Lo ya probado (batch = lote Montgomery, nslot = slots C/B, "
        "toom3 = multiplicador Toom-3 45T vs nativo 63T):\n"
        f"{hist or '- nada todavía'}\n\n"
        f"Propón un LOTE de hasta {int(batch_size)} movimientos "
        "distintos como JSON: "
        '{"deltas": [{"batch": 4|8|17|36, "nslot": <entero>, '
        '"toom3": true|false, "seed": <entero>, '
        '"reason": "<una frase>"}, ...]}. '
        "Varía batch, nslot y toom3 respecto a lo ya probado; "
        "nslot debe ser >= n//2+1 (si no, el circuito no cabe). "
        "No propongas compuertas ni circuitos: solo los knobs; el "
        "generador construye y la verificación decide si vale."
    )


def _parse_deltas(obj: dict[str, Any], min_nslot: int
                  ) -> list[dict[str, Any]]:
    """Un lote de deltas DQI desde lo que devolvió el modelo."""
    if isinstance(obj, dict) and "deltas" in obj:
        raw = obj["deltas"]
    elif isinstance(obj, dict) and "batch" in obj:
        raw = [obj]
    elif isinstance(obj, list):
        raw = obj
    else:
        raise ValueError(f"el modelo no devolvió deltas: {str(obj)[:200]}")
    if not isinstance(raw, list) or not raw:
        raise ValueError("el lote de deltas está vacío")
    out = []
    for d in raw:
        batch = int(d["batch"])
        if batch < 1 or batch > 64:
            raise ValueError(f"batch={batch} fuera de 1..64")
        nslot = int(d["nslot"])
        if nslot < int(min_nslot):
            raise ValueError(
                f"nslot={nslot} < mínimo {min_nslot} (n//2+1)")
        toom3 = bool(d.get("toom3", False))
        out.append({"batch": batch, "nslot": nslot, "toom3": toom3,
                    "seed": int(d.get("seed", 0)),
                    "reason": str(d.get("reason", ""))[:200]})
    return out


def _default_batch(round_no: int, min_nslot: int, batch_size: int,
                   seed: int) -> list[dict[str, Any]]:
    """Deltas por defecto (sin modelo): batch/nslot rotando, toom3
    alternando."""
    out = []
    for j in range(int(batch_size)):
        k = round_no + j
        out.append({
            "batch": _DEFAULT_BATCH[k % len(_DEFAULT_BATCH)],
            "nslot": int(min_nslot) + _DEFAULT_NSLOT_EXTRA[
                k % len(_DEFAULT_NSLOT_EXTRA)],
            "toom3": bool(k % 2 == 0),
            "seed": int(seed) + k,
            "reason": "sin modelo: knobs por defecto rotando",
        })
    return out


def _measure_knobs(n: int, m: int, batch: int, nslot: int, toom3: bool,
                   verify: bool) -> dict[str, Any]:
    """Materializa el DQI con esos knobs y mide Q/T/S.

    Si `verify` es True, corre `verify_small` a esta escala para
    confirmar que el circuito es válido (sigma correcto y scan
    limpio) antes de aceptar el S.
    """
    circ, info = build_hybrid_bm_circuit(
        n=n, m=m, batch=batch, nslot=nslot, toom3=toom3)
    q = int(info["qubits"])
    t = int(info["toffoli_like"])
    entry: dict[str, Any] = {
        "batch": int(batch), "nslot": int(nslot), "toom3": bool(toom3),
        "qubits": q, "toffoli_like": t, "S": dqi_S(q, t),
        "instructions": int(info["instructions"]),
    }
    if verify:
        res = verify_small(n=n, m=m, batch=batch, seed=12345,
                           nshots=4, toom3=toom3)
        ok = (res["bm_sigma_correct"] == res["bm_sigma_total"]
              and res["scan_registers_intact"]
              == res["scan_registers_total"])
        entry["valid"] = bool(ok)
        entry["verify"] = {
            "bm_sigma": f"{res['bm_sigma_correct']}/"
                        f"{res['bm_sigma_total']}",
            "scan": f"{res['scan_registers_intact']}/"
                    f"{res['scan_registers_total']}",
        }
        if not ok:
            entry["reason"] = "verify_small falló (sigma o scan)"
    else:
        entry["valid"] = True
    return entry


def run_llm_auto_dqi(target_S: float, n: int = 70, m: int = 4095,
                     max_proposals: int | None = None,
                     time_budget_seconds: float | None = None,
                     llm_client: Callable[[str], dict[str, Any]] | None = None,
                     provider: str | None = None,
                     seed: int = 42, batch_size: int = 5,
                     verify: bool = True,
                     base_batch: int = 17, base_nslot: int | None = None,
                     base_toom3: bool = False,
                     on_proposal: Callable[[dict[str, Any]], None] | None = None
                     ) -> dict[str, Any]:
    """Corredor LLM para DQI: el estratega mueve los knobs del
    generador híbrido durante la ejecución y solo sobrevive el menor S.

    Devuelve {task, target_S, best_S, best_knobs, reached, proposals,
    valid, invalid, llm_calls, llm_fallbacks}. `llm_client` es una
    función prompt -> dict (por defecto, el cliente real de
    auto_mvp.llm); los tests le pasan una falsa.
    """
    target = float(target_S)
    if not (math.isfinite(target) and target > 0):
        raise ValueError(f"target_S debe ser finito y > 0, got {target_S!r}")
    if n < 2 or m < 1:
        raise ValueError(f"n={n}, m={m} inválidos")
    min_nslot = (n // 2) + 1
    if base_nslot is None:
        base_nslot = min_nslot
    if base_nslot < min_nslot:
        raise ValueError(f"base_nslot={base_nslot} < mínimo {min_nslot}")
    if llm_client is None:
        def _real(prompt: str) -> dict[str, Any]:
            return complete_json(prompt, provider=provider)
        llm_client = _real

    def _progress(entry: dict[str, Any]) -> None:
        print(f"[dqi-llm] {entry}", file=sys.stderr, flush=True)
        if on_proposal is not None:
            on_proposal(entry)

    started = time.monotonic()
    # La base, medida: el punto de partida es un circuito real con
    # su Q/T/S medidos, no un número supuesto.
    best = _measure_knobs(n, m, base_batch, base_nslot, base_toom3,
                          verify=verify)
    if not best["valid"]:
        raise RuntimeError(
            "la base DQI no es válida: "
            f"{best.get('reason', '')}")
    best_S = float(best["S"])
    _progress({"proposal": 0, "operator": "base", "S": best_S,
               "valid": True, "knobs": {k: best[k] for k in
                                        ("batch", "nslot", "toom3")},
               "note": "base medida"})
    if best_S <= target:
        return {"task": "dqi", "target_S": target, "best_S": best_S,
                "best_knobs": best, "reached": True, "proposals": 0,
                "valid": 1, "invalid": 0, "llm_calls": 0,
                "llm_fallbacks": 0, "stopped": "la base ya llega"}

    history: list[dict[str, Any]] = [dict(best)]
    proposals = 0
    valid = 1
    invalid = 0
    llm_calls = 0
    llm_fallbacks = 0
    stopped = "límite alcanzado"
    while True:
        round_no = proposals + 1
        # 1. El estratega propone un LOTE (o los knobs por defecto
        # si no hay modelo). Cada delta se materializa y se mide.
        llm_ok = False
        llm_error = ""
        try:
            raw = llm_client(_prompt(best, history, n, m,
                                     int(batch_size)))
            batch = _parse_deltas(raw, min_nslot)
            llm_ok = True
            llm_calls += 1
        except (LLMError, ValueError, KeyError, TypeError) as exc:
            llm_error = str(exc)[:200]
            batch = _default_batch(round_no, min_nslot, batch_size, seed)
            llm_fallbacks += 1
        for delta in batch:
            proposals += 1
            i = proposals
            entry = _measure_knobs(
                n, m, delta["batch"], delta["nslot"], delta["toom3"],
                verify=verify)
            entry.update({"proposal": i, "llm": llm_ok,
                          "reason_llm": delta.get("reason", "")})
            if llm_error:
                entry["llm_error"] = llm_error
            if not entry["valid"]:
                invalid += 1
                entry["note"] = "INVÁLIDO: no cuenta, no es nada"
                history.append(entry)
                _progress(entry)
            else:
                valid += 1
                if entry["S"] < best_S:
                    best_S = float(entry["S"])
                    best = dict(entry)
                    entry["note"] = "MEJORA: nuevos mejores knobs"
                else:
                    entry["note"] = "válido pero no mejora"
                history.append(entry)
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
    return {"task": "dqi", "target_S": target, "best_S": best_S,
            "best_knobs": best, "reached": bool(best_S <= target),
            "proposals": proposals, "valid": valid, "invalid": invalid,
            "llm_calls": llm_calls, "llm_fallbacks": llm_fallbacks,
            "stopped": stopped}


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m auto_mvp.llm_auto_dqi --target-S 1e13."""
    ap = argparse.ArgumentParser(
        description="Corredor LLM para DQI (el estratega mueve los "
                    "knobs del generador híbrido).")
    ap.add_argument("--target-S", type=float, required=True)
    ap.add_argument("--n", type=int, default=70)
    ap.add_argument("--m", type=int, default=4095)
    ap.add_argument("--max-proposals", type=int, default=None)
    ap.add_argument("--time-budget-s", type=float, default=None)
    ap.add_argument("--provider", type=str, default=None)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--batch-size", type=int, default=5)
    ap.add_argument("--no-verify", action="store_true",
                    help="no correr verify_small por delta")
    ap.add_argument("--base-batch", type=int, default=17)
    ap.add_argument("--base-nslot", type=int, default=None)
    ap.add_argument("--base-toom3", action="store_true")
    args = ap.parse_args(argv)
    res = run_llm_auto_dqi(
        args.target_S, n=args.n, m=args.m,
        max_proposals=args.max_proposals,
        time_budget_seconds=args.time_budget_s,
        provider=args.provider, seed=args.seed,
        batch_size=args.batch_size, verify=not args.no_verify,
        base_batch=args.base_batch, base_nslot=args.base_nslot,
        base_toom3=args.base_toom3)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res["reached"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

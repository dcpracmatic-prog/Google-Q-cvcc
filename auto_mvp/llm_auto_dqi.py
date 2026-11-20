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
3. **La semilla es la receta Y el archivo.** Cada mejora guarda sus
   knobs (batch, nslot, toom3) + Q/T/S, y al final el corredor
   guarda la mejor semilla como archivo: `mejor_semilla.kmb`
   (el circuito real, formato binario) + `mejor_semilla.json`
   (la receta completa: versión y commit del repo, knobs, Q/T/S,
   verificación y SHA256 del .kmb). Re-correr el generador con los
   mismos knobs reproduce el circuito (el generador es
   determinista); `reproducir_semilla` lo comprueba comparando el
   SHA256. Sin el .kmb y la receta, la semilla no es transparente:
   no se puede reproducir ni evaluar. Por eso se guarda.
4. **Sin llave, no se para.** Si no hay modelo, si el modelo
   devuelve un JSON malo, el corredor sigue con deltas por defecto
   (batch/nslot rotando, toom3 alternando). La corrida nunca depende
   del modelo; el modelo solo la guía.

Uso::

    python -m auto_mvp.llm_auto_dqi --target-S 1e13 --max-proposals 6

La llave NO existe: el único LLM es Qwen Code 1.5
(Qwen2.5-Coder-1.5B-Instruct, GGUF Q4_K_M, llama-cpp-python, temp 0.7),
local en la máquina, sin API. No se usan Gemini ni Groq. Si el modelo no está disponible (falta el GGUF o
llama-cpp-python), el corredor sigue con los deltas por defecto y
lo dice en el resultado (`llm_fallbacks`). El GGUF (~1 GB) no va en
el repo: se baja de HuggingFace la primera vez (`LLM_MODEL_PATH` o
`~/workspace/models/`; en Kaggle, `/kaggle/working/`).

Los knobs que mueve el LLM (deltas DQI):
  batch: tamaño del lote Montgomery (T; más grande = menos
    inversiones, más multiplicaciones por lote).
  nslot: slots C/B (Q; debe ser >= Lmax+1 = n//2+1).
  toom3: True usa el multiplicador Toom-3 (45 T/mult) en vez del
    nativo (63 T/mult); False usa el nativo.
"""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .circuits.generators.build_hybrid_bm import (
    build_hybrid_bm_circuit, verify_small)
from .llm import LLMError, complete_json

# R(ε+) medido en el DQI de referencia a 102,400 shots (kernel
# 144307906); es el R del S comparable. El S que cuenta es el
# proyectado con este R (la verificación oficial es el paso caro).
R_DQI = 1.1912605

# Deltas por defecto (sin modelo): batch y nslot rotando, toom3
# alternando. Son los knobs que el LLM movería.
# AUDITORÍA v2.17.6: antes era (4, 8, 17, 36) y el LLM solo podía
# proponer esos batch. A n=10, m=15 el mejor batch ES 4 (la base),
# así que NUNCA había mejora. Medido: batch=1 da S=3.9983e10
# (9.5% mejor que la base 4.418e10) porque Q baja de 1139 a 1067
# y Q^2 domina S = R*Q^2*T. Se añaden 1, 2, 3 para que el
# optimizador pueda encontrarlos.
# v2.17.9: el scan usa siempre inversos directos (Montgomery
# desactivado por fase), así que `batch` YA NO cambia Q/T/S: todos
# los batch dan Q=1067, T=29481, S=3.9983e10 a n=10.
# v2.17.16: T 29481 -> 33051, S 3.9983e10 -> 4.4825e10 (el arreglo
# limpia hist_mult e is_zero de forma unitaria antes de liberarlos).
_DEFAULT_BATCH = (1, 2, 3, 4, 8, 17, 36)
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
        '{"deltas": [{"batch": 1..64, "nslot": <entero>, '
        '"toom3": true|false, "seed": <entero>, '
        '"reason": "<una frase>"}, ...]}. '
        "Varía batch, nslot y toom3 respecto a lo ya probado; "
        "nslot debe ser >= n//2+1 (si no, el circuito no cabe). "
        "Pista medida: S = R*Q^2*T y Q^2 domina; a escala chica "
        "un batch PEQUEÑO (1, 2, 3) baja Q y baja S aunque T suba "
        "un poco; nslot mínimo suele ser lo mejor (más nslot = "
        "más qubits, S sube). "
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

    Si `verify` es True, exige que `verify_small` confirme sigma,
    preservación de registros y fase DQI por shot antes de aceptar el S.
    Esta comprobación es un filtro pequeño, no la certificación oficial.
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
        # Ocho shots pequeños detectan fallos de fase que antes quedaban
        # ocultos porque verify_small solo comprobaba sigma/C/O.
        res = verify_small(n=n, m=m, batch=batch, seed=12345,
                           nshots=8, toom3=toom3)
        ok = bool(res.get("valid", False))
        entry["valid"] = ok
        entry["verify"] = {
            "bm_sigma": f"{res['bm_sigma_correct']}/"
                        f"{res['bm_sigma_total']}",
            "scan": f"{res['scan_registers_intact']}/"
                    f"{res['scan_registers_total']}",
            "phase": f"{res['scan_phase_correct']}/"
                     f"{res['scan_phase_total']}",
        }
        if not ok:
            entry["reason"] = (
                "verify_small falló: sigma, registros o fase DQI "
                f"({res.get('scan_phase_errors', '?')} errores de fase)"
            )
    else:
        # Sin verificación no puede aprobarse ni promoverse un candidato.
        entry["valid"] = False
        entry["verified"] = False
        entry["reason"] = "verificación desactivada: candidato no promovible"
    return entry


def _repo_commit() -> str | None:
    """El commit del repo (si es un clon git); None si no se puede."""
    try:
        repo = Path(__file__).resolve().parent.parent
        r = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                           capture_output=True, text=True, timeout=30)
        sha = r.stdout.strip()
        return sha if r.returncode == 0 and sha else None
    except Exception:
        return None


def save_best_seed(n: int, m: int, best: dict[str, Any],
                   output_dir: str | Path) -> dict[str, Any]:
    """Guarda la mejor semilla como archivo, para reproducir y evaluar.

    Reconstruye el circuito con los knobs de `best` (el generador es
    determinista: los mismos knobs dan el mismo circuito) y escribe:
      - `mejor_semilla.kmb`: el circuito real (formato binario kickmix).
      - `mejor_semilla.json`: la receta completa (versión y commit del
        repo, knobs, Q/T/S, verificación y SHA256 del .kmb).

    Devuelve la receta (el contenido de mejor_semilla.json). Sin el
    .kmb y la receta, la semilla no es transparente: no se puede
    reproducir ni evaluar. Por eso se guarda.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    circ, info = build_hybrid_bm_circuit(
        n=n, m=m, batch=int(best["batch"]), nslot=int(best["nslot"]),
        toom3=bool(best["toom3"]))
    kmb = out / "mejor_semilla.kmb"
    circ.to_file(str(kmb), format="kmb")
    sha = hashlib.sha256(kmb.read_bytes()).hexdigest()
    recipe: dict[str, Any] = {
        "repo_version": __version__,
        "repo_commit": _repo_commit(),
        "generador": "auto_mvp.circuits.generators.build_hybrid_bm.build_hybrid_bm_circuit",
        "n": int(n), "m": int(m),
        "batch": int(best["batch"]), "nslot": int(best["nslot"]),
        "toom3": bool(best["toom3"]),
        "qubits": int(info["qubits"]),
        "toffoli_like": int(info["toffoli_like"]),
        "instructions": int(info["instructions"]),
        "S": float(best["S"]),
        "verify": best.get("verify"),
        "kmb": "mejor_semilla.kmb",
        "kmb_sha256": sha,
        "reproducir": ("python -m auto_mvp.llm_auto_dqi --reproducir "
                       "mejor_semilla.json"),
    }
    (out / "mejor_semilla.json").write_text(
        json.dumps(recipe, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return recipe


def reproducir_semilla(recipe_path: str | Path,
                       output_dir: str | Path | None = None
                       ) -> dict[str, Any]:
    """Reconstruye una semilla desde su receta y comprueba que es la misma.

    Lee `mejor_semilla.json`, reconstruye el circuito con los knobs
    guardados y compara el SHA256 con el del .kmb guardado. Devuelve
    {coincide, sha256, esperado, ...}. Si `output_dir` se da, escribe
    el circuito reconstruido como `mejor_semilla_reconstruida.kmb`.
    Levanta ValueError si la receta no trae los knobs.
    """
    recipe = json.loads(Path(recipe_path).read_text(encoding="utf-8"))
    for k in ("n", "m", "batch", "nslot", "toom3", "kmb_sha256"):
        if k not in recipe:
            raise ValueError(f"la receta no trae {k!r}")
    circ, info = build_hybrid_bm_circuit(
        n=int(recipe["n"]), m=int(recipe["m"]),
        batch=int(recipe["batch"]), nslot=int(recipe["nslot"]),
        toom3=bool(recipe["toom3"]))
    if output_dir is not None:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        circ.to_file(str(out / "mejor_semilla_reconstruida.kmb"),
                     format="kmb")
    # El SHA256 del circuito reconstruido: se escribe a un temporal
    # y se hashea (to_file es el mismo camino que save_best_seed).
    tmp = Path(recipe_path).resolve().parent / ".reproducir_tmp.kmb"
    circ.to_file(str(tmp), format="kmb")
    sha = hashlib.sha256(tmp.read_bytes()).hexdigest()
    tmp.unlink(missing_ok=True)
    return {
        "coincide": sha == recipe["kmb_sha256"],
        "sha256": sha,
        "esperado": recipe["kmb_sha256"],
        "qubits": int(info["qubits"]),
        "toffoli_like": int(info["toffoli_like"]),
        "S": float(recipe["S"]),
    }


def run_llm_auto_dqi(target_S: float, n: int = 70, m: int = 4095,
                     max_proposals: int | None = None,
                     time_budget_seconds: float | None = None,
                     llm_client: Callable[[str], dict[str, Any]] | None = None,
                     seed: int = 42, batch_size: int = 5,
                     verify: bool = True,
                     base_batch: int = 17, base_nslot: int | None = None,
                     base_toom3: bool = False,
                     on_proposal: Callable[[dict[str, Any]], None] | None = None,
                     output_dir: str | Path | None = None
                     ) -> dict[str, Any]:
    """Corredor LLM para DQI: el estratega mueve los knobs del
    generador híbrido durante la ejecución y solo sobrevive el menor S.

    Devuelve {task, target_S, best_S, best_knobs, reached, proposals,
    valid, invalid, llm_calls, llm_fallbacks}. `llm_client` es una
    función prompt -> dict (por defecto, el cliente real de
    auto_mvp.llm); los tests le pasan una falsa. Si `output_dir` se
    da, al final guarda la mejor semilla (`mejor_semilla.kmb` +
    `mejor_semilla.json`, con la receta y el SHA256) para que sea
    transparente: reproducible y evaluable.
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
            return complete_json(prompt)
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
        res = {"task": "dqi", "target_S": target, "best_S": best_S,
               "best_knobs": best, "reached": True, "proposals": 0,
               "valid": 1, "invalid": 0, "llm_calls": 0,
               "llm_fallbacks": 0, "stopped": "la base ya llega"}
        if output_dir is not None:
            res["semilla"] = save_best_seed(n, m, best, output_dir)
        return res

    history: list[dict[str, Any]] = [dict(best)]
    proposals = 0
    valid = 1
    invalid = 0
    llm_calls = 0
    llm_fallbacks = 0
    stopped = "límite alcanzado"
    # BARRIDO SISTEMÁTICO (v2.17.6, auditoría): antes de preguntar
    # al LLM, medir los batch pequeños con nslot mínimo. El LLM
    # (1.5B) sube nslot cuando varía batch y nunca prueba batch=1,
    # 2, 3 con nslot mínimo, que es donde está la mejora (medido
    # a n=10, m=15: batch=1, nslot=6 da S=3.998e10, 9.5% mejor que
    # la base 4.418e10; el LLM propuso batch=1 con nslot=7..13 y
    # todos salieron peores). Es fuerza bruta sobre circuitos: se
    # mide el circuito real, no un número supuesto. Respeta el
    # límite de propuestas y el presupuesto de tiempo.
    for _b in (1, 2, 3):
        if _b == base_batch:
            continue
        if (max_proposals is not None
                and proposals >= int(max_proposals)):
            stopped = f"límite de propuestas ({max_proposals})"
            break
        if (time_budget_seconds is not None
                and time.monotonic() - started
                >= float(time_budget_seconds)):
            stopped = f"presupuesto de tiempo ({time_budget_seconds}s)"
            break
        proposals += 1
        _entry = _measure_knobs(n, m, _b, min_nslot, base_toom3,
                                verify=verify)
        _entry.update({"proposal": proposals, "llm": False,
                       "reason_llm": "barrido sistemático: batch "
                       "pequeño, nslot mínimo"})
        if not _entry["valid"]:
            invalid += 1
            _entry["note"] = "INVÁLIDO: no cuenta, no es nada"
        else:
            valid += 1
            if _entry["S"] < best_S:
                best_S = float(_entry["S"])
                best = dict(_entry)
                _entry["note"] = "MEJORA: nuevos mejores knobs"
            else:
                _entry["note"] = "válido pero no mejora"
        history.append(_entry)
        _progress(_entry)
        if best_S <= target:
            stopped = "meta alcanzada"
            break
    while stopped == "límite alcanzado":
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
    res = {"task": "dqi", "target_S": target, "best_S": best_S,
           "best_knobs": best, "reached": bool(best_S <= target),
           "proposals": proposals, "valid": valid, "invalid": invalid,
           "llm_calls": llm_calls, "llm_fallbacks": llm_fallbacks,
           "stopped": stopped}
    if output_dir is not None:
        res["semilla"] = save_best_seed(n, m, best, output_dir)
    return res


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m auto_mvp.llm_auto_dqi --target-S 1e13.

    --reproducir <mejor_semilla.json> reconstruye la semilla desde
    su receta y comprueba que el SHA256 coincide (la semilla es
    reproducible). No corre el corredor.
    """
    ap = argparse.ArgumentParser(
        description="Corredor LLM para DQI (el estratega mueve los "
                    "knobs del generador híbrido).")
    ap.add_argument("--target-S", type=float, default=None)
    ap.add_argument("--n", type=int, default=70)
    ap.add_argument("--m", type=int, default=4095)
    ap.add_argument("--max-proposals", type=int, default=None)
    ap.add_argument("--time-budget-s", type=float, default=None)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--batch-size", type=int, default=5)
    ap.add_argument("--no-verify", action="store_true",
                    help="no correr verify_small por delta")
    ap.add_argument("--base-batch", type=int, default=17)
    ap.add_argument("--base-nslot", type=int, default=None)
    ap.add_argument("--base-toom3", action="store_true")
    ap.add_argument("--output-dir", type=str, default=None,
                    help="donde guardar la mejor semilla "
                         "(mejor_semilla.kmb + mejor_semilla.json)")
    ap.add_argument("--reproducir", type=str, default=None,
                    help="receta (mejor_semilla.json) a reproducir "
                         "y verificar por SHA256")
    args = ap.parse_args(argv)
    if args.reproducir is not None:
        res = reproducir_semilla(args.reproducir,
                                 output_dir=args.output_dir)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["coincide"] else 1
    if args.target_S is None:
        ap.error("--target-S es obligatorio (salvo --reproducir)")
    res = run_llm_auto_dqi(
        args.target_S, n=args.n, m=args.m,
        max_proposals=args.max_proposals,
        time_budget_seconds=args.time_budget_s,
        seed=args.seed,
        batch_size=args.batch_size, verify=not args.no_verify,
        base_batch=args.base_batch, base_nslot=args.base_nslot,
        base_toom3=args.base_toom3,
        output_dir=args.output_dir)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res["reached"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

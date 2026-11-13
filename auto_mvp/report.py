"""AUTO_MVP v2.5 — el REPORTE: resultados con estructura y valor
cualitativo y cuantitativo.

La herramienta producía semillas y un ledger JSON, pero nadie veía
qué pasó en una corrida sin leer el JSON a mano. Este módulo lee el
ledger de una corrida (`runs/seed_ledger.json`) y produce un reporte
estructurado: lo cuantitativo (propuestas, válidas, inválidas, mejor
S medido, ganancia del operador, limpieza del peephole, descarte
del prefilter, llamadas al modelo) y lo cualitativo (un comentario
en simple, generado por REGLAS a partir de los números — no por un
modelo — que dice qué hizo cada operador, por qué se rechazó cada
propuesta y qué queda pendiente).

El comentario es determinista: los mismos números dan el mismo
texto. Si los números cambian, el texto cambia. Nada de prosa
inventada.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _read_ledger(runs_dir: str | Path) -> dict[str, Any]:
    p = Path(runs_dir) / "seed_ledger.json"
    if not p.is_file():
        raise FileNotFoundError(f"no hay ledger en {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def build_report(runs_dir: str | Path) -> dict[str, Any]:
    """El reporte estructurado de una corrida, desde su ledger."""
    led = _read_ledger(runs_dir)
    measured: list[dict[str, Any]] = list(led.get("measured", []))
    rejected: list[dict[str, Any]] = list(led.get("rejected", []))
    best = led.get("best_seed") or {}
    best_s = best.get("S")
    measured_s = [m["S"] for m in measured if m.get("S") is not None]
    run_best = min(measured_s) if measured_s else None
    # El peephole y la fusión de rotaciones se reportan por propuesta
    # en el progreso (seed-progress.jsonl): el ledger solo guarda un
    # resumen de las medidas sin esos detalles. Se suma una vez por
    # número de propuesta.
    peephole_removed = 0
    peephole_pairs = 0
    rotation_merged = 0
    rotation_removed = 0
    seen: set[Any] = set()
    prog_path = Path(runs_dir) / "seed-progress.jsonl"
    if prog_path.is_file():
        for line in prog_path.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except Exception:
                continue
            pid = e.get("proposal")
            if pid is None or pid in seen:
                continue
            seen.add(pid)
            ph = e.get("peephole") or {}
            peephole_removed += int(ph.get("removed", 0))
            peephole_pairs += int(ph.get("pairs_cancelled", 0))
            rm = e.get("rotation_merge") or {}
            rotation_merged += int(rm.get("merged", 0))
            rotation_removed += int(rm.get("removed", 0))
    if not seen:
        for e in rejected + measured:
            ph = e.get("peephole") or {}
            peephole_removed += int(ph.get("removed", 0))
            peephole_pairs += int(ph.get("pairs_cancelled", 0))
            rm = e.get("rotation_merge") or {}
            rotation_merged += int(rm.get("merged", 0))
            rotation_removed += int(rm.get("removed", 0))
    gains = [m.get("gain_reported", 0) for m in measured]
    proposals = int(led.get("proposals", 0))
    valid = int(led.get("valid", 0))
    invalid = int(led.get("invalid", 0))
    # Lo cualitativo, por reglas sobre los números.
    comments: list[str] = []
    if proposals == 0:
        comments.append("La corrida no propuso nada: no hay nada que medir.")
    else:
        if valid == 0:
            comments.append(
                f"Se propusieron {proposals} circuitos y NINGUNO fue "
                "válido: el operador no produjo un circuito que cuente.")
        elif run_best is not None and best_s is not None \
                and run_best < float(best_s):
            comments.append(
                f"Hay mejora: el mejor S medido en la corrida "
                f"({run_best}) está por debajo del mejor guardado "
                f"({best_s}).")
        else:
            comments.append(
                "Ninguna propuesta mejoró la mejor semilla: la base "
                "sigue siendo óptima para las ventanas probadas "
                "(ganancia del operador 0 en todas).")
        if gains and max(gains) == 0:
            comments.append(
                "El operador sa_windows no encontró ganancia en "
                "ninguna ventana: la semilla ya es óptima para esos K.")
        if peephole_removed:
            comments.append(
                f"El peephole quitó {peephole_removed} compuertas "
                f"Clifford ({peephole_pairs} pares) sin tocar el S: "
                "limpieza, no mejora de puntuación.")
        if rotation_merged:
            comments.append(
                f"La fusión de rotaciones juntó {rotation_merged} "
                f"rotaciones ({rotation_removed} eliminadas).")
        ranked = int(led.get("prefilter_ranked", 0))
        discarded = int(led.get("prefilter_discarded", 0))
        if ranked:
            comments.append(
                f"El prefilter ordenó {ranked} deltas y descartó "
                f"{discarded} baratos antes del paso caro.")
        if int(led.get("llm_fallbacks", 0)):
            comments.append(
                "El modelo de lenguaje no propuso (sin llave o con "
                "error) y el corredor usó el respaldo sa_windows.")
    return {
        "task": led.get("task"),
        "best_seed_id": best.get("id"),
        "best_S": best_s,
        "best_Q": best.get("Q"),
        "best_T": best.get("T"),
        "proposals": proposals,
        "valid": valid,
        "invalid": invalid,
        "measured": len(measured),
        "run_best_S": run_best,
        "gain_max": max(gains) if gains else 0,
        "gain_total": sum(gains),
        "peephole_removed": peephole_removed,
        "peephole_pairs": peephole_pairs,
        "rotation_merged": rotation_merged,
        "rotation_removed": rotation_removed,
        "prefilter_ranked": int(led.get("prefilter_ranked", 0)),
        "prefilter_discarded": int(led.get("prefilter_discarded", 0)),
        "prefilter_winners": int(led.get("prefilter_winners", 0)),
        "llm_calls": int(led.get("llm_calls", 0)),
        "llm_fallbacks": int(led.get("llm_fallbacks", 0)),
        "rejected_reasons": [e.get("note", e.get("reason", ""))
                             for e in rejected],
        "comments": comments,
    }


def render_markdown(rep: dict[str, Any]) -> str:
    """El reporte como Markdown (para guardarlo en el repo)."""
    lines = [f"# Reporte de corrida — {rep['task']}",
             "",
             "## Cuantitativo",
             "",
             f"- Mejor semilla: `{rep['best_seed_id']}` — "
             f"S={rep['best_S']}, Q={rep['best_Q']}, T={rep['best_T']}",
             f"- Propuestas: {rep['proposals']} "
             f"(válidas {rep['valid']}, inválidas {rep['invalid']}, "
             f"medidas {rep['measured']})",
             f"- Mejor S medido en la corrida: {rep['run_best_S']}",
             f"- Ganancia del operador: máx {rep['gain_max']}, "
             f"total {rep['gain_total']}",
             f"- Peephole: {rep['peephole_removed']} compuertas quitadas "
             f"({rep['peephole_pairs']} pares cancelados)",
             f"- Fusión de rotaciones: {rep['rotation_merged']} juntas "
             f"({rep['rotation_removed']} eliminadas)",
             f"- Prefilter: {rep['prefilter_ranked']} ordenados, "
             f"{rep['prefilter_discarded']} descartados, "
             f"{rep['prefilter_winners']} ganadores del paso caro",
             f"- Modelo: {rep['llm_calls']} llamadas, "
             f"{rep['llm_fallbacks']} respaldos",
             "",
             "## Cualitativo",
             ""]
    for c in rep["comments"]:
        lines.append(f"- {c}")
    if rep["rejected_reasons"]:
        lines += ["", "## Rechazadas", ""]
        for r in rep["rejected_reasons"]:
            lines.append(f"- {r}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m auto_mvp.report <runs_dir> [--out archivo.md]."""
    import argparse
    ap = argparse.ArgumentParser(prog="auto_mvp.report")
    ap.add_argument("runs_dir")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    rep = build_report(args.runs_dir)
    md = render_markdown(rep)
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
        print(f"reporte guardado en {args.out}")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

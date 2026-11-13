"""AUTO_MVP v2.6 — el BENCHMARK: cada operador medido en el mismo
circuito, en una tabla.

La herramienta tenía operadores (peephole, rotation_merge,
sa_windows) pero no había una forma de compararlos entre sí sobre
el mismo circuito: cada uno se medía aparte y en su propio formato.
El benchmark corre los tres sobre el mismo .kmx y produce una
comparación estructurada: por operador, qué quitó o fusionó, si el
circuito sigue siendo válido y cómo quedó el S. Así se ve de un
vistazo cuál operador sirve en ese circuito y cuál no.

Todo se mide con el protocolo oficial (fast_verify_invsqrt,
max_x=1024). El sa_windows corre con K y presupuesto chicos (por
defecto K=5, 5 s) para que la comparación sea rápida; no es una
corrida de optimización, es una medición.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .circuit import fast_verify_invsqrt, propose_sa_windows
from .circuits.operators.peephole import clean_file
from .circuits.operators.rotation_merge import merge_file


def benchmark(circuit_path: str | Path, *, work_dir: str | Path | None = None,
              sa_K: int = 5, sa_budget_s: float = 5.0,
              sa_seed: int = 1, run_sa: bool = True) -> dict[str, Any]:
    """Compara peephole, rotation_merge y sa_windows en un circuito.

    Con run_sa=False se salta el sa_windows (para circuitos enormes
    como el DQI, donde el SA no es práctico: 64M de instrucciones).
    """
    src = Path(circuit_path)
    work = Path(work_dir) if work_dir else Path.cwd() / ".benchmark-tmp"
    work.mkdir(parents=True, exist_ok=True)
    base = fast_verify_invsqrt(src, max_x=1024)
    result: dict[str, Any] = {
        "circuit": str(src),
        "base_valid": bool(base["valid"]),
        "base_S": base.get("S"),
        "operators": {},
    }
    if not base["valid"]:
        result["note"] = ("el circuito base no es válido: no se puede "
                          "comparar nada")
        return result
    # Peephole.
    p_out = work / "peephole.kmx"
    p_stats = clean_file(src, p_out)
    p_meas = fast_verify_invsqrt(p_out, max_x=1024)
    result["operators"]["peephole"] = {
        "stats": p_stats, "valid": bool(p_meas["valid"]),
        "S": p_meas.get("S"),
        "delta_S": (None if p_meas.get("S") is None else
                    float(p_meas["S"]) - float(base["S"])),
    }
    # Rotation merge.
    r_out = work / "rotation.kmx"
    r_stats = merge_file(src, r_out)
    r_meas = fast_verify_invsqrt(r_out, max_x=1024)
    result["operators"]["rotation_merge"] = {
        "stats": r_stats, "valid": bool(r_meas["valid"]),
        "S": r_meas.get("S"),
        "delta_S": (None if r_meas.get("S") is None else
                    float(r_meas["S"]) - float(base["S"])),
    }
    # sa_windows (con peephole como pre-paso, como en el corredor).
    # En circuitos enormes se salta: el SA no es práctico a esa escala.
    if run_sa:
        s_out = work / "sa.kmx"
        s_log = work / "sa.json"
        prop = propose_sa_windows(src, s_out, s_log, K=sa_K,
                                  budget_s=sa_budget_s, seed=sa_seed)
        if prop["ok"]:
            s_meas = fast_verify_invsqrt(s_out, max_x=1024)
            result["operators"]["sa_windows"] = {
                "stats": {"gain_reported": prop.get("gain", 0),
                          "peephole": prop.get("peephole", {}),
                          "rotation_merge": prop.get("rotation_merge", {})},
                "valid": bool(s_meas["valid"]),
                "S": s_meas.get("S"),
                "delta_S": (None if s_meas.get("S") is None else
                            float(s_meas["S"]) - float(base["S"])),
            }
        else:
            result["operators"]["sa_windows"] = {
                "stats": {"gain_reported": 0}, "valid": False, "S": None,
                "delta_S": None, "reason": prop.get("reason", ""),
            }
    else:
        result["operators"]["sa_windows"] = {
            "stats": {}, "valid": None, "S": None, "delta_S": None,
            "reason": "saltado: el circuito es demasiado grande para el SA",
        }
    # Lo cualitativo, por reglas.
    comments: list[str] = []
    for name, op in result["operators"].items():
        if not op["valid"]:
            comments.append(f"{name}: el circuito quedó inválido, no cuenta.")
        elif op["delta_S"] is not None and op["delta_S"] < 0:
            comments.append(f"{name}: mejora el S en {-op['delta_S']:.4f}.")
        else:
            comments.append(f"{name}: no mejora el S en este circuito.")
    result["comments"] = comments
    return result


def render_markdown(rep: dict[str, Any]) -> str:
    """La comparación como Markdown (para guardarla en el repo)."""
    lines = [f"# Benchmark — {rep['circuit']}", "",
             f"- S base: {rep['base_S']} (válido: {rep['base_valid']})", "",
             "| operador | válido | S | ΔS | qué hizo |",
             "|---|---|---|---|---|"]
    for name, op in rep["operators"].items():
        stats = json.dumps(op["stats"], ensure_ascii=False)
        lines.append(f"| {name} | {op['valid']} | {op.get('S')} | "
                     f"{op.get('delta_S')} | {stats} |")
    lines += ["", "## Comentario", ""]
    for c in rep.get("comments", []):
        lines.append(f"- {c}")
    if rep.get("note"):
        lines += ["", rep["note"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m auto_mvp.benchmark <circuito.kmx> [--out archivo.md]."""
    import argparse
    ap = argparse.ArgumentParser(prog="auto_mvp.benchmark")
    ap.add_argument("circuit")
    ap.add_argument("--out", default=None)
    ap.add_argument("--sa-K", type=int, default=5)
    ap.add_argument("--sa-budget-s", type=float, default=5.0)
    ap.add_argument("--no-sa", action="store_true",
                    help="saltar el sa_windows (circuitos enormes)")
    ap.add_argument("--work-dir", default=None)
    args = ap.parse_args(argv)
    rep = benchmark(args.circuit, work_dir=args.work_dir,
                    sa_K=args.sa_K, sa_budget_s=args.sa_budget_s,
                    run_sa=not args.no_sa)
    md = render_markdown(rep)
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
        print(f"benchmark guardado en {args.out}")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

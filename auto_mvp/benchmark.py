"""AUTO_MVP v2.9 — el BENCHMARK: cada operador medido en el mismo
circuito, en una tabla.

La herramienta tenía operadores (peephole, rotation_merge,
sa_windows) pero no había una forma de compararlos entre sí sobre
el mismo circuito: cada uno se medía aparte y en su propio formato.
El benchmark corre los tres sobre el mismo .kmx y produce una
comparación estructurada: por operador, qué quitó o fusionó, si el
circuito sigue siendo válido y cómo quedó el S. Así se ve de un
vistazo cuál operador sirve en ese circuito y cuál no.

La v2.9 añade el FAN-OUT como cuarto operador de la tabla: no
reescribe el circuito (no hay grupos válidos que reescribir en la
semilla ni en el DQI), pero su potencial medido aparece junto a los
demás, para que la comparación sea completa.

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
from .circuits.operators.fanout import detect_fanout_file
from .circuits.operators.peephole import clean_file
from .circuits.operators.rotation_merge import merge_file


def _measure_invsqrt(path: Path) -> dict[str, Any]:
    """Mide un circuito invsqrt (S del protocolo oficial)."""
    m = fast_verify_invsqrt(path, max_x=1024)
    return {"valid": bool(m["valid"]), "S": m.get("S")}


def _measure_dqi(path: Path) -> dict[str, Any]:
    """Mide un circuito DQI sin simularlo: que cargue en kickmix y
    su conteo de Toffolis e instrucciones. El S DQI necesita el
    verificador oficial (miles de shots sobre 892 qubits); aquí lo
    que importa es que el operador no rompa el circuito ni toque
    los Toffolis (las Clifford no cuentan en T).
    """
    try:
        import kickmix as km
        c = km.Circuit.from_file(str(path))
        st = c.operation_statistics()
        return {"valid": True, "qubits": c.num_qubits,
                "toffoli_like": st.num_toffoli_like,
                "instructions": st.num_instructions}
    except Exception as exc:  # noqa: BLE001 - el .kmx no carga
        return {"valid": False, "reason": str(exc)[:200]}


def benchmark(circuit_path: str | Path, *, work_dir: str | Path | None = None,
              sa_K: int = 5, sa_budget_s: float = 5.0,
              sa_seed: int = 1, run_sa: bool = True,
              task: str = "invsqrt") -> dict[str, Any]:
    """Compara peephole, rotation_merge y sa_windows en un circuito.

    Con run_sa=False se salta el sa_windows (para circuitos enormes
    como el DQI, donde el SA no es práctico: 64M de instrucciones).
    Con task="dqi" la medida es cargar en kickmix + conteo de
    Toffolis (no el S, que necesita el verificador oficial).
    """
    if task not in ("invsqrt", "dqi"):
        raise ValueError(f"task debe ser invsqrt o dqi, got {task!r}")
    measure = _measure_invsqrt if task == "invsqrt" else _measure_dqi
    src = Path(circuit_path)
    work = Path(work_dir) if work_dir else Path.cwd() / ".benchmark-tmp"
    work.mkdir(parents=True, exist_ok=True)
    base = measure(src)
    result: dict[str, Any] = {
        "circuit": str(src), "task": task,
        "base_valid": bool(base["valid"]),
        "base": base,
        "base_S": base.get("S"),
        "base_toffoli": base.get("toffoli_like"),
        "operators": {},
    }
    if not base["valid"]:
        result["note"] = ("el circuito base no es válido: no se puede "
                          "comparar nada")
        return result
    base_S = base.get("S")
    base_toffoli = base.get("toffoli_like")
    # Peephole.
    p_out = work / "peephole.kmx"
    p_stats = clean_file(src, p_out)
    p_meas = measure(p_out)
    result["operators"]["peephole"] = {
        "stats": p_stats, "valid": bool(p_meas["valid"]),
        "S": p_meas.get("S"),
        "delta_S": (None if p_meas.get("S") is None or base_S is None
                    else float(p_meas["S"]) - float(base_S)),
        "toffoli_like": p_meas.get("toffoli_like"),
        "delta_toffoli": (None if p_meas.get("toffoli_like") is None
                          or base_toffoli is None else
                          int(p_meas["toffoli_like"]) - int(base_toffoli)),
    }
    # Rotation merge.
    r_out = work / "rotation.kmx"
    r_stats = merge_file(src, r_out)
    r_meas = measure(r_out)
    result["operators"]["rotation_merge"] = {
        "stats": r_stats, "valid": bool(r_meas["valid"]),
        "S": r_meas.get("S"),
        "delta_S": (None if r_meas.get("S") is None or base_S is None
                    else float(r_meas["S"]) - float(base_S)),
        "toffoli_like": r_meas.get("toffoli_like"),
        "delta_toffoli": (None if r_meas.get("toffoli_like") is None
                          or base_toffoli is None else
                          int(r_meas["toffoli_like"]) - int(base_toffoli)),
    }
    # Fan-out (medición, no reescribe el circuito: el potencial es
    # lo que se ahorraría si los grupos válidos se colapsaran).
    f_rep = detect_fanout_file(src)
    result["operators"]["fanout"] = {
        "stats": {"num_groups": f_rep["num_groups"],
                  "num_valid": f_rep["num_valid"],
                  "total_potential_T": f_rep["total_potential_T"]},
        "valid": True,
        "S": base_S,
        "delta_S": 0 if base_S is not None else None,
        "toffoli_like": base_toffoli,
        "delta_toffoli": 0 if base_toffoli is not None else None,
    }
    # sa_windows (con peephole como pre-paso, como en el corredor).
    # En circuitos enormes se salta: el SA no es práctico a esa escala.
    if run_sa:
        s_out = work / "sa.kmx"
        s_log = work / "sa.json"
        prop = propose_sa_windows(src, s_out, s_log, K=sa_K,
                                  budget_s=sa_budget_s, seed=sa_seed)
        if prop["ok"]:
            s_meas = measure(s_out)
            result["operators"]["sa_windows"] = {
                "stats": {"gain_reported": prop.get("gain", 0),
                          "peephole": prop.get("peephole", {}),
                          "rotation_merge": prop.get("rotation_merge", {})},
                "valid": bool(s_meas["valid"]),
                "S": s_meas.get("S"),
                "delta_S": (None if s_meas.get("S") is None or base_S is None
                            else float(s_meas["S"]) - float(base_S)),
                "toffoli_like": s_meas.get("toffoli_like"),
                "delta_toffoli": (None if s_meas.get("toffoli_like") is None
                                  or base_toffoli is None else
                                  int(s_meas["toffoli_like"])
                                  - int(base_toffoli)),
            }
        else:
            result["operators"]["sa_windows"] = {
                "stats": {"gain_reported": 0}, "valid": False, "S": None,
                "delta_S": None, "toffoli_like": None,
                "delta_toffoli": None, "reason": prop.get("reason", ""),
            }
    else:
        result["operators"]["sa_windows"] = {
            "stats": {}, "valid": None, "S": None, "delta_S": None,
            "toffoli_like": None, "delta_toffoli": None,
            "reason": "saltado: el circuito es demasiado grande para el SA",
        }
    # Lo cualitativo, por reglas.
    comments: list[str] = []
    for name, op in result["operators"].items():
        if name == "fanout":
            st = op["stats"]
            comments.append(
                f"fanout: potencial {st['total_potential_T']} T en "
                f"{st['num_valid']} grupos válidos "
                f"(de {st['num_groups']} por subflujo).")
            continue
        if op["valid"] is None:
            comments.append(f"{name}: {op.get('reason', 'saltado')}.")
        elif op["valid"] is False:
            comments.append(f"{name}: el circuito quedó inválido, no cuenta.")
        elif op.get("delta_S") is not None and op["delta_S"] < 0:
            comments.append(f"{name}: mejora el S en {-op['delta_S']:.4f}.")
        elif op.get("delta_toffoli") is not None and op["delta_toffoli"] < 0:
            comments.append(f"{name}: quita {-op['delta_toffoli']} Toffolis.")
        elif op.get("delta_toffoli") == 0:
            comments.append(f"{name}: no toca los Toffolis (limpieza).")
        else:
            comments.append(f"{name}: no mejora el S en este circuito.")
    result["comments"] = comments
    return result


def render_markdown(rep: dict[str, Any]) -> str:
    """La comparación como Markdown (para guardarla en el repo)."""
    lines = [f"# Benchmark — {rep['circuit']} (tarea: {rep.get('task', 'invsqrt')})", ""]
    if rep.get("base_S") is not None:
        lines.append(f"- S base: {rep['base_S']} (válido: {rep['base_valid']})")
    if rep.get("base_toffoli") is not None:
        lines.append(f"- Toffoli base: {rep['base_toffoli']} "
                     f"(válido: {rep['base_valid']})")
    lines += ["",
              "| operador | válido | S | ΔS | ΔToffoli | qué hizo |",
              "|---|---|---|---|---|---|"]
    for name, op in rep["operators"].items():
        stats = json.dumps(op["stats"], ensure_ascii=False)
        lines.append(f"| {name} | {op['valid']} | {op.get('S')} | "
                     f"{op.get('delta_S')} | {op.get('delta_toffoli')} | "
                     f"{stats} |")
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
    ap.add_argument("--task", default="invsqrt",
                    help="invsqrt (S del protocolo) o dqi (conteo Toffoli)")
    ap.add_argument("--work-dir", default=None)
    args = ap.parse_args(argv)
    rep = benchmark(args.circuit, work_dir=args.work_dir,
                    sa_K=args.sa_K, sa_budget_s=args.sa_budget_s,
                    run_sa=not args.no_sa, task=args.task)
    md = render_markdown(rep)
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
        print(f"benchmark guardado en {args.out}")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

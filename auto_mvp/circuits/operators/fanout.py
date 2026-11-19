"""AUTO_MVP v2.8 — el DETECTOR de fan-out: dónde se puede colapsar
un AND a muchos objetivos.

La idea (medida en el estudio de reescritura DQI, 2026-11-12): si
el mismo AND (c1 & c2) se escribe en k objetivos distintos con CCX
consecutivos, se calcula UNA vez en un temporal y se copia con CX
(gratis en T) a los k objetivos: se ahorran (k-1) T por grupo. El
estudio midió ~33 T reales en el DQI público (extract 13 T,
padded_unsynthesis 20 T, resto 0): los grupos grandes están
dispersos, no contiguos.

Este módulo DETECTA esos grupos en un .kmx (en streaming, una
sola pasada) y reporta dónde están y cuánto se ahorraría. NO
reescribe el circuito: la reescritura necesita un temporal
(ancilla) limpio por grupo, y encontrarlo (o demostrar que existe
uno libre en ese punto) es un análisis aparte — queda pendiente
para v2.9. El detector es la mitad medible y segura: reproduce la
medición del estudio (~33 T en el DQI) sobre el .kmx.

Reglas del detector (las mismas del estudio, MÁS la validez):
- Un grupo es una racha de CCX consecutivos EN EL SUBFLUJO 3q
  (las compuertas de 2q/1q entre ellos no rompen el grupo) con el
  mismo (control1, control2) y objetivos distintos.
- Una compuerta 3q que no sea CCX con el mismo (c1, c2) rompe el
  grupo.
- Solo cuentan los grupos con k >= 2 objetivos distintos. El
  ahorro potencial es (k-1) T por grupo (sin contar el costo de
  limpiar el temporal, que es el pendiente de v2.9).
- VALIDEZ (v2.8, hallazgo al medir la semilla): un grupo solo es
  reescribible si ninguna compuerta entre sus CCX toca c1, c2 o
  los objetivos. En la semilla invsqrt los 6 grupos que salen por
  subflujo son INVÁLIDOS: entre los CCX hay CX que modifican el
  control (p. ej. CX q24 q14 entre dos CCX q16 q14), así que los
  dos CCX calculan ANDs DISTINTOS y el colapso no aplica. El
  detector los reporta como inválidos (potencial 0) y no los
  cuenta en el total.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def _split(line: str) -> tuple[str, list[str]]:
    """Una línea .kmx sin comentario: (opcode, operandos)."""
    s = line.split("#", 1)[0].strip()
    if not s:
        return "", []
    parts = s.split()
    return parts[0], parts[1:]


def _qubits_of(op: str, args: list[str]) -> set[str]:
    """Los qubits que toca una compuerta (por su opcode)."""
    if op in ("CCX", "CCZ", "CSWAP", "CCZ_IF"):
        return set(args[:3])
    if op in ("CX", "CZ", "SWAP"):
        return set(args[:2])
    if op in ("X", "Z", "H"):
        return set(args[:1])
    if op == "Z_POW":
        return set(args[:1])
    return {a for a in args if a.startswith("q")}


def detect_fanout(lines) -> dict[str, Any]:
    """Detecta grupos fan-out en las líneas de un .kmx.

    Devuelve {"groups": [...], "total_potential_T": int,
    "num_groups": int, "num_valid": int}. Cada grupo es
    {"c1": str, "c2": str, "targets": [...], "k": int,
    "potential_T": int, "valid": bool, "first_line": int}.
    """
    groups: list[dict[str, Any]] = []
    # El grupo abierto: (c1, c2, targets, first_line, touched).
    # "touched" son los qubits que tocaron las compuertas NO-CCX
    # entre los CCX del grupo (si tocan c1, c2 o un objetivo, el
    # grupo es inválido: el AND o el objetivo cambiaron).
    cur: dict[str, Any] | None = None

    def close_group() -> None:
        nonlocal cur
        if cur is not None and len(cur["targets"]) >= 2:
            cur["k"] = len(cur["targets"])
            protected = {cur["c1"], cur["c2"]} | set(cur["targets"])
            cur["valid"] = not (cur["touched"] & protected)
            cur["potential_T"] = cur["k"] - 1 if cur["valid"] else 0
            cur.pop("touched", None)
            groups.append(cur)
        cur = None

    for lineno, raw in enumerate(lines, start=1):
        op, args = _split(raw)
        if not op or op in ("REGISTER", "APPEND_TO_REGISTER",
                            "PUSH_CONDITION", "POP_CONDITION"):
            continue
        if op == "CCX" and len(args) >= 3:
            c1, c2, tgt = args[0], args[1], args[2]
            if cur is not None and cur["c1"] == c1 and cur["c2"] == c2:
                if tgt not in cur["targets"]:
                    cur["targets"].append(tgt)
                continue
            close_group()
            cur = {"c1": c1, "c2": c2, "targets": [tgt],
                   "k": 1, "potential_T": 0, "valid": True,
                   "first_line": lineno, "touched": set()}
            continue
        # No es CCX: si es 3q rompe el grupo; si no, anota los
        # qubits que toca (para validar al cerrar).
        if op in ("CCZ", "CSWAP", "CCZ_IF"):
            close_group()
        elif cur is not None:
            cur["touched"] |= _qubits_of(op, args)
    close_group()
    total = sum(g["potential_T"] for g in groups)
    return {"groups": groups,
            "total_potential_T": total,
            "num_groups": len(groups),
            "num_valid": sum(1 for g in groups if g["valid"])}


def detect_fanout_file(in_path: str | Path) -> dict[str, Any]:
    """Detecta grupos fan-out en un .kmx en disco, en streaming."""
    in_path = Path(in_path)
    with in_path.open(encoding="utf-8") as fin:
        return detect_fanout((line.rstrip("\n") for line in fin))


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m auto_mvp.circuits.operators.fanout <circuito.kmx>."""
    import argparse
    import json
    ap = argparse.ArgumentParser(prog="auto_mvp.circuits.operators.fanout")
    ap.add_argument("circuit")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    rep = detect_fanout_file(args.circuit)
    text = json.dumps(rep, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"fan-out guardado en {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

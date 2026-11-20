"""yosys_to_ir.py — Convierte el netlist JSON de Yosys al IR neutral.

Yosys escribe su netlist con `write_json` (módulos, puertos, celdas
$_AND_, $_XOR_, $_NOT_, etc.). Este conversor lo aplana a nuestro IR
(capa 2): nodos AND/XOR/NOT con args/out, más el presupuesto de
qubits que impone Julia (capa 3).

Uso: python3 yosys_to_ir.py yosys.json ir.json --budget 892
"""

from __future__ import annotations

import argparse
import json
import sys


def yosys_to_ir(yosys: dict, budget: int, name: str) -> dict:
    """Un módulo Yosys -> IR neutral."""
    modules = yosys.get("modules", {})
    if not modules:
        raise ValueError("el JSON de Yosys no trae módulos")
    # Tomar el primer módulo (top).
    mod = next(iter(modules.values()))
    ports = mod.get("ports", {})
    inputs = sorted(p for p, d in ports.items() if d.get("direction") == "input")
    outputs = sorted(p for p, d in ports.items() if d.get("direction") == "output")
    nodes = []
    cells = mod.get("cells", {})
    for cid, cell in sorted(cells.items()):
        ctype = cell.get("type", "")
        conns = cell.get("connections", {})
        if ctype in ("$_AND_", "$and"):
            args = list(conns.get("A", [])) + list(conns.get("B", []))
            out = list(conns.get("Y", []))
            if len(args) == 2 and len(out) == 1:
                nodes.append({"id": cid, "op": "AND",
                              "args": [str(a) for a in args],
                              "out": str(out[0])})
        elif ctype in ("$_XOR_", "$xor"):
            args = list(conns.get("A", [])) + list(conns.get("B", []))
            out = list(conns.get("Y", []))
            if len(args) == 2 and len(out) == 1:
                nodes.append({"id": cid, "op": "XOR",
                              "args": [str(a) for a in args],
                              "out": str(out[0])})
        elif ctype in ("$_NOT_", "$not"):
            args = list(conns.get("A", []))
            out = list(conns.get("Y", []))
            if len(args) == 1 and len(out) == 1:
                nodes.append({"id": cid, "op": "NOT",
                              "args": [str(args[0])],
                              "out": str(out[0])})
        # Otras celdas (buffers, muxes) se ignoran: Yosys con
        # `synth` + `abc` las reduce a AND/XOR/NOT.
    and_count = sum(1 for n in nodes if n["op"] == "AND")
    return {
        "name": name,
        "inputs": inputs,
        "outputs": outputs,
        "qubit_budget": int(budget),
        "nodes": nodes,
        "and_count": and_count,
        "uncompute_plan": [],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Yosys JSON -> IR neutral")
    ap.add_argument("yosys_json")
    ap.add_argument("ir_json")
    ap.add_argument("--budget", type=int, default=892)
    ap.add_argument("--name", default="bloque")
    args = ap.parse_args(argv)
    with open(args.yosys_json) as f:
        yosys = json.load(f)
    ir = yosys_to_ir(yosys, args.budget, args.name)
    with open(args.ir_json, "w") as f:
        json.dump(ir, f, indent=2)
    print(f"IR: {len(ir['nodes'])} nodos, {ir['and_count']} AND "
          f"(Toffolis), budget Q={ir['qubit_budget']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

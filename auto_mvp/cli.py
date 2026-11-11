"""AUTO_MVP v0.7.0 — CLI: el punto de entrada por terminal de la Skill.

Uso (después de instalar el paquete, o desde el repo):
    python -m auto_mvp.cli <operación> [opciones]

Operaciones (las mismas que la Skill, el servidor MCP y las
funciones para ChatGPT/Grok; ver auto_mvp/operations.py):
    evaluate   evalúa un candidato (proxy + puerta) desde un JSON
    tunnel     tunela un grafo de llamadas con las reglas MORPH
    decode     decodifica una config JSON (directivas en lenguaje natural)
    run        corre el orquestador adaptativo sobre candidatos + config
    integrity  pasa el filtro de integridad sobre una evidencia
    export     exporta e inyecta un módulo promovido al dataset de trabajo
    gate       la puerta de promoción (GM, DQI necesario, S objetivo)
    version    la versión del paquete

Entrada y salida son JSON (por archivo con --in/--out, o por stdin/
stdout). Nada se imprime fuera del JSON de salida (salvo errores).
"""
from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .operations import (OPERATIONS, apply_morph_tunnel, check_integrity,
                         decode_json_config, evaluate_candidate,
                         export_module, promotion_gate, run_orchestrator)


def _load(path: str | None) -> dict:
    if path is None:
        return json.load(sys.stdin)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _emit(obj: dict) -> None:
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="auto-mvp",
                                description="Optimizador AUTO_MVP para VQCC")
    sub = p.add_subparsers(dest="op", required=True)

    def add(name: str, help_text: str) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("--in", dest="inp", default=None,
                        help="archivo JSON de entrada (si no, stdin)")
        return sp

    e = add("evaluate", "evalúa un candidato (proxy + puerta)")
    e.add_argument("--meta-mvp", type=float, default=30.0)
    e.add_argument("--margin", type=float, default=0.10)
    e.add_argument("--best-S", type=float, default=None)

    t = add("tunnel", "tunela un grafo de llamadas (MORPH)")
    t.add_argument("--method", default="greedy", choices=("greedy", "beam"))

    add("decode", "decodifica una config JSON (directivas en lenguaje natural)")

    r = add("run", "corre el orquestador adaptativo")
    r.add_argument("--candidates", default=None,
                   help="archivo JSON con la lista de candidatos")
    r.add_argument("--runs-dir", default=None,
                   help="dónde guardar los artefactos (si no, temporal)")
    r.add_argument("--best-S", default=None,
                   help="JSON con el mejor S por tarea, ej. '{\"dqi\": 3.714e12}'")

    add("integrity", "pasa el filtro de integridad sobre una evidencia")

    x = add("export", "exporta e inyecta un módulo promovido al dataset")
    x.add_argument("--runs-dir", default=None,
                   help="directorio de runs (si no, temporal)")

    g = add("gate", "la puerta de promoción")
    g.add_argument("--meta-mvp", type=float, default=30.0)
    g.add_argument("--S", dest="S", default=None,
                   help="JSON con los S por tarea, ej. '{\"dqi\": 3.7e11}'")

    sub.add_parser("version", help="la versión del paquete")

    args = p.parse_args(argv)
    if args.op == "version":
        _emit({"version": __version__})
        return 0
    try:
        if args.op == "evaluate":
            data = _load(args.inp)
            out = evaluate_candidate(data, meta_mvp=args.meta_mvp,
                                     margin=args.margin, best_S=args.best_S)
        elif args.op == "tunnel":
            data = _load(args.inp)
            out = apply_morph_tunnel(data.get("call_graph", data),
                                     rules=data.get("rules"),
                                     method=args.method)
        elif args.op == "decode":
            out = decode_json_config(_load(args.inp))
        elif args.op == "run":
            config = _load(args.inp)
            cands = _load(args.candidates) if args.candidates else \
                config.pop("candidates", [])
            if isinstance(cands, dict):
                cands = cands.get("candidates", [])
            best = json.loads(args.best_S) if args.best_S else None
            out = run_orchestrator(cands, config, runs_dir=args.runs_dir,
                                   best_S=best)
        elif args.op == "integrity":
            out = check_integrity(_load(args.inp))
        elif args.op == "export":
            out = export_module(_load(args.inp), runs_dir=args.runs_dir)
        elif args.op == "gate":
            s = json.loads(args.S) if args.S else None
            out = promotion_gate(args.meta_mvp, S=s)
        else:  # pragma: no cover
            p.error(f"operación desconocida: {args.op}")
    except (ValueError, KeyError, TypeError) as exc:
        _emit({"error": str(exc)})
        return 2
    _emit(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

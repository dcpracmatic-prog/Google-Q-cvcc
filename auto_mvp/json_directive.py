"""AUTO_MVP — decodificador de JSON en lenguaje natural (desde v0.6.0).

La capa de adaptación dinámica por JSON: lee configuraciones JSON
(con directivas en lenguaje natural) y las traduce a pasos del
pipeline y metodologías. El orquestador no se limita a pruebas
fijas y paramétricas: lee el JSON, reordena pasos, adapta
metodologías en caliente y ejecuta iteraciones inteligentes.

El "lenguaje natural" es un VOCABULARIO CONTROLADO, no NLP libre:
las directivas se parsean con reglas deterministas (palabras clave
+ números), sin modelo de lenguaje y sin adivinanzas. Cada directiva
que no encaja en el vocabulario se devuelve como NO PARSEADA, con
el motivo, y el llamador decide: nunca se descarta en silencio.

Vocabulario (español, sin tildes en el matching):
- "meta 30" / "sube la meta a 30" / "baja la meta a 2" -> set_meta_mvp
- "ataca unextract" / "tunela chien" / "tunela chien con montgomery"
  -> attack_block / tunnel
- "poda lo que no baje T un 5%" -> prune
- "reordena tunnel antes que gate" / "mueve proxy despues de tunnel"
  -> reorder_step
- "reemplaza proxy por numeric" / "usa beam en vez de greedy"
  / "cambia gate a meta_mvp" -> replace_method
- "inserta observe despues de compile" -> insert_step
- "quita calibrate" / "elimina search" -> remove_step
- "presupuesto 20 intentos" / "presupuesto 6 horas" -> set_budget
- "usa numeric para proxy" -> set_method

Pasos conocidos: proxy, gate, tunnel, compile, observe, calibrate,
search, verify. Métodos conocidos por paso (ver METHODS).
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

STEPS = ("proxy", "gate", "tunnel", "compile", "observe", "calibrate",
         "search", "verify")

METHODS: dict[str, tuple[str, ...]] = {
    "proxy": ("metadata", "numeric"),
    "gate": ("meta_mvp",),
    "tunnel": ("greedy", "beam"),
    "compile": ("official", "local"),
    "observe": ("observer",),
    "calibrate": ("dcp",),
    "search": ("morph", "mwis"),
    "verify": ("official", "local"),
}

ALL_METHODS = sorted({m for ms in METHODS.values() for m in ms})


@dataclass
class Directive:
    """Una directiva decodificada: verbo + parámetros + texto original."""
    verb: str
    params: dict[str, Any] = field(default_factory=dict)
    raw: str = ""
    parsed: bool = True
    reason: str = ""


def _norm(text: str) -> str:
    """Minúsculas sin tildes, para el matching (el raw se conserva)."""
    s = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _num(text: str) -> float | None:
    m = re.search(r"(\d+(?:[.,]\d+)?)", text)
    return float(m.group(1).replace(",", ".")) if m else None


def parse_directive(text: str) -> Directive:
    """Decodifica una directiva en lenguaje natural (vocabulario controlado)."""
    raw = text.strip()
    t = _norm(raw)
    # meta: "meta 30" / "sube la meta a 30" / "pon la meta en 30"
    m = re.search(r"\bmeta\b.*?(\d+(?:[.,]\d+)?)", t)
    if m and ("meta" in t):
        return Directive("set_meta_mvp",
                         {"meta_mvp": float(m.group(1).replace(",", "."))},
                         raw=raw)
    # tunelar / atacar un bloque: "tunela chien con montgomery-b17"
    m = re.match(r"^(?:tunela|ataca|atacar|tunnel)\s+([a-z0-9_]+)"
                 r"(?:\s+con\s+([a-z0-9_\-]+))?", t)
    if m:
        params: dict[str, Any] = {"block": m.group(1)}
        if m.group(2):
            params["rule"] = m.group(2)
        return Directive("tunnel", params, raw=raw)
    # podar: "poda lo que no baje T un 5%"
    m = re.search(r"\bpoda\b.*?([a-z])\s+un\s+(\d+(?:[.,]\d+)?)\s*%", t)
    if m:
        return Directive("prune", {"metric": m.group(1).upper(),
                                   "pct": float(m.group(2).replace(",", "."))},
                         raw=raw)
    m = re.match(r"^\s*poda\b", t)
    if m:
        return Directive("prune", {"metric": "T", "pct": 0.0}, raw=raw)
    # reordenar: "reordena X antes que Y" / "mueve X despues de Y"
    m = re.match(r"^(?:reordena|mueve|mover)\s+([a-z_]+)\s+"
                 r"(antes(?:\s+que|\s+de)?|despues(?:\s+de)?)\s+([a-z_]+)", t)
    if m:
        where = "before" if m.group(2).startswith("antes") else "after"
        return Directive("reorder_step",
                         {"step": m.group(1), where: m.group(3)}, raw=raw)
    # reemplazar método: "reemplaza proxy por numeric"
    m = re.match(r"^reemplaza\s+([a-z_]+)\s+por\s+([a-z0-9_\-]+)", t)
    if m:
        return Directive("replace_method",
                         {"step": m.group(1), "method": m.group(2)}, raw=raw)
    m = re.match(r"^usa\s+([a-z0-9_\-]+)\s+en\s+vez\s+de\s+([a-z0-9_\-]+)", t)
    if m:
        return Directive("replace_method",
                         {"from": m.group(2), "method": m.group(1)}, raw=raw)
    m = re.match(r"^cambia\s+([a-z_]+)\s+a\s+([a-z0-9_\-]+)", t)
    if m:
        return Directive("replace_method",
                         {"step": m.group(1), "method": m.group(2)}, raw=raw)
    # insertar: "inserta observe despues de compile"
    m = re.match(r"^inserta\s+([a-z_]+)\s+"
                 r"(antes(?:\s+de)?|despues(?:\s+de)?)\s+([a-z_]+)", t)
    if m:
        where = "before" if m.group(2).startswith("antes") else "after"
        return Directive("insert_step",
                         {"step": m.group(1), where: m.group(3)}, raw=raw)
    # quitar: "quita calibrate"
    m = re.match(r"^(?:quita|elimina|quitar|eliminar)\s+([a-z_]+)", t)
    if m:
        return Directive("remove_step", {"step": m.group(1)}, raw=raw)
    # presupuesto: "presupuesto 20 intentos" / "presupuesto 6 horas"
    m = re.match(r"^presupuesto\s+(\d+(?:[.,]\d+)?)\s+(intentos|horas|hora)", t)
    if m:
        key = "trials" if m.group(2).startswith("intento") else "hours"
        return Directive("set_budget",
                         {key: float(m.group(1).replace(",", "."))}, raw=raw)
    # método para un paso: "usa numeric para proxy"
    m = re.match(r"^usa\s+([a-z0-9_\-]+)\s+para\s+([a-z_]+)", t)
    if m:
        return Directive("set_method",
                         {"step": m.group(2), "method": m.group(1)}, raw=raw)
    return Directive("unknown", {}, raw=raw, parsed=False,
                     reason=("no encaja en el vocabulario controlado "
                             "(ver json_directive.METHODS / STEPS)"))


def load_plan(source: str | Path | dict) -> dict[str, Any]:
    """Lee una configuración JSON y la decodifica.

    Acepta una ruta, un texto JSON o un dict. Devuelve:
    {"meta_mvp": ..., "steps": [pasos], "directives": [Directive],
     "unparsed": [Directive no parseadas], "budget": {...}}.
    Las directivas en lenguaje natural se parsean; las que no
    encajan quedan en "unparsed" con su motivo (nunca se tiran).
    """
    if isinstance(source, dict):
        cfg = source
    else:
        text = Path(source).read_text(encoding="utf-8") if Path(source).exists() \
            else str(source)
        cfg = json.loads(text)
    steps: list[dict[str, Any]] = []
    for s in cfg.get("steps", []):
        if isinstance(s, dict):
            steps.append({"step": s.get("step", ""), "method": s.get("method", ""),
                          "params": dict(s.get("params", {}))})
        elif isinstance(s, str):
            d = parse_directive(s)
            if d.parsed and d.verb in ("set_method", "replace_method"):
                steps.append({"step": d.params.get("step", ""),
                              "method": d.params.get("method", ""),
                              "params": {}})
    directives = [parse_directive(d) for d in cfg.get("directives", [])]
    unparsed = [d for d in directives if not d.parsed]
    return {
        "meta_mvp": cfg.get("meta_mvp"),
        "steps": steps,
        "directives": directives,
        "unparsed": unparsed,
        "budget": dict(cfg.get("budget", {})),
        "raw": cfg,
    }

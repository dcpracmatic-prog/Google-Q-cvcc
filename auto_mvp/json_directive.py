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


def _bad(raw: str, reason: str) -> Directive:
    """Una directiva que no encaja (o encaja con nombres inválidos).

    Nunca se acepta en silencio: parsed=False y el motivo, para que
    el llamador la registre en `unparsed`.
    """
    return Directive("unknown", {}, raw=raw, parsed=False, reason=reason)


def _check_step(raw: str, step: str) -> Directive | None:
    """None si el paso es conocido; si no, la directiva no parseada."""
    if step not in STEPS:
        return _bad(raw, f"paso desconocido: {step!r} (ver STEPS: "
                         f"{', '.join(STEPS)})")
    return None


def _check_method(raw: str, step: str, method: str) -> Directive | None:
    """None si el método es válido para ese paso; si no, no parseada."""
    if method not in METHODS.get(step, ()):
        return _bad(raw, f"método {method!r} no válido para el paso "
                         f"{step!r} (ver METHODS: "
                         f"{', '.join(METHODS.get(step, ())) or 'ninguno'})")
    return None


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
        for name in (m.group(1), m.group(3)):
            if (bad := _check_step(raw, name)) is not None:
                return bad
        where = "before" if m.group(2).startswith("antes") else "after"
        return Directive("reorder_step",
                         {"step": m.group(1), where: m.group(3)}, raw=raw)
    # reemplazar método: "reemplaza proxy por numeric"
    m = re.match(r"^reemplaza\s+([a-z_]+)\s+por\s+([a-z0-9_\-]+)", t)
    if m:
        if (bad := _check_step(raw, m.group(1))) is not None:
            return bad
        if (bad := _check_method(raw, m.group(1), m.group(2))) is not None:
            return bad
        return Directive("replace_method",
                         {"step": m.group(1), "method": m.group(2)}, raw=raw)
    m = re.match(r"^usa\s+([a-z0-9_\-]+)\s+en\s+vez\s+de\s+([a-z0-9_\-]+)", t)
    if m:
        if m.group(1) not in ALL_METHODS:
            return _bad(raw, f"método desconocido: {m.group(1)!r} "
                             f"(ver ALL_METHODS: {', '.join(ALL_METHODS)})")
        return Directive("replace_method",
                         {"from": m.group(2), "method": m.group(1)}, raw=raw)
    m = re.match(r"^cambia\s+([a-z_]+)\s+a\s+([a-z0-9_\-]+)", t)
    if m:
        if (bad := _check_step(raw, m.group(1))) is not None:
            return bad
        if (bad := _check_method(raw, m.group(1), m.group(2))) is not None:
            return bad
        return Directive("replace_method",
                         {"step": m.group(1), "method": m.group(2)}, raw=raw)
    # insertar: "inserta observe despues de compile"
    m = re.match(r"^inserta\s+([a-z_]+)\s+"
                 r"(antes(?:\s+de)?|despues(?:\s+de)?)\s+([a-z_]+)", t)
    if m:
        for name in (m.group(1), m.group(3)):
            if (bad := _check_step(raw, name)) is not None:
                return bad
        where = "before" if m.group(2).startswith("antes") else "after"
        return Directive("insert_step",
                         {"step": m.group(1), where: m.group(3)}, raw=raw)
    # quitar: "quita calibrate"
    m = re.match(r"^(?:quita|elimina|quitar|eliminar)\s+([a-z_]+)", t)
    if m:
        if (bad := _check_step(raw, m.group(1))) is not None:
            return bad
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
        if (bad := _check_step(raw, m.group(2))) is not None:
            return bad
        if (bad := _check_method(raw, m.group(2), m.group(1))) is not None:
            return bad
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
    step_unparsed: list[Directive] = []
    for s in cfg.get("steps", []):
        if isinstance(s, dict):
            step = s.get("step", "")
            method = s.get("method", "")
            if step not in STEPS:
                step_unparsed.append(_bad(
                    str(s), f"paso desconocido: {step!r} (ver STEPS: "
                            f"{', '.join(STEPS)})"))
            elif method and method not in METHODS.get(step, ()):
                step_unparsed.append(_bad(
                    str(s), f"método {method!r} no válido para el paso "
                            f"{step!r} (ver METHODS)"))
            else:
                steps.append({"step": step, "method": method,
                              "params": dict(s.get("params", {}))})
        elif isinstance(s, str):
            d = parse_directive(s)
            if (d.parsed and d.verb in ("set_method", "replace_method")
                    and "step" in d.params):
                steps.append({"step": d.params.get("step", ""),
                              "method": d.params.get("method", ""),
                              "params": {}})
            else:
                # Un paso en texto que no define un paso (una directiva
                # como "tunela chien", un reordenamiento, una meta...)
                # no desaparece: queda en unparsed con su motivo.
                if d.parsed:
                    d = Directive(d.verb, d.params, raw=d.raw, parsed=False,
                                  reason=("es una directiva, no un paso del "
                                          "plan: ponla en 'directives' o "
                                          "escribe el paso como dict"))
                step_unparsed.append(d)
        else:
            step_unparsed.append(_bad(
                str(s), "paso con formato desconocido (dict o texto)"))
    directives = [parse_directive(d) for d in cfg.get("directives", [])]
    # H4: la meta y el presupuesto que fijan las directivas se pliegan
    # en el plan (la directiva manda: es la capa dinámica, y el
    # orquestador ya la aplicaba al arrancar; aquí queda registrada).
    meta_mvp = cfg.get("meta_mvp")
    budget = dict(cfg.get("budget", {}))
    for d in directives:
        if d.parsed and d.verb == "set_meta_mvp":
            meta_mvp = d.params["meta_mvp"]
        elif d.parsed and d.verb == "set_budget":
            budget.update(d.params)
    unparsed = [d for d in directives if not d.parsed] + step_unparsed
    return {
        "meta_mvp": meta_mvp,
        "steps": steps,
        "directives": directives,
        "unparsed": unparsed,
        "budget": budget,
        "raw": cfg,
    }

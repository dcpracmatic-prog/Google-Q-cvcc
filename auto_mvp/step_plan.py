"""AUTO_MVP — plan de pasos y reprogramación fluida (desde v0.6.0).

La reprogramación fluida de órdenes o pasos entre celdas: el plan
es la lista ordenada de pasos (celdas) del orquestador, y el
orquestador puede reordenar pasos y reprogramar celdas EN CALIENTE
(entre iteraciones), por directivas JSON. Cada reprogramación queda
en el log (qué cambió, cuándo, por qué directiva): nada se cambia
sin dejar rastro.

Un paso es {"step": nombre, "method": método, "params": {...}}.
Pasos: proxy, gate, tunnel, compile, observe, calibrate, search,
verify. El orden por defecto es el del pipeline (proxy -> gate ->
compile) con el túnel antes de la puerta y la observación al final;
el plan lo cambia todo por directivas.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .json_directive import METHODS, STEPS, Directive

DEFAULT_STEPS: list[dict[str, Any]] = [
    {"step": "tunnel", "method": "greedy", "params": {}},
    {"step": "proxy", "method": "metadata", "params": {}},
    {"step": "gate", "method": "meta_mvp", "params": {}},
    {"step": "compile", "method": "local", "params": {}},
    {"step": "observe", "method": "observer", "params": {}},
]


@dataclass
class StepPlan:
    """El plan de pasos del orquestador, reprogramable en caliente."""
    steps: list[dict[str, Any]] = field(default_factory=list)
    log: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        if not self.steps:
            self.steps = [dict(s, params=dict(s.get("params", {})))
                          for s in DEFAULT_STEPS]

    @property
    def order(self) -> list[str]:
        return [s["step"] for s in self.steps]

    def _record(self, action: str, detail: dict[str, Any],
                directive: str = "") -> None:
        self.log.append({"action": action, "detail": detail,
                         "directive": directive, "ts": time.time(),
                         "order_after": list(self.order)})

    def move(self, step: str, before: str | None = None,
             after: str | None = None, directive: str = "") -> bool:
        """Mueve un paso antes/después de otro. False si no existe."""
        idx = next((i for i, s in enumerate(self.steps)
                    if s["step"] == step), None)
        if idx is None:
            return False
        item = self.steps.pop(idx)
        if before is not None:
            j = next((i for i, s in enumerate(self.steps)
                      if s["step"] == before), len(self.steps))
            self.steps.insert(j, item)
        elif after is not None:
            j = next((i for i, s in enumerate(self.steps)
                      if s["step"] == after), len(self.steps) - 1)
            self.steps.insert(j + 1, item)
        else:
            self.steps.append(item)
        self._record("move", {"step": step, "before": before, "after": after},
                     directive)
        return True

    def replace_method(self, step: str, method: str,
                       directive: str = "") -> bool:
        """Reprograma una celda: cambia el método de un paso."""
        for s in self.steps:
            if s["step"] == step:
                old = s["method"]
                s["method"] = method
                self._record("replace_method",
                             {"step": step, "from": old, "to": method},
                             directive)
                return True
        return False

    def set_method(self, step: str, method: str,
                   directive: str = "") -> bool:
        return self.replace_method(step, method, directive)

    def insert(self, step: str, method: str = "",
               before: str | None = None, after: str | None = None,
               directive: str = "") -> bool:
        """Inserta un paso nuevo antes/después de otro (o al final)."""
        if any(s["step"] == step for s in self.steps):
            return False
        item = {"step": step, "method": method, "params": {}}
        if before is not None:
            j = next((i for i, s in enumerate(self.steps)
                      if s["step"] == before), len(self.steps))
            self.steps.insert(j, item)
        elif after is not None:
            j = next((i for i, s in enumerate(self.steps)
                      if s["step"] == after), len(self.steps) - 1)
            self.steps.insert(j + 1, item)
        else:
            self.steps.append(item)
        self._record("insert", {"step": step, "method": method,
                                "before": before, "after": after}, directive)
        return True

    def remove(self, step: str, directive: str = "") -> bool:
        """Quita un paso del plan."""
        before = len(self.steps)
        self.steps = [s for s in self.steps if s["step"] != step]
        if len(self.steps) == before:
            return False
        self._record("remove", {"step": step}, directive)
        return True

    def apply(self, directive: Directive) -> bool:
        """Aplica una directiva decodificada al plan. False si no aplica."""
        p = directive.params
        v = directive.verb
        if v == "reorder_step":
            return self.move(p["step"], before=p.get("before"),
                             after=p.get("after"), directive=directive.raw)
        if v in ("replace_method", "set_method"):
            if "step" in p:
                return self.replace_method(p["step"], p["method"],
                                           directive=directive.raw)
            # "usa X en vez de Y": reemplaza el método Y donde esté.
            for s in self.steps:
                if s["method"] == p.get("from"):
                    return self.replace_method(s["step"], p["method"],
                                               directive=directive.raw)
            return False
        if v == "insert_step":
            return self.insert(p["step"], before=p.get("before"),
                               after=p.get("after"), directive=directive.raw)
        if v == "remove_step":
            return self.remove(p["step"], directive=directive.raw)
        return False

    def method_of(self, step: str) -> str | None:
        for s in self.steps:
            if s["step"] == step:
                return s["method"]
        return None

    def as_dict(self) -> dict[str, Any]:
        return {"steps": [dict(s) for s in self.steps],
                "log": list(self.log)}

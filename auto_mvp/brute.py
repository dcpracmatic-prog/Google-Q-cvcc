"""AUTO_MVP — fuerza bruta aritmética sobre las métricas (desde v1.3.0).

El mutador (mutator.py) propone configuraciones REALES: muta el grafo
con reglas medidas y el pipeline solo promueve lo que mejora el S
medido. Pero las reglas medidas se acaban (hoy solo DQI tiene una) y
el corredor NO se para por eso: la fuerza bruta sigue proponiendo la
infinidad de posibilidades que existen sobre los números.

Cómo: para cada tarea, las variables de costo que usa su fórmula
oficial de S (nunca eps_plus, rel_error ni la estructura: se heredan
de la semilla) se van bajando con operaciones aritméticas, de menor a
mayor cambio: restar 1, 10, 100..., multiplicar por 0.99, 0.9, 0.5,
dividir entre 2... y la escala crece en cada ciclo. El S de cada
propuesta se calcula con la fórmula oficial exacta (estimate_S): la
propuesta es un número que la configuración TENDRÍA que alcanzar, no
un circuito que exista. Por eso las propuestas de fuerza bruta NUNCA
entran al ledger (no son medido): viven aparte, marcadas
``measured=False`` / ``kind="brute"``, y el ZIP las entrega como
``proyectado``: la frontera de números que hay que alcanzar, junto a
lo mejor real que se tiene. Sin esa marca, sería inventar un resultado.

La secuencia de operaciones es infinita (la escala crece sin límite)
y los pisos (T>=1, Q>=1, toffoli>=1...) evitan valores sin sentido:
la caminata solo se agota si llega a los pisos, lo que para cualquier
meta realista no pasa.
"""
from __future__ import annotations

import math
from typing import Any

from .proxy import CandidateMeta, estimate_S

# Variables de costo por tarea, con su piso y si es un conteo entero.
# Los conteos de un circuito son enteros (Q, T, Toffolis, Ttot, Qtot):
# la fuerza bruta nunca entrega Q=404.92. Las medias del verificador
# son otra cosa: invsqrt cobra Toffolis MEDIOS por shot (el verificador
# oficial reporta media 1,325.48 y C equivalente), así que toffoli y
# t_count son continuos ahí; solo Q es entero. lambda_eff es un
# parámetro físico continuo (ver el límite de Lambda implicada abajo).
_COST_VARS: dict[str, tuple[tuple[str, float, bool], ...]] = {
    "dqi": (("T", 1.0, True), ("Q", 1.0, True)),
    "invsqrt": (("toffoli", 1.0, False), ("t_count", 0.0, False),
                ("Q", 1.0, True)),
    "dfthcsos": (("lambda_eff", 0.001, False), ("Ttot", 1.0, True),
                 ("Qtot", 1.0, True)),
}

# Pasos de menor a mayor cambio, por ciclo. La resta escala x10 en cada
# ciclo; los factores se repiten igual (ya son el cambio grande).
_SUB_STEPS = (1.0, 10.0, 100.0)
_FACTORS = (0.999, 0.99, 0.98, 0.95, 0.9, 0.75, 0.5)

# Pasos finos: cuando el S ya está cerca del objetivo (<= 1.5x), solo
# se usan estos, para no pasar de largo de un salto (Q*0.5 cortaba el
# S en 4 de golpe y la GM saltaba de 30 a 38).
_FINE_SUB = (1.0,)
_FINE_FACTORS = (0.999, 0.99)


def _s_of(task: str, metrics: dict[str, Any]) -> float | None:
    """El S oficial de unas métricas (None si no se puede calcular)."""
    try:
        return float(estimate_S(CandidateMeta(task=task, metrics=metrics)))
    except Exception:
        return None


def limits_ok(task: str, metrics: dict[str, Any]) -> list[str]:
    """Los límites físicos de la competencia para unas métricas.

    Lista de fallos, vacía si pasa. Son los del contrato oficial
    (``SPECS[task]().check_metrics``) más dos reglas de la fórmula:
    - los conteos son enteros (un circuito no tiene 404.92 cúbits);
    - química: la Lambda implicada por lambda_eff y E_gap
      (lambda_eff = sqrt(E_gap*(2*Lambda - E_gap)), o sea
      Lambda = (lambda_eff^2/E_gap + E_gap)/2) debe ser > 49.0.
      Bajar lambda_eff sin tocar E_gap es cambiar la factorización
      por otra con otra Lambda: si esa Lambda cae bajo 49, no vale.
    Las estructuras que la fuerza bruta no toca (eps_plus, rel_error,
    error_2, E_gap, los Angles_k) se heredan de la semilla medida: sus
    límites ya los pasa la semilla y no cambian.
    """
    fails: list[str] = []
    for key, _floor, is_int in _COST_VARS.get(task, ()):
        v = metrics.get(key)
        if v is None:
            continue
        if is_int and not (isinstance(v, int)
                           or (isinstance(v, float) and v.is_integer())):
            fails.append(f"{task}: {key} = {v} no es entero")
    if task == "dfthcsos":
        lam_eff = metrics.get("lambda_eff")
        gap = metrics.get("E_gap")
        if lam_eff is not None and gap:
            lam = (float(lam_eff) ** 2 / float(gap) + float(gap)) / 2.0
            if not lam > 49.0:
                fails.append(
                    f"química: Lambda implicada = {lam:.2f} debe ser > 49.0")
    try:
        from .vqcc.contracts import SPECS
        view = dict(metrics)
        if task == "invsqrt":
            # El contrato pide C; el candidato trae toffoli y t_count:
            # C = Toffoli + T/4, la fórmula oficial de invsqrt.
            view["C"] = float(metrics.get("toffoli", 0)) + float(
                metrics.get("t_count", 0)) / 4.0
        fails.extend(SPECS[task]().check_metrics(view))
    except Exception:
        pass
    return fails


class BruteForce:
    """Caminata aritmética infinita desde unas métricas base.

    ``walk(target_S, max_steps)`` baja las variables de costo con
    operaciones aritméticas (de menor a mayor cambio) hasta que el S
    llega a ``target_S`` o se acaban los pasos. El estado (métricas y
    posición en la secuencia) persiste entre llamadas: la caminata
    sigue donde se quedó, ronda tras ronda, sin pararse nunca.
    """

    def __init__(self, task: str, base_metrics: dict[str, Any]):
        if task not in _COST_VARS:
            raise ValueError(f"tarea desconocida: {task!r}")
        self.task = task
        self.base_metrics = dict(base_metrics)
        self.metrics = dict(base_metrics)
        self.vars = _COST_VARS[task]
        self.op_index = 0
        self.fine_index = 0
        self.cycle = 0
        self.best_metrics = dict(base_metrics)
        self.best_S = _s_of(task, self.metrics)
        self.ops_used: list[str] = []
        self.steps = 0
        self.exhausted = False

    def _next_op(self, fine: bool) -> tuple[str, str, str, float]:
        """La siguiente operación: (etiqueta, variable, 'sub'|'mul', valor)."""
        if fine:
            n_vars = len(self.vars)
            per_var = len(_FINE_SUB) + len(_FINE_FACTORS)
            pos = self.fine_index % (n_vars * per_var)
            self.fine_index += 1
            var_idx, step_idx = divmod(pos, per_var)
            key, _floor, _is_int = self.vars[var_idx]
            if step_idx < len(_FINE_SUB):
                amount = _FINE_SUB[step_idx]
                return f"{key}-{amount:g}", key, "sub", amount
            factor = _FINE_FACTORS[step_idx - len(_FINE_SUB)]
            return f"{key}*{factor:g}", key, "mul", factor
        n_vars = len(self.vars)
        per_var = len(_SUB_STEPS) + len(_FACTORS)
        pos = self.op_index % (n_vars * per_var)
        self.op_index += 1
        if self.op_index % (n_vars * per_var) == 0:
            self.cycle += 1
        var_idx, step_idx = divmod(pos, per_var)
        key, _floor, _is_int = self.vars[var_idx]
        if step_idx < len(_SUB_STEPS):
            amount = _SUB_STEPS[step_idx] * (10.0 ** self.cycle)
            return f"{key}-{amount:g}", key, "sub", amount
        factor = _FACTORS[step_idx - len(_SUB_STEPS)]
        return f"{key}*{factor:g}", key, "mul", factor

    def _apply(self, metrics: dict[str, Any], op) -> dict[str, Any] | None:
        """Aplica una operación; None si cae bajo el piso, no cambia
        nada, o viola un límite físico (conteos enteros, contrato)."""
        _label, key, kind, amount = op
        _k, floor, is_int = next((k, f, i) for k, f, i in self.vars
                                 if k == key)
        cur = float(metrics[key])
        new = cur - amount if kind == "sub" else cur * amount
        if is_int:
            new = float(int(round(new)))
            if new >= cur:
                return None
        if not (math.isfinite(new) and new >= floor):
            return None
        out = dict(metrics)
        out[key] = int(new) if is_int else new
        if limits_ok(self.task, out):
            return None
        return out

    def walk(self, target_S: float, max_steps: int = 200) -> dict[str, Any]:
        """Camina hasta S <= target_S (o hasta agotar los pasos).

        Devuelve {reached, S, metrics, ops, steps_used, exhausted}.
        ``exhausted`` solo es True si TODAS las variables están en su
        piso y ya no hay operación válida: la frontera aritmética.
        """
        target = float(target_S)
        ops: list[str] = []
        used = 0
        if self.exhausted:
            reached = self.best_S is not None and self.best_S <= target
            return {"reached": bool(reached), "S": self.best_S,
                    "metrics": dict(self.best_metrics), "ops": ops,
                    "steps_used": 0, "exhausted": True}
        exhausted = False
        for _ in range(int(max_steps)):
            # Si el mejor ya llega, no hay nada que caminar.
            if self.best_S is not None and self.best_S <= target:
                break
            # Cerca del objetivo (<= 1.5x) solo pasos finos: un salto
            # grande aquí es lo que hacía saltar la GM de 30 a 38.
            fine = (self.best_S is not None
                    and self.best_S <= 1.5 * target)
            tried = 0
            moved = False
            # Salta operaciones inválidas (bajo el piso, sin cambio, o
            # que violan un límite físico) sin gastar pasos.
            while tried < len(self.vars) * 12:
                op = self._next_op(fine)
                tried += 1
                cand = self._apply(self.metrics, op)
                if cand is None:
                    continue
                s = _s_of(self.task, cand)
                if s is None:
                    continue
                self.metrics = cand
                self.steps += 1
                used += 1
                moved = True
                if s < (self.best_S if self.best_S is not None
                        else float("inf")):
                    self.best_S = s
                    self.best_metrics = dict(cand)
                ops.append(op[0])
                self.ops_used.append(op[0])
                break
            if not moved:
                exhausted = True
                self.exhausted = True
                break
        reached = self.best_S is not None and self.best_S <= target
        return {
            "reached": bool(reached), "S": self.best_S,
            "metrics": dict(self.best_metrics), "ops": ops,
            "steps_used": used, "exhausted": exhausted,
        }

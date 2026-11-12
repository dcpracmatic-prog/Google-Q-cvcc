"""AUTO_MVP — mutador autónomo: el proponente que el lazo no tenía (desde v1.1.0).

Estrategias (familias D y K de la materia prima de Arturo):
- morph: una regla MORPH con evidencia medida (morph_tunnel).
- window: ventana SA (sa_windows.py) — reordena una sub-ventana de
  hijos para satisfacer el orden que exige una regla, y la aplica.
  Solo se propone si la regla aplica después del reorden.
- tunnel: salto Lévy (motor_tunelamiento.py) — explora una regla
  lejana (no la greedy) con probabilidad de cola pesada (Cauchy):
  casi siempre el mejor movimiento, a veces uno mucho peor.
- mwis: resuelve los conflictos entre mutaciones propuestas con
  MWIS (LOGIC_CORE v4): el subconjunto compatible de máxima
  ganancia total.

El mutador es un generador de candidatos en el formato del
pipeline (meta, metrics, kind, name, call_graph, source). La
aceptación interna sigue simulated annealing: la temperatura decae
de temp_start a temp_end y un candidato peor se acepta con
probabilidad exp(-(S_nuevo - S_actual) / S_actual / temp). El
candidato se YIELD igual (el pipeline decide la promoción con el
proxy y la puerta); el SA solo controla desde qué grafo muta la
siguiente iteración. El mutador nunca inventa un costo: cada
mutación lleva el delta_T medido de su regla, y el eps_plus (o el
rel_error / lambda_eff) se hereda de la semilla, nunca se toca.
"""
from __future__ import annotations

import copy
import math
import random
from dataclasses import dataclass, field
from typing import Any, Iterable

from .morph_tunnel import RULES, ReplacementRule, tunnel as morph_tunnel
from .mwis import solve_mwis
from .proxy import CandidateMeta, estimate_S
from .qualtran_bridge import CallGraph

# Tareas y las claves de métrica que el mutador actualiza (T/Q).
# El resto (eps_plus, rel_error, lambda_eff) se hereda de la semilla.
_TQ_KEYS = {
    "dqi": ("Q", "T"),
    "invsqrt": ("Q", "t_count"),
    "dfthcsos": ("Qtot", "Ttot"),
}


def _cauchy(rng: random.Random) -> float:
    """Un paso de cola pesada (Cauchy): casi siempre chico, a veces grande."""
    u = rng.random()
    if u <= 0.0:
        u = 1e-12
    if u >= 1.0:
        u = 1.0 - 1e-12
    return math.tan(math.pi * (u - 0.5))


@dataclass
class Mutation:
    """Una mutación propuesta sobre un grafo (con su delta medido)."""

    strategy: str
    rule_name: str
    delta_T: float
    touches: frozenset = frozenset()
    graph: CallGraph | None = None
    description: str = ""


def _metrics_for(task: str, base: dict[str, Any],
                 graph: CallGraph) -> dict[str, Any]:
    """Las métricas de la semilla con el T/Q del grafo mutado."""
    m = dict(base)
    tq = _TQ_KEYS.get(task, ("Q", "T"))
    total_T = graph.total_T()
    total_Q = graph.total_Q()
    if total_T is not None:
        m[tq[1]] = float(total_T)
    if total_Q is not None:
        m[tq[0]] = float(total_Q)
    return m


def _s_estimate(task: str, metrics: dict[str, Any]) -> float | None:
    """El S estimado del proxy para unas métricas (None si no se puede)."""
    try:
        return float(estimate_S(CandidateMeta(task=task, metrics=metrics)))
    except Exception:
        return None


def _apply_rule(graph: CallGraph, rule: ReplacementRule) -> CallGraph | None:
    """Aplica una regla con el túnel MORPH; None si no baja el T."""
    res = morph_tunnel(graph, [rule], method="greedy")
    if not res.moves or res.final_T is None or res.baseline_T is None:
        return None
    if res.final_T >= res.baseline_T:
        return None
    return res.graph


def _reorder_for_rule(graph: CallGraph,
                      rule: ReplacementRule) -> CallGraph | None:
    """Ventana SA: reordena los hijos del bloque que contiene a y b
    para satisfacer el orden que exige la regla. Devuelve el grafo
    reordenado si el orden cambió, o None si ya estaba bien / no aplica."""
    if rule.requires_order is None:
        return None
    a, b = rule.requires_order
    new = copy.deepcopy(graph)

    def _reorder(block: Any) -> bool:
        names = [c.name for c, _ in block.children]
        if a in names and b in names and names.index(a) > names.index(b):
            # Mueve a antes de b dentro de la ventana (los hijos entre
            # ambos se desplazan, el resto no se toca).
            ia, ib = names.index(a), names.index(b)
            item = block.children.pop(ia)
            block.children.insert(ib, item)
            return True
        for child, _ in block.children:
            if _reorder(child):
                return True
        return False

    return new if _reorder(new.root) else None


class Mutator:
    """El proponente autónomo: genera candidatos mutando la semilla.

    ``seed_graph`` es el CallGraph base (o su dict) y ``base_metrics``
    las métricas de la semilla (Q, T, eps_plus...). ``rules`` es el
    registro de reglas MORPH con evidencia (por defecto RULES).
    """

    STRATEGIES = ("morph", "window", "tunnel", "mwis")

    def __init__(self, seed_graph: CallGraph | dict[str, Any], task: str,
                 base_metrics: dict[str, Any],
                 rules: list[ReplacementRule] | None = None,
                 seed: int = 42, tunnel_prob: float = 0.03,
                 temp_start: float = 0.6, temp_end: float = 0.15,
                 horizon: int = 100):
        self.task = task
        self.base_metrics = dict(base_metrics)
        self.rules = list(rules) if rules is not None else list(RULES)
        self.rng = random.Random(seed)
        self.tunnel_prob = float(tunnel_prob)
        self.temp_start = float(temp_start)
        self.temp_end = float(temp_end)
        self.horizon = max(1, int(horizon))
        self.seed_graph = (seed_graph if isinstance(seed_graph, CallGraph)
                           else CallGraph.from_dict(seed_graph))
        self.current = copy.deepcopy(self.seed_graph)
        self.best = copy.deepcopy(self.seed_graph)
        self.best_S = _s_estimate(task, _metrics_for(
            task, self.base_metrics, self.seed_graph))
        self.weights = {s: 1.0 for s in self.STRATEGIES}
        self.iteration = 0
        self.history: list[dict[str, Any]] = []

    # -- temperatura SA (decae geométricamente en el horizonte) --
    def _temperature(self) -> float:
        frac = min(1.0, self.iteration / self.horizon)
        return self.temp_start * (self.temp_end / self.temp_start) ** frac

    # -- las cuatro estrategias --
    def _morph_moves(self, graph: CallGraph) -> list[Mutation]:
        moves = []
        for rule in self.rules:
            new = _apply_rule(graph, rule)
            if new is None:
                continue
            moves.append(Mutation(
                strategy="morph", rule_name=rule.name,
                delta_T=float(new.total_T() - graph.total_T()),
                touches=frozenset({rule.target}),
                graph=new,
                description=f"{rule.name}: {rule.replacement}"))
        return moves

    def _window_moves(self, graph: CallGraph) -> list[Mutation]:
        moves = []
        for rule in self.rules:
            reordered = _reorder_for_rule(graph, rule)
            if reordered is None:
                continue
            new = _apply_rule(reordered, rule)
            if new is None:
                continue
            moves.append(Mutation(
                strategy="window", rule_name=rule.name,
                delta_T=float(new.total_T() - graph.total_T()),
                touches=frozenset({rule.target}),
                graph=new,
                description=(f"ventana: reordenar para {rule.name} "
                             f"({rule.requires_order})")))
        return moves

    def _tunnel_moves(self, graph: CallGraph) -> list[Mutation]:
        """Salto Lévy: elige una regla por rango de cola pesada (Cauchy).
        Casi siempre la mejor; a veces una mucho peor (exploración)."""
        moves = self._morph_moves(graph)
        if not moves:
            return []
        moves.sort(key=lambda m: m.delta_T)  # mejor (más negativo) primero
        jump = abs(_cauchy(self.rng))
        idx = min(len(moves) - 1, int(jump))
        chosen = moves[idx]
        chosen.strategy = "tunnel"
        chosen.description = (f"salto Lévy (rango {idx}/{len(moves)}): "
                              f"{chosen.rule_name}")
        return [chosen]

    def _mwis_moves(self, graph: CallGraph) -> list[Mutation]:
        """Resuelve los conflictos entre las reglas que aplican con
        MWIS y las aplica en secuencia (cada una debe seguir bajando T)."""
        moves = self._morph_moves(graph)
        if len(moves) < 2:
            return moves
        # Conflicto: dos reglas tocan el mismo bloque objetivo.
        # solve_mwis trabaja con índices (lista de adyacencia + pesos).
        n = len(moves)
        adj: list[set[int]] = [set() for _ in range(n)]
        for i, a in enumerate(moves):
            for j in range(i + 1, n):
                if a.touches & moves[j].touches:
                    adj[i].add(j)
                    adj[j].add(i)
        weights = [max(0.0, -m.delta_T) for m in moves]
        chosen_idx = solve_mwis(adj, weights, method="greedy",
                                seed=self.rng.randint(0, 2 ** 31))
        if not chosen_idx:
            return []
        chosen = [moves[i].rule_name for i in sorted(chosen_idx)]
        by_name = {m.rule_name: m for m in moves}
        # Aplica las elegidas en secuencia sobre el grafo.
        cur = copy.deepcopy(graph)
        applied: list[str] = []
        for name in chosen:
            rule = next(r for r in self.rules if r.name == name)
            new = _apply_rule(cur, rule)
            if new is None:
                continue
            cur = new
            applied.append(name)
        if not applied:
            return []
        return [Mutation(
            strategy="mwis", rule_name="+".join(applied),
            delta_T=float(cur.total_T() - graph.total_T()),
            touches=frozenset().union(*[by_name[n].touches for n in applied]),
            graph=cur,
            description=f"MWIS: {' + '.join(applied)}")]

    def _pick_strategy(self) -> str:
        total = sum(self.weights.values())
        x = self.rng.random() * total
        for s in self.STRATEGIES:
            x -= self.weights[s]
            if x <= 0:
                return s
        return self.STRATEGIES[-1]

    def _propose_one(self) -> Mutation | None:
        """Una mutación con la estrategia elegida (adaptativa)."""
        strategy = self._pick_strategy()
        if strategy == "morph":
            moves = self._morph_moves(self.current)
        elif strategy == "window":
            moves = self._window_moves(self.current)
        elif strategy == "tunnel":
            moves = self._tunnel_moves(self.current)
        else:
            moves = self._mwis_moves(self.current)
        if not moves:
            # Sin movimientos de esa estrategia: cae a morph.
            moves = self._morph_moves(self.current)
            strategy = "morph"
        if not moves:
            return None
        # Dentro de la estrategia, el mejor delta (el túnel ya eligió).
        best = min(moves, key=lambda m: m.delta_T)
        best.strategy = strategy
        return best

    def propose(self, n: int = 10) -> Iterable[dict[str, Any]]:
        """Genera hasta n candidatos en el formato del pipeline."""
        for i in range(int(n)):
            self.iteration += 1
            move = self._propose_one()
            if move is None or move.graph is None:
                continue
            metrics = _metrics_for(self.task, self.base_metrics, move.graph)
            s_est = _s_estimate(self.task, metrics)
            # Aceptación SA: el grafo actual avanza (o no) por temperatura.
            temp = self._temperature()
            if s_est is not None and self.best_S is not None:
                if s_est < self.best_S:
                    self.best = copy.deepcopy(move.graph)
                    self.best_S = s_est
                    self.weights[move.strategy] *= 1.1
                elif self.rng.random() < math.exp(
                        -(s_est - self.best_S) / max(self.best_S, 1e-12) / temp):
                    self.current = copy.deepcopy(move.graph)
                else:
                    self.weights[move.strategy] *= 0.95
            elif s_est is not None:
                self.current = copy.deepcopy(move.graph)
            candidate = {
                "meta": CandidateMeta(task=self.task, metrics=dict(metrics)),
                "metrics": metrics,
                "kind": "candidate",
                "name": f"mut:{move.strategy}:{move.rule_name}:{i}",
                "call_graph": move.graph.to_dict(),
                "source": {"mutator": "v1.1.0", "strategy": move.strategy,
                           "rule": move.rule_name,
                           "description": move.description,
                           "delta_T": move.delta_T,
                           "temperature": temp},
                "integrity": None,
            }
            self.history.append({
                "iteration": self.iteration, "strategy": move.strategy,
                "rule": move.rule_name, "delta_T": move.delta_T,
                "S_estimate": s_est, "temperature": temp})
            yield candidate

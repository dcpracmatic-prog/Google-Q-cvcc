"""AUTO_MVP v0.5.0 — núcleo MWIS (LOGIC_CORE v4 de Arturo).

Port fiel del núcleo de LOGIC_CORE v4 (``LOGIC_CORE_v4_OPTIMIZADO``):
conjunto independiente de peso máximo (MWIS) sobre el grafo de
conflictos. Las funciones son las del notebook, verbatim en lógica
(``greedy_mwis``, ``one_to_two_improve``, ``solve_mwis``,
``exact_mwis``, ``is_independent``, ``total_weight``,
``classify_states``); solo cambia que los pesos son listas stdlib
en vez de arrays numpy. El núcleo no toca hardware ni ejecución:
lee la salida (el grafo y las ganancias) y reporta la selección.

Uso en este repo: la selección de mutaciones. Antes se usaba MIS
sin peso (``greedy_mis`` de maxcut.py, que solo maximiza cuántas
mutaciones entran); ahora se usa MWIS con peso = ganancia en S
(``dS``): maximiza la ganancia total del conjunto, no su tamaño.
Solo entran nodos con ganancia positiva (una mutación que empeora
el S nunca ayuda a una combinación: solo añade conflictos).
``protected`` son los nodos que deben entrar primero (por peso).
"""
from __future__ import annotations

import random
from itertools import combinations


def is_independent(adj, selected):
    selected = set(selected)
    for i in selected:
        if adj[i] & selected:
            return False
    return True


def total_weight(selected, weights):
    return float(sum(weights[i] for i in selected))


def build_conflict_graph(points, conflict_fn):
    n = len(points)
    adj = [set() for _ in range(n)]
    for i, j in combinations(range(n), 2):
        if conflict_fn(points[i], points[j]):
            adj[i].add(j)
            adj[j].add(i)
    return adj


def add_reference_nodes(obs_points, references, conflict_fn):
    points = list(obs_points) + list(references)
    n_obs = len(obs_points)
    adj = build_conflict_graph(points, conflict_fn)
    ref_ids = list(range(n_obs, len(points)))
    return adj, ref_ids


def greedy_mwis(adj, weights, protected=None, randomized=False, seed=42):
    n = len(adj)
    protected = set(protected) if protected else set()
    selected = set()

    def score(i):
        return weights[i] / (1 + len(adj[i]))

    for i in sorted(protected, key=lambda i: -weights[i]):
        if not (adj[i] & selected):
            selected.add(i)
    remaining = [i for i in range(n) if i not in selected]
    if randomized:
        rnd = random.Random(seed)
        scored = [(score(i), i) for i in remaining]
        rnd.shuffle(scored)
        scored.sort(key=lambda t: -t[0])
        order = [i for _, i in scored]
    else:
        order = sorted(remaining, key=lambda i: -score(i))
    for i in order:
        if not (adj[i] & selected):
            selected.add(i)
    return selected


def one_to_two_improve(adj, weights, selected):
    selected = set(selected)
    changed = True
    while changed:
        changed = False
        rejected = set(range(len(adj))) - selected
        for v in list(selected):
            others = selected - {v}
            candidates = [u for u in rejected if not (adj[u] & others)]
            for u, x in combinations(candidates, 2):
                if x in adj[u]:
                    continue
                if weights[u] + weights[x] > weights[v]:
                    selected.remove(v)
                    selected.update([u, x])
                    changed = True
                    break
            if changed:
                break
    return selected


def solve_mwis(adj, weights, method="greedy", protected=None, seed=42):
    s = greedy_mwis(adj, weights, protected=protected,
                    randomized=(method == "randomized"), seed=seed)
    if method == "local":
        s = one_to_two_improve(adj, weights, s)
    assert is_independent(adj, s), "Local improvement produced a non-independent set."
    return s


def classify_states(adj, selected, ref_ids):
    selected, ref_ids = set(selected), set(ref_ids)
    states = {}
    for i in range(len(adj)):
        if i in ref_ids:
            states[i] = "REFERENCE"
            continue
        conflicts_with_ref = bool(adj[i] & ref_ids)
        states[i] = "REJECT" if conflicts_with_ref else (
            "PASS" if i in selected else "REVIEW")
    return states


def exact_mwis(adj, weights):
    n = len(adj)
    best_set, best_w = set(), -float("inf")
    for mask in range(1 << n):
        s = {i for i in range(n) if mask & (1 << i)}
        if is_independent(adj, s):
            w = total_weight(s, weights)
            if w > best_w:
                best_w, best_set = w, s
    return best_set

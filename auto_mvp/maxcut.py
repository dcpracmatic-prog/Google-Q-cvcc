"""AUTO_MVP v0.4.0 — MaxCut (port fiel del programa C++ de Arturo).

El programa original (``examples/maxcut_reference.cpp``, pegado por
Arturo el 2026-11-11, guardado verbatim) resuelve MaxCut con dos
piezas:

- ``exact``: enumeración por código Gray con ganancias incrementales
  (todos los 2^n estados; n=24 son 16,777,216 estados, 2.69 s en C++).
- ``morph``: restarts aleatorios + intensificación por mejor flip
  (repetir el flip de mayor ganancia > 1e-12) + diversificación por
  perturbación aleatoria de n/4 variables. En n=24 seed=101:
  exact_best=76.3397044423, morph_best=76.3397044422, gap 9.95e-11,
  certificate_exact=PASS (reproducido con g++ -O2).

Este módulo es el MISMO algoritmo en Python (solo stdlib). Dos
diferencias honestas: el generador usa ``random.Random`` (el C++
usa mt19937_64), así que los grafos generados NO son los mismos y
los números 76.3397... pertenecen al flujo del C++, no al port; y
el ``exact`` en Python es lento para n=24 (16.7M de estados), así
que el certificado exacto en Python se usa hasta n<=20 y el C++ es
la referencia para n=24.

PARA QUÉ SIRVE EN EL PIPELINE (su engrane real): el grafo de
conflictos de mutaciones (Notebook 1: 13 nodos, 31 aristas) se
parte con MaxCut en dos lados que maximizan el peso de los
conflictos ENTRE ellos. Dentro de cada lado quedan pocos conflictos,
así que el MIS voraz (MORPH v1.5, grado residual mínimo) encuentra
en cada lado un conjunto grande y compatible. Es divide y vencerás
sobre el espacio de mutaciones, con certificado exacto cuando
n<=20 (nuestro grafo tiene 12 nodos válidos; K_b36_nofix está
rechazado por el contrato y NO entra en la partición).
El peso de una arista (a, b) es |ganancia_a| + |ganancia_b| (las
ganancias dS medidas/proyectadas del Notebook 1); sin pesos, vale 1.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

EXACT_MAX_N = 20
CERT_TOL = 1e-9


def make_graph(n: int, seed: int = 101, p: float = 0.35) -> list[list[float]]:
    """Grafo aleatorio como el C++: arista con prob. p, peso U(0.2, 2.0)."""
    rng = random.Random(seed)
    w = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if rng.random() < p:
                v = rng.uniform(0.2, 2.0)
                w[i][j] = w[j][i] = v
    return w


def cut_value(w: list[list[float]], x: list[int]) -> float:
    """Corte ingenuo (para verificar el exacto): suma w[i][j] con x[i]!=x[j]."""
    n = len(w)
    return sum(w[i][j] for i in range(n) for j in range(i + 1, n)
               if x[i] != x[j])


def _gains(w: list[list[float]], x: list[int]) -> list[float]:
    n = len(w)
    return [sum(w[i][j] * (1.0 if x[j] == x[i] else -1.0)
                for j in range(n) if j != i) for i in range(n)]


def exact(w: list[list[float]]) -> tuple[float, list[int]]:
    """Máximo corte exacto por código Gray, como el C++.

    Recorre los 2^n estados volteando un solo bit por paso (ctz del
    contador) y actualiza el corte con la ganancia incremental.
    Devuelve (mejor_corte, asignación). Lento en Python para n>20.
    """
    n = len(w)
    if n > 24:
        raise ValueError(f"exact no soporta n={n} (>24 estados inmanejables)")
    x = [-1] * n
    gain = _gains(w, x)
    c = cut_value(w, x)
    best, bx = c, list(x)
    for k in range(1, 1 << n):
        b = (k & -k).bit_length() - 1  # ctz(k): el bit que cambia
        dc = gain[b]
        x[b] = -x[b]
        c += dc
        gain[b] = -gain[b]
        for j in range(n):
            if j != b:
                gain[j] += 2.0 * w[j][b] if x[j] == x[b] else -2.0 * w[j][b]
        if c > best:
            best, bx = c, list(x)
    return best, bx


def morph(w: list[list[float]], seed: int = 101, restarts: int = 64,
          steps: int = 5000) -> tuple[float, list[int], int]:
    """Heurístico 'morph' del C++: restarts + mejor flip + perturbación.

    Por restart: asignación aleatoria; intensificación = voltear
    repetidamente la variable de mayor ganancia (>1e-12);
    diversificación = perturbar n/4 variables al azar. Devuelve
    (mejor_corte, asignación, flips_totales).
    """
    n = len(w)
    rng = random.Random(seed)
    best, bx, evals = -1.0, [1] * n, 0
    for _ in range(restarts):
        x = [1 if rng.random() < 0.5 else -1 for _ in range(n)]
        gain = _gains(w, x)
        c = cut_value(w, x)
        if c > best:
            best, bx = c, list(x)
        for _ in range(steps):
            bi = max(range(n), key=lambda i: gain[i])
            if gain[bi] <= 1e-12:
                break
            x[bi] = -x[bi]
            c += gain[bi]
            gain[bi] = -gain[bi]
            for j in range(n):
                if j != bi:
                    gain[j] += 2.0 * w[j][bi] if x[j] == x[bi] else -2.0 * w[j][bi]
            evals += 1
            if c > best:
                best, bx = c, list(x)
        for _ in range(n // 4):
            i = rng.randrange(n)
            x[i] = -x[i]
    return best, bx, evals


@dataclass
class Partition:
    side_a: list[str]
    side_b: list[str]
    cut_weight: float
    total_weight: float
    certificate: str  # "EXACT" (n<=20) o "HEURISTIC"
    gap: float
    method: str

    def as_dict(self) -> dict:
        return {"side_a": list(self.side_a), "side_b": list(self.side_b),
                "cut_weight": self.cut_weight,
                "total_weight": self.total_weight,
                "certificate": self.certificate, "gap": self.gap,
                "method": self.method}


def partition_conflict_graph(nodes: list[str],
                             edges: list[tuple],
                             seed: int = 101) -> Partition:
    """Parte el grafo de conflictos con MaxCut.

    ``edges``: (a, b) o (a, b, peso). Sin peso, vale 1. Los nodos que
    no pasan el contrato (p. ej. K_b36_nofix) NO se incluyen: la
    partición corre sobre los candidatos válidos. Con n<=20 el
    certificado es EXACT (morph == exact, gap < 1e-9); si no, el
    heurístico con su gap reportado (sin certificado).
    """
    idx = {name: i for i, name in enumerate(nodes)}
    n = len(nodes)
    w = [[0.0] * n for _ in range(n)]
    for e in edges:
        a, b = e[0], e[1]
        weight = float(e[2]) if len(e) > 2 else 1.0
        i, j = idx[a], idx[b]
        w[i][j] = w[j][i] = weight
    total = sum(w[i][j] for i in range(n) for j in range(i + 1, n))
    if n <= EXACT_MAX_N:
        best_e, xe = exact(w)
        best_m, xm, _ = morph(w, seed=seed ^ 0x9E3779B97F4A7C15)
        gap = abs(best_e - best_m)
        cert = "EXACT" if gap < CERT_TOL else "MISMATCH"
        x = xe if best_e >= best_m else xm
        method = "exact+morph"
    else:
        best_m, xm, _ = morph(w, seed=seed ^ 0x9E3779B97F4A7C15)
        gap = float("nan")
        cert = "HEURISTIC"
        x = xm
        method = "morph"
    cut = cut_value(w, x)
    side_a = [nodes[i] for i in range(n) if x[i] == 1]
    side_b = [nodes[i] for i in range(n) if x[i] == -1]
    return Partition(side_a=side_a, side_b=side_b, cut_weight=cut,
                     total_weight=total, certificate=cert, gap=gap,
                     method=method)


def greedy_mis(nodes: list[str], edges: list[tuple]) -> list[str]:
    """MIS voraz (construcción MORPH v1.5: grado residual mínimo).

    Repite: toma el vértice activo de menor grado residual, lo suma
    al conjunto y elimina a él y a sus vecinos activos. Es la
    heurística del repo MORPH, no un exacto.
    """
    adj: dict[str, set[str]] = {name: set() for name in nodes}
    for e in edges:
        adj[e[0]].add(e[1])
        adj[e[1]].add(e[0])
    active = set(nodes)
    chosen: list[str] = []
    while active:
        # Orden determinista (sorted) para desempatar: mismo resultado
        # en cada corrida.
        v = min(sorted(active), key=lambda u: len(adj[u] & active))
        chosen.append(v)
        active -= {v} | (adj[v] & active)
    return chosen


def partition_then_select(nodes: list[str], edges: list[tuple],
                          seed: int = 101) -> dict:
    """MaxCut + MIS voraz por lado. Devuelve la partición y los dos MIS."""
    part = partition_conflict_graph(nodes, edges, seed=seed)
    edge_set = {(e[0], e[1]) for e in edges} | {(e[1], e[0]) for e in edges}

    def sub_edges(side: list[str]) -> list[tuple]:
        s = set(side)
        return [(a, b) for (a, b) in edge_set if a in s and b in s and a < b]

    return {"partition": part.as_dict(),
            "mis_a": greedy_mis(part.side_a, sub_edges(part.side_a)),
            "mis_b": greedy_mis(part.side_b, sub_edges(part.side_b))}

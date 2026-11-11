"""Detector reorientado (antes detect.py contaba errores HTTP).

Ahora vigila dos cosas en una búsqueda de circuitos:
1. Invariantes rotas: el candidato no pasa el contrato de su tarea.
2. Costo empeorado o estancamiento: S no baja del mejor visto en N
   intentos seguidos (el "estancamiento" que debe disparar una nueva
   propuesta, estilo MORPH: si el camino no mejora, cambia de camino).

v0.2.1-vqcc (ideas de los archivos DSP de Arturo):
- Umbral adaptativo por mediana móvil (hard_dsp v9: el umbral fijo
  14.9 estaba congelado porque no tenía sentido en la escala de la
  carga). Aquí la mejora solo cuenta si baja S más que `margin`
  (derivado de la calibración de arranque, calibrate.py): S tiene
  escala ~1e12, así que una baja de 0.001% es ruido del paisaje, no
  una mejora. Con margin=0 el comportamiento es el viejo.
- La mediana móvil del historial (_history, que ya existía) es la
  referencia del lazo: `median_S` y la firma de salud `health()`.
- Los S no finitos (inf de un candidato rechazado por contrato, NaN)
  NO entran al historial: contaminarían la mediana y la salud.
"""
from __future__ import annotations

import math
import statistics
from collections import deque
from dataclasses import dataclass, field
from typing import Deque

from .contracts import CircuitSpec

# Pesos de la salud del lazo, los mismos que TERM_U del DSP v9/v10
# (0.60*C + 0.28*B + 0.05*G + 0.07*A). Son pesos de arranque, no del
# contrato: la salud solo gobierna el modo del lazo, nunca el circuito.
HEALTH_WEIGHTS = {"C": 0.60, "B": 0.28, "G": 0.05, "A_adapt": 0.07}


@dataclass
class CircuitDetector:
    spec: CircuitSpec
    stagnation_limit: int = 5  # intentos sin mejorar -> estancado
    best_S: float = float("inf")
    trials: int = 0
    trials_since_improvement: int = 0
    margin: float = 0.0  # mejora mínima relativa para contar (calibración)
    _history: Deque[float] = field(default_factory=lambda: deque(maxlen=50))

    def __post_init__(self) -> None:
        # El punto de partida es el mejor propio medido, no infinito:
        # si no, el primer intento (peor que el baseline) contaría
        # como "mejora" y el estancamiento no se detectaría.
        if self.best_S == float("inf") and self.spec.baseline_S != float("inf"):
            self.best_S = self.spec.baseline_S
        if not 0.0 <= self.margin <= 0.25:
            raise ValueError(f"margin debe estar en [0, 0.25], no {self.margin!r}")

    @property
    def median_S(self) -> float | None:
        """Mediana móvil de los S finitos observados, o None si no hay."""
        if not self._history:
            return None
        return statistics.median(self._history)

    def health(self) -> dict | None:
        """Firma de salud del lazo [C, B, G, A_adapt] + salud ponderada.

        Misma forma que TERM_U del DSP: C estabilidad (var de S
        relativo al mejor), B cercanía (mediana del S relativo al
        mejor), G suavidad (saltos entre intentos), A_adapt cola
        (p99-p95 de los S relativos). Devuelve None con menos de 3
        puntos: no hay suficiente historia para hablar de salud.
        La salud solo gobierna el modo del lazo (search.py); nunca
        decide si un candidato pasa el contrato.
        """
        if len(self._history) < 3 or self.best_S <= 0:
            return None
        rel = [s / self.best_S for s in self._history]
        var_r = statistics.pvariance(rel) if len(rel) > 1 else 0.0
        c = 1.0 / (1.0 + var_r)
        b = math.exp(-abs(statistics.median(rel) - 1.0))
        diffs = [abs(rel[i + 1] - rel[i]) for i in range(len(rel) - 1)]
        g = 1.0 / (1.0 + (sum(diffs) / len(diffs) if diffs else 0.0))
        ordered = sorted(rel)
        n = len(ordered)
        p95 = ordered[min(n - 1, int(0.95 * (n - 1)))]
        p99 = ordered[min(n - 1, int(0.99 * (n - 1)))]
        a = math.exp(-abs(p99 - p95) / (p95 + 1e-9)) if p95 >= 1e-12 else 1.0
        signature = {"C": c, "B": b, "G": g, "A_adapt": a}
        score = sum(HEALTH_WEIGHTS[k] * signature[k] for k in HEALTH_WEIGHTS)
        return {"signature": signature, "health": score}

    def observe(self, S: float, contract_failures: list[str]) -> dict:
        """Registra un intento. Devuelve qué se detectó."""
        self.trials += 1
        # Solo S finitos y > 0 entran al historial: un S=inf (rechazado
        # por contrato) o negativo (fórmula R fuera de dominio con
        # eps+ >= 1/16) no es un costo, contaminaría mediana y salud.
        if math.isfinite(S) and S > 0:
            self._history.append(S)
        broken = bool(contract_failures)
        # Una mejora solo cuenta si baja S más que el margen: con
        # S ~ 1e12, una baja de 0.001% es ruido del paisaje. Un S
        # negativo (fórmula R fuera de dominio con eps+ >= 1/16) nunca
        # es una mejora: no es un costo válido.
        improved = (not broken) and math.isfinite(S) and S > 0 and S < self.best_S * (1 - self.margin)
        if improved:
            self.best_S = S
            self.trials_since_improvement = 0
        else:
            self.trials_since_improvement += 1
        stagnated = self.trials_since_improvement >= self.stagnation_limit
        h = self.health()
        return {
            "broken_invariant": broken,
            "failures": contract_failures,
            "improved": improved,
            "best_S": self.best_S,
            "trials_since_improvement": self.trials_since_improvement,
            "stagnated": stagnated,
            "should_propose": broken or stagnated or improved is False,
            "median_S": self.median_S,
            "margin": self.margin,
            "health": h["health"] if h else None,
            "health_signature": h["signature"] if h else None,
        }

    def reset(self) -> None:
        self.trials = 0
        self.trials_since_improvement = 0
        self._history.clear()

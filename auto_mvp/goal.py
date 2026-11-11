"""AUTO_MVP v0.3.0 — meta porcentual con regla de paro (fase 5).

La especificación pide definir metas porcentuales y escalar el tiempo
de cómputo "de forma proporcional". Aquí eso es concreto y acotado:

- La meta es un S objetivo o un porcentaje de mejora sobre el
  baseline (por ejemplo +50% significa S <= baseline / 1.5; la
  mejora se mide en S, no en Q: bajar Q un 74.8% no es mejorar el
  puntaje un 74.8%).
- El presupuesto crece SOLO mientras haya mejoras reales y nunca pasa
  de ``max_trials``: cada mejora aceptada suma ``growth_per_hit``
  intentos. Sin mejoras, el presupuesto no crece.
- La regla de paro es explícita y tiene motivo: meta alcanzada,
  paciencia agotada (N intentos sin mejorar), presupuesto agotado o
  plazo vencido. Nada de "entrenar hasta que se estabilice" sin
  números.

El estado del ciclo (intentos, mejoras, mejor S, inicio) vive en
``GoalState``; la meta en sí es inmutable.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Goal:
    """Meta y regla de paro. Una de las dos formas de meta es obligatoria.

    target_S: S objetivo (menor es mejor). Si se pasa, manda sobre
        improvement_pct.
    improvement_pct: porcentaje de mejora sobre baseline_S (ej. 50.0
        significa S <= baseline_S / 1.5).
    baseline_S: S del baseline verificado del que se parte.
    max_trials: techo duro de intentos (el presupuesto adaptativo no
        lo supera).
    base_trials: intentos iniciales antes de que las mejoras los amplíen.
    growth_per_hit: intentos extra por cada mejora aceptada.
    patience: intentos seguidos sin mejorar antes de parar.
    min_improvement: mejora mínima en S para contar como mejora (por
        defecto 0: cualquier baja cuenta; con calibración, usar el
        margen para no perseguir ruido).
    deadline_seconds: plazo máximo en segundos (None = sin plazo).
    """
    baseline_S: float
    target_S: float | None = None
    improvement_pct: float | None = None
    max_trials: int = 20
    base_trials: int = 10
    growth_per_hit: int = 2
    patience: int = 5
    min_improvement: float = 0.0
    deadline_seconds: float | None = None

    def __post_init__(self):
        if self.target_S is None and self.improvement_pct is None:
            raise ValueError("hay que pasar target_S o improvement_pct")
        if self.max_trials < 1 or self.base_trials < 1:
            raise ValueError("trials debe ser >= 1")
        if self.patience < 1:
            raise ValueError("patience debe ser >= 1")

    @property
    def effective_target(self) -> float:
        if self.target_S is not None:
            return float(self.target_S)
        assert self.improvement_pct is not None
        return self.baseline_S / (1.0 + self.improvement_pct / 100.0)

    def target_label(self) -> str:
        if self.target_S is not None:
            return f"S<={self.target_S:.6g}"
        return f"+{self.improvement_pct:.6g}% (S<={self.effective_target:.6g})"


@dataclass
class GoalState:
    trials: int = 0
    accepted: int = 0
    trials_since_improvement: int = 0
    best_S: float = float("inf")
    started_at: float = field(default_factory=time.monotonic)
    budget: int = 0  # intentos permitidos en total (crece con mejoras)

    def __post_init__(self):
        if self.budget == 0:
            self.budget = 0  # lo fija el orquestador con base_trials


class GoalTracker:
    """Sigue el estado frente a la meta y decide cuándo parar."""

    def __init__(self, goal: Goal):
        self.goal = goal
        self.state = GoalState(best_S=goal.baseline_S, budget=goal.base_trials)

    def observe(self, S: float, improved: bool) -> None:
        """Registra un intento. ``improved`` = S bajó más que el margen."""
        st = self.state
        st.trials += 1
        if improved and S < st.best_S - self.goal.min_improvement:
            st.best_S = S
            st.accepted += 1
            st.trials_since_improvement = 0
            st.budget = min(self.goal.max_trials,
                            st.budget + self.goal.growth_per_hit)
        else:
            st.trials_since_improvement += 1

    def should_stop(self) -> tuple[bool, str]:
        st = self.state
        if st.best_S <= self.goal.effective_target:
            return True, (f"meta alcanzada: S={st.best_S:.6g} <= "
                          f"{self.goal.effective_target:.6g}")
        if st.trials_since_improvement >= self.goal.patience:
            return True, (f"paciencia agotada: {st.trials_since_improvement} "
                          f"intentos sin mejorar (paciencia {self.goal.patience})")
        if st.trials >= st.budget:
            return True, (f"presupuesto agotado: {st.trials} intentos "
                          f"(techo {self.goal.max_trials})")
        if st.trials >= self.goal.max_trials:
            return True, f"techo de intentos: {self.goal.max_trials}"
        if self.goal.deadline_seconds is not None:
            elapsed = time.monotonic() - st.started_at
            if elapsed >= self.goal.deadline_seconds:
                return True, f"plazo vencido: {elapsed:.1f}s"
        return False, ""

    def progress(self) -> dict[str, object]:
        st = self.state
        return {
            "target": self.goal.target_label(),
            "trials": st.trials,
            "budget": st.budget,
            "accepted": st.accepted,
            "trials_since_improvement": st.trials_since_improvement,
            "best_S": st.best_S,
            "baseline_S": self.goal.baseline_S,
        }

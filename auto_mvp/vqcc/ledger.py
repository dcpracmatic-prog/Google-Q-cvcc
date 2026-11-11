"""Ledger reorientado (antes ledger.py: bitácora genérica en JSONL).

Ahora cada fila es un intento de búsqueda: qué mutación se probó,
qué puntaje S dio, si pasó el verificador oficial y si se aceptó.
Reutiliza el Ledger genérico de self_healing (sin duplicarlo).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from auto_mvp.healing.ledger import Ledger


class VQCCLedger(Ledger):
    def __init__(self, path: str | None = None, max_bytes: int | None = None):
        super().__init__(path=path, max_bytes=max_bytes)

    def trial(self, task: str, mutation: str, S: float, best_S: float,
              passed: bool, accepted: bool, verified_by: str = "",
              **extra: Any) -> None:
        self.log(
            "trial", task=task, mutation=mutation, S=S, best_S=best_S,
            passed=passed, accepted=accepted, verified_by=verified_by,
            **extra,
        )

    def stagnated(self, task: str, trials_since_improvement: int) -> None:
        self.log("stagnated", task=task,
                 trials_since_improvement=trials_since_improvement)

    def rolled_back(self, task: str, reason: str, best_S: float) -> None:
        self.log("rolled_back", task=task, reason=reason, best_S=best_S)

    def proposed(self, task: str, mutation: str, S: float) -> None:
        """Modo PROPOSE: el candidato se deja pendiente, no se aplica."""
        self.log("proposed", task=task, mutation=mutation, S=S)

    def mode_transition(self, task: str, from_mode: str, to_mode: str,
                        reason: str, health: float | None = None) -> None:
        """El veto de salud bajó el modo del lazo (AUTO->PROPOSE->SHADOW)."""
        self.log("mode_transition", task=task, from_mode=from_mode,
                 to_mode=to_mode, reason=reason, health=health)

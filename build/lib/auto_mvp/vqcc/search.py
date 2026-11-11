"""El lazo principal reorientado (antes heal.py: reparar una función).

Ahora es un motor de búsqueda autónomo, estilo MORPH:
- propone una mutación de parámetros (o de factorización),
- la verifica en local (cribado barato, oficial solo al finalista),
- la acepta solo si pasa el contrato Y baja el mejor S visto,
- si empeora o rompe invariantes, la descarta y hace rollback al mejor,
- si se estanca N intentos sin mejorar, lo registra y sigue proponiendo
  (el proponente decide el cambio de camino; el lazo no inventa
  mutaciones por su cuenta).

El proponente es un protocolo: recibe el spec, el mejor candidato y
la evidencia (fallos, historial) y devuelve un candidato nuevo.
Sin proponente no hay búsqueda; el lazo no propone solo.

v0.2.1-vqcc (ideas de los archivos DSP de Arturo):
- Calibración de arranque (calibrate.py): si se pasa una Calibration,
  el margen de aceptación, la paciencia y el presupuesto de intentos
  vienen medidos de la sonda, no puestos a mano.
- Veto de salud (hard_dsp v10: el veto térmico fuerza el modo ahorro
  sin importar el índice): si la salud del lazo (detect.health())
  cae bajo health_floor, o el verificador falla N veces seguidas, el
  modo baja un escalón: AUTO -> PROPOSE -> SHADOW. El veto se registra
  en el ledger como mode_transition. El modo solo gobierna al lazo:
  en SHADOW se sigue evaluando pero no se cambia nada; en PROPOSE la
  mejora se deja pendiente (proposed_best) sin aplicar; en AUTO se
  aplica como antes. Es la misma regla que el gobernador v9: actúa
  solo sobre su propio proceso, nunca sobre el circuito ni el
  verificador.
- best_verified_S: el mejor S con verificación OFICIAL completa, por
  separado del mejor proyectado (cribado de costo). El cribado guía
  la búsqueda; solo lo oficial corona un mejor verificado.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from auto_mvp.healing.heal import Autonomy

from .calibrate import Calibration
from .contracts import CircuitSpec
from .detect import CircuitDetector
from .ledger import VQCCLedger
from .verify import CircuitVerifyResult, LocalVerifier


class Mutator(Protocol):
    """Propone la siguiente mutación. Recibe spec, mejor candidato y evidencia."""
    def propose(self, spec: CircuitSpec, best: dict[str, Any] | None,
                evidence: dict[str, Any]) -> dict[str, Any]: ...


@dataclass
class SearchResult:
    best: dict[str, Any] | None
    best_S: float
    trials: int
    accepted: int
    rejected: int
    stagnated: bool
    ledger_events: list[str] = field(default_factory=list)
    # v0.2.1: mejor verificado oficial, modo final y transiciones de veto.
    best_verified_S: float = float("inf")
    proposed: dict[str, Any] | None = None
    autonomy: str = "auto"
    health: float | None = None
    mode_transitions: list[dict[str, Any]] = field(default_factory=list)


class SearchLoop:
    def __init__(self, spec: CircuitSpec, mutator: Mutator,
                 verifier: LocalVerifier | None = None,
                 ledger: VQCCLedger | None = None,
                 stagnation_limit: int | None = None,
                 max_trials: int | None = None,
                 calibration: Calibration | None = None,
                 autonomy: Autonomy = Autonomy.AUTO,
                 health_floor: float = 0.5,
                 max_consecutive_failures: int = 3):
        self.spec = spec
        self.mutator = mutator
        self.verifier = verifier or LocalVerifier(spec)
        self.ledger = ledger or VQCCLedger()
        self.calibration = calibration
        # La calibración manda si no se pasó el valor explícito.
        if stagnation_limit is None:
            stagnation_limit = calibration.stagnation_limit if calibration else 5
        if max_trials is None:
            max_trials = calibration.max_trials if calibration else 20
        margin = calibration.margin if calibration else 0.0
        self.detector = CircuitDetector(spec, stagnation_limit=stagnation_limit,
                                        margin=margin)
        # El mejor inicial es el baseline del spec (S propio medido).
        self.best: dict[str, Any] | None = None
        self.best_S: float = spec.baseline_S
        self.best_verified_S: float = float("inf")
        self.proposed: dict[str, Any] | None = None
        self.proposed_S: float = float("inf")
        self.detector.best_S = spec.baseline_S
        self.max_trials = max_trials
        self.accepted = 0
        self.rejected = 0
        self.autonomy = autonomy
        self.health_floor = health_floor
        self.max_consecutive_failures = max_consecutive_failures
        self._consecutive_failures = 0
        self.mode_transitions: list[dict[str, Any]] = []

    def _drop_mode(self, reason: str, health: float | None) -> None:
        """Baja un escalón de autonomía (AUTO -> PROPOSE -> SHADOW)."""
        order = [Autonomy.AUTO, Autonomy.PROPOSE, Autonomy.SHADOW]
        idx = order.index(self.autonomy)
        if idx >= len(order) - 1:
            return  # ya en SHADOW, no hay más abajo
        old = self.autonomy
        self.autonomy = order[idx + 1]
        transition = {"from": old.value, "to": self.autonomy.value,
                      "reason": reason, "health": health}
        self.mode_transitions.append(transition)
        self.ledger.mode_transition(self.spec.task, old.value,
                                    self.autonomy.value, reason, health=health)

    def run(self) -> SearchResult:
        for _ in range(self.max_trials):
            evidence = {
                "best_S": self.best_S,
                "best_verified_S": self.best_verified_S,
                "trials": self.detector.trials,
                "trials_since_improvement": self.detector.trials_since_improvement,
                "autonomy": self.autonomy.value,
                "health": self.detector.health(),
            }
            candidate = self.mutator.propose(self.spec, self.best, evidence)
            result = self.verifier.verify(candidate)
            S = result.S if math.isfinite(result.S) else float("inf")
            # El detector decide si rompió invariantes o si hay estancamiento.
            obs = self.detector.observe(
                S, result.failures if not result.ok else [])
            # Veto de salud: fallos seguidos del verificador, o salud baja.
            if result.ok:
                self._consecutive_failures = 0
            else:
                self._consecutive_failures += 1
            health = obs["health"]
            if self._consecutive_failures >= self.max_consecutive_failures:
                self._drop_mode(
                    f"verificador falló {self._consecutive_failures} veces seguidas",
                    health)
                self._consecutive_failures = 0
            elif health is not None and health < self.health_floor:
                self._drop_mode(f"salud del lazo {health:.3f} < {self.health_floor}",
                                health)
            # El mejor verificado oficial vive aparte del proyectado.
            if (result.verified_by == "official" and result.ok
                    and math.isfinite(S) and S < self.best_verified_S):
                self.best_verified_S = S
            accepted = result.ok and obs["improved"]
            if accepted:
                if self.autonomy is Autonomy.SHADOW:
                    # Solo observa: no cambia nada y no cuenta como
                    # aceptado ni rechazado (el detector sigue viendo
                    # la mejora para el estancamiento).
                    pass
                elif self.autonomy is Autonomy.PROPOSE:
                    # Pendiente de aprobación: no se aplica al mejor.
                    self.proposed = candidate
                    self.proposed_S = S
                    self.ledger.proposed(
                        self.spec.task,
                        str(candidate.get("mutation", candidate.get("name", "?"))), S)
                else:  # AUTO: se aplica como antes.
                    self.best = candidate
                    self.best_S = S
                    self.accepted += 1
            else:
                self.rejected += 1
                # Rollback: el mejor no cambia; se registra el descarte.
                self.ledger.rolled_back(
                    self.spec.task,
                    reason="; ".join(result.failures) or f"S={S:.6g} no mejora best={self.best_S:.6g}",
                    best_S=self.best_S,
                )
            self.ledger.trial(
                task=self.spec.task,
                mutation=str(candidate.get("mutation", candidate.get("name", "?"))),
                S=S, best_S=self.best_S, passed=result.ok,
                accepted=accepted and self.autonomy is Autonomy.AUTO,
                verified_by=result.verified_by,
                params=candidate.get("params", {}),
                autonomy=self.autonomy.value,
                health=health,
                best_verified_S=self.best_verified_S,
            )
            if obs["stagnated"]:
                self.ledger.stagnated(self.spec.task, obs["trials_since_improvement"])
                break
        final_health = self.detector.health()
        return SearchResult(
            best=self.best, best_S=self.best_S,
            trials=self.detector.trials, accepted=self.accepted,
            rejected=self.rejected,
            stagnated=self.detector.trials_since_improvement >= self.detector.stagnation_limit,
            ledger_events=self.ledger.events(),
            best_verified_S=self.best_verified_S,
            proposed=self.proposed,
            autonomy=self.autonomy.value,
            health=final_health["health"] if final_health else None,
            mode_transitions=self.mode_transitions,
        )

"""AUTO_MVP v0.3.0 — orquestador del ciclo de 5 fases (MVP).

El ciclo de la especificación v0.0.1, implementado sobre los
componentes v0.2.1 (que quedan intactos) con tres compuertas nuevas:

  [Ingesta] -> [Evaluación] -> [Auditoría] -> [Mutación + CVV]
  -> [Convergencia]

1. INGESTA: carga el baseline verificado, la meta (Goal) y la
   calibración. Registra el baseline en la cadena CVV (LOCKED_BASE).
2. EVALUACIÓN: el proxy de metadatos (si hay) criba la variante
   ANTES de construirla; el verificador local calcula el S oficial
   (nunca la suma ponderada de la spec: esa solo ordena en el proxy).
3. AUDITORÍA: el filtro de integridad revisa la evidencia del
   candidato (sigma, C/B, dreg/alpha, temporales). Un candidato con
   mejor S pero integridad rota se rechaza con veto_reason
   (la forma exacta del paso 51) y queda en la cadena CVV como
   REJECTED_REGRESSION. El veto de salud (v0.2.1) sigue vivo.
4. MUTACIÓN + CVV: cada mejora aceptada entra a la cadena CVV y,
   si está verificada (oficial + integridad), se congela de inmediato
   en el checkpoint. Lo proyectado sin verificar no toca el checkpoint.
5. CONVERGENCIA: la meta con regla de paro decide el final; el último
   récord CVV es MVP_CONVERGENCE con el mejor final.

El motor morfogenético y el decodificador JSON SÍ están aquí
(v0.6.0): su formalización algorítmica es Qualtran (Bloqs, grafo
de llamadas, T/Q de primera clase), en qualtran_bridge.py,
morph_tunnel.py, json_directive.py, step_plan.py y orchestrator.py.
Lo que queda fuera: el tensor TERM_U con atractor y el
entrenamiento algebraico implícito, que no tienen fórmula ni
algoritmo definidos.

El lazo es el mismo que SearchLoop.run() con las tres compuertas
(proxy, integridad, CVV+checkpoint). Se implementa aparte para no
tocar la v0.2.1; cuando las compuertas se estabilicen, ambos lazos
pueden unificarse.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from auto_mvp.healing.heal import Autonomy

from .cache import VerificationCache, verify_with_cache
from .vqcc.calibrate import Calibration
from .checkpoint import Checkpoint
from .vqcc.contracts import CircuitSpec
from .cvv import CvvChain, CvvRecord
from .vqcc.detect import CircuitDetector
from .goal import Goal, GoalTracker
from .integrity import IntegrityEvidence, IntegrityFilter, canonical_hash
from .vqcc.ledger import VQCCLedger
from .proxy import CandidateMeta, MetadataProxy
from .vqcc.search import Mutator
from .vqcc.verify import LocalVerifier


@dataclass
class MvpResult:
    best: dict[str, Any] | None
    best_S: float
    best_verified_S: float
    trials: int
    accepted: int
    rejected: int
    proxy_rejected: int
    integrity_vetoes: int
    stagnated: bool
    goal_reached: bool
    stop_reason: str
    autonomy: str
    health: float | None
    cvv_records: int
    checkpoint_path: str | None
    cache_hits: int = 0
    cache_misses: int = 0
    cvv_path: str | None = None
    mode_transitions: list[dict[str, Any]] = field(default_factory=list)
    ledger_events: list[str] = field(default_factory=list)


class AutoMvp:
    def __init__(self, spec: CircuitSpec, mutator: Mutator, goal: Goal,
                 verifier: LocalVerifier | None = None,
                 ledger: VQCCLedger | None = None,
                 calibration: Calibration | None = None,
                 proxy: MetadataProxy | None = None,
                 integrity: IntegrityFilter | None = None,
                 cvv: CvvChain | None = None,
                 checkpoint: Checkpoint | None = None,
                 cache: VerificationCache | None = None,
                 autonomy: Autonomy = Autonomy.AUTO,
                 health_floor: float = 0.5,
                 max_consecutive_failures: int = 3,
                 workdir: str | Path | None = None):
        self.spec = spec
        self.mutator = mutator
        self.goal = goal
        self.tracker = GoalTracker(goal)
        self.verifier = verifier or LocalVerifier(spec)
        self.workdir = Path(workdir) if workdir is not None else None
        # Con workdir, el ledger vive en disco y rota a 1 MB (idea DSP v9);
        # sin workdir, solo en memoria (comportamiento v0.3.0).
        if ledger is None and self.workdir is not None:
            ledger = VQCCLedger(path=str(self.workdir / "ledger.jsonl"),
                                max_bytes=1_048_576)
        self.ledger = ledger or VQCCLedger()
        self.calibration = calibration
        self.proxy = proxy
        self.integrity = integrity or IntegrityFilter()
        self.cvv = cvv or CvvChain()
        self.cache = cache
        if checkpoint is None and workdir is not None:
            checkpoint = Checkpoint(Path(workdir) / "checkpoints")
        self.checkpoint = checkpoint
        self.autonomy = autonomy
        self.health_floor = health_floor
        self.max_consecutive_failures = max_consecutive_failures
        self._consecutive_failures = 0
        self.mode_transitions: list[dict[str, Any]] = []
        self.proxy_rejected = 0
        self.integrity_vetoes = 0
        self.accepted = 0
        self.rejected = 0
        margin = calibration.margin if calibration else 0.0
        stagnation = calibration.stagnation_limit if calibration else None
        self.detector = CircuitDetector(
            spec, stagnation_limit=stagnation or goal.patience, margin=margin)
        self.best: dict[str, Any] | None = None
        self.best_S: float = spec.baseline_S
        self.best_verified_S: float = float("inf")
        self.proposed: dict[str, Any] | None = None
        self.detector.best_S = spec.baseline_S
        self._cycle = 0

    # -- veto de salud (misma regla que SearchLoop v0.2.1) --
    def _drop_mode(self, reason: str, health: float | None) -> None:
        order = [Autonomy.AUTO, Autonomy.PROPOSE, Autonomy.SHADOW]
        idx = order.index(self.autonomy)
        if idx >= len(order) - 1:
            return
        old = self.autonomy
        self.autonomy = order[idx + 1]
        self.mode_transitions.append(
            {"from": old.value, "to": self.autonomy.value,
             "reason": reason, "health": health})
        self.ledger.mode_transition(self.spec.task, old.value,
                                    self.autonomy.value, reason, health=health)

    def _cvv(self, phase: str, score: float, status: str, *,
             logic_verified: bool, certified: bool = False,
             verified_by: str = "", logic_integrity: str = "PASSED",
             delta: str | None = None, veto_reason: str | None = None,
             best_found: bool = False, state_hash: str = "") -> CvvRecord:
        self._cycle += 1
        return self.cvv.append(CvvRecord(
            cycle=self._cycle, phase=phase,
            target_goal=self.goal.target_label(),
            algebraic_state_hash=state_hash or canonical_hash(
                self.best.get("params", {}) if self.best else {}),
            score=score, logic_verified=logic_verified, status=status,
            delta_improvement=delta, best_found_so_far=best_found,
            veto_reason=veto_reason, certified=certified,
            verified_by=verified_by, logic_integrity=logic_integrity))

    @staticmethod
    def _delta_pct(old: float, new: float) -> str:
        if old in (0.0, float("inf")) or not math.isfinite(old):
            return "n/a"
        return f"{(new - old) / old * 100:+.1f}%"

    def run(self) -> MvpResult:
        # 1. INGESTA: el baseline verificado queda sellado.
        self._cvv("INGEST_BASELINE", self.spec.baseline_S, "LOCKED_BASE",
                  logic_verified=True, certified=True,
                  verified_by="official", logic_integrity="PASSED_STRICT",
                  state_hash=canonical_hash({"baseline": self.spec.baseline_S}))
        stop_reason = ""
        goal_reached = False
        while True:
            stop, reason = self.tracker.should_stop()
            if stop:
                stop_reason, goal_reached = reason, "meta alcanzada" in reason
                break
            evidence = {
                "best_S": self.best_S,
                "best_verified_S": self.best_verified_S,
                "trials": self.detector.trials,
                "trials_since_improvement": self.detector.trials_since_improvement,
                "autonomy": self.autonomy.value,
                "health": self.detector.health(),
            }
            candidate = self.mutator.propose(self.spec, self.best, evidence)
            name = str(candidate.get("mutation", candidate.get("name", "?")))
            # 2a. EVALUACIÓN (proxy): criba por metadatos antes de construir.
            if self.proxy is not None and "meta" in candidate:
                meta = candidate["meta"]
                if isinstance(meta, dict):
                    meta = CandidateMeta(**meta)
                verdict = self.proxy.evaluate(meta, self.best_S)
                if not verdict.ok:
                    self.proxy_rejected += 1
                    self.rejected += 1
                    # La criba por proxy también es un intento: cuenta
                    # para el estancamiento y la paciencia, aunque no se
                    # construyó nada (ese es el punto del proxy).
                    self.detector.observe(float("inf"), verdict.reasons)
                    self.tracker.observe(float("inf"), False)
                    self.ledger.trial(
                        task=self.spec.task, mutation=name, S=float("inf"),
                        best_S=self.best_S, passed=False, accepted=False,
                        verified_by="proxy",
                        params=candidate.get("params", {}),
                        autonomy=self.autonomy.value, health=None,
                        reason="; ".join(verdict.reasons))
                    continue
            # 2b. EVALUACIÓN (verificador): S oficial, nunca la suma ponderada.
            # Con caché, un candidato idéntico no se vuelve a verificar.
            if self.cache is not None:
                result, _hit = verify_with_cache(self.cache, self.verifier, candidate)
            else:
                result = self.verifier.verify(candidate)
            S = result.S if math.isfinite(result.S) else float("inf")
            # 3. AUDITORÍA (integridad): obligatoria si trae evidencia o
            #    si afirma verificación oficial.
            integrity_ok, veto_reasons = True, []
            has_evidence = candidate.get("integrity") is not None
            if has_evidence or result.verified_by == "official":
                integrity_ok, veto_reasons = self.integrity.check(
                    candidate.get("integrity"))
            obs = self.detector.observe(
                S if integrity_ok else float("inf"),
                (result.failures if not result.ok else []) + veto_reasons)
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
            if not integrity_ok:
                # Forma exacta del paso 51: mejor S, lógica rota.
                self.integrity_vetoes += 1
                self.rejected += 1
                self.tracker.observe(float("inf"), False)
                self._cvv("REJECTED_REGRESSION", S, "ROLLED_BACK",
                          logic_verified=False,
                          verified_by=result.verified_by,
                          logic_integrity="FAILED",
                          veto_reason="; ".join(veto_reasons) or "SIGMA_DIVERGENCE",
                          state_hash=canonical_hash(candidate.get("params", {})))
                self.ledger.rolled_back(
                    self.spec.task,
                    reason="integridad: " + "; ".join(veto_reasons),
                    best_S=self.best_S)
                self.ledger.trial(
                    task=self.spec.task, mutation=name, S=S, best_S=self.best_S,
                    passed=False, accepted=False, verified_by=result.verified_by,
                    params=candidate.get("params", {}),
                    autonomy=self.autonomy.value, health=health,
                    best_verified_S=self.best_verified_S)
                if obs["stagnated"]:
                    self.ledger.stagnated(self.spec.task,
                                          obs["trials_since_improvement"])
                    stop_reason = "estancamiento"
                    break
                continue
            # Mejor verificado oficial, por separado del proyectado.
            verified = (result.verified_by == "official" and result.ok
                        and math.isfinite(S))
            if verified and S < self.best_verified_S:
                self.best_verified_S = S
            accepted = result.ok and obs["improved"]
            self.tracker.observe(S, bool(accepted))
            if accepted:
                old_S = self.best_S
                if self.autonomy is Autonomy.SHADOW:
                    pass
                elif self.autonomy is Autonomy.PROPOSE:
                    self.proposed = candidate
                    self.ledger.proposed(self.spec.task, name, S)
                else:
                    self.best = candidate
                    self.best_S = S
                    self.accepted += 1
                    logic_integrity = ("PASSED_STRICT" if verified
                                       else "PASSED")
                    self._cvv("AUTO_OPTIMIZE", S, "CERTIFIED" if verified else "PROJECTED_BEST",
                              logic_verified=bool(has_evidence or verified),
                              certified=verified,
                              verified_by=result.verified_by,
                              logic_integrity=logic_integrity,
                              delta=self._delta_pct(old_S, S),
                              best_found=True,
                              state_hash=canonical_hash(candidate.get("params", {})))
                    # 4. Checkpoint inmediato, solo si está verificado.
                    if verified and self.checkpoint is not None:
                        ev = candidate.get("integrity")
                        ev_dict: dict[str, Any] = {}
                        if isinstance(ev, dict):
                            ev_dict = IntegrityEvidence.from_dict(ev).to_dict()
                        elif isinstance(ev, IntegrityEvidence):
                            ev_dict = ev.to_dict()
                        self.checkpoint.save({
                            "task": self.spec.task,
                            "S": S,
                            "mutation": name,
                            "params": candidate.get("params", {}),
                            "verified_by": "official",
                            "logic_integrity": logic_integrity,
                            "integrity": ev_dict,
                            "cvv_checksum": self.cvv.records[-1].checksum,
                        })
            else:
                self.rejected += 1
                self.ledger.rolled_back(
                    self.spec.task,
                    reason="; ".join(result.failures) or f"S={S:.6g} no mejora best={self.best_S:.6g}",
                    best_S=self.best_S)
            self.ledger.trial(
                task=self.spec.task, mutation=name, S=S, best_S=self.best_S,
                passed=result.ok, accepted=accepted and self.autonomy is Autonomy.AUTO,
                verified_by=result.verified_by,
                params=candidate.get("params", {}),
                autonomy=self.autonomy.value, health=health,
                best_verified_S=self.best_verified_S)
            if obs["stagnated"]:
                self.ledger.stagnated(self.spec.task,
                                      obs["trials_since_improvement"])
                stop_reason = "estancamiento"
                break
        # 5. CONVERGENCIA: el último récord resume el mejor final.
        certified = (self.best is not None and self.best_verified_S == self.best_S
                     and math.isfinite(self.best_verified_S))
        self._cvv("MVP_CONVERGENCE", self.best_S,
                  "CERTIFIED" if certified else "PROJECTED_BEST",
                  logic_verified=certified, certified=certified,
                  verified_by="official" if certified else "cost-only",
                  logic_integrity="PASSED_STRICT" if certified else "PASSED",
                  delta=self._delta_pct(self.spec.baseline_S, self.best_S),
                  best_found=True)
        # La cadena CVV queda guardada junto al ledger y los checkpoints.
        cvv_path = None
        if self.workdir is not None:
            self.workdir.mkdir(parents=True, exist_ok=True)
            cvv_path = str(self.workdir / "cvv.jsonl")
            self.cvv.save(cvv_path)
        final_health = self.detector.health()
        return MvpResult(
            best=self.best, best_S=self.best_S,
            best_verified_S=self.best_verified_S,
            trials=self.detector.trials, accepted=self.accepted,
            rejected=self.rejected, proxy_rejected=self.proxy_rejected,
            integrity_vetoes=self.integrity_vetoes,
            stagnated=stop_reason == "estancamiento",
            goal_reached=goal_reached, stop_reason=stop_reason,
            autonomy=self.autonomy.value,
            health=final_health["health"] if final_health else None,
            cvv_records=len(self.cvv),
            checkpoint_path=(str(self.checkpoint.best_path)
                             if self.checkpoint is not None and
                             self.checkpoint.best_path.exists() else None),
            cache_hits=self.cache.hits if self.cache else 0,
            cache_misses=self.cache.misses if self.cache else 0,
            cvv_path=cvv_path,
            mode_transitions=self.mode_transitions,
            ledger_events=self.ledger.events())

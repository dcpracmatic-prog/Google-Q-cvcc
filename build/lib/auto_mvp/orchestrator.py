"""AUTO_MVP v0.6.0 — orquestador adaptativo (la capa de adaptación dinámica).

El orquestador no se limita a pruebas fijas y paramétricas: lee
configuraciones JSON (con directivas en lenguaje natural), reordena
pasos, adapta metodologías en caliente y ejecuta iteraciones
inteligentes apoyándose en Qualtran y kickmix (la formalización es
Qualtran: Bloqs, grafo de llamadas, T/Q de primera clase).

Cómo funciona:
- El plan (StepPlan) es la lista ordenada de pasos (celdas): tunnel,
  proxy, gate, compile, observe, calibrate, search, verify. El
  orquestador ejecuta los pasos EN ESE ORDEN por candidato. Cambiar
  el orden cambia el resultado: con "tunnel" antes de "proxy", un
  candidato que el proxy rechazaría se tunela primero y puede pasar;
  con "tunnel" después de "gate", solo se tunelan los promovidos.
- Entre iteraciones, las directivas JSON reprograman el plan
  (reordenar, reemplazar métodos, insertar/quitar pasos), la meta
  (meta_mvp), el presupuesto y el margen de poda. Cada
  reprogramación queda en el log.
- La gobernanza vive en el Pipeline (modo AUTO->PROPOSE->SHADOW,
  Observer solo observa): el orquestador no veta nada, solo
  reordena y adapta.

Pasos implementados: tunnel, proxy, gate, compile, observe,
calibrate (con sonda en los params del paso). Pasos reconocidos
pero NO cableados (se reportan, no se saltan en silencio):
- "search": la búsqueda de mutaciones vive en vqcc/search.py
  (SearchLoop); no es un paso por candidato del orquestador.
- "verify": la verificación oficial vive en la fase 3 (compile_fn
  + verificador oficial); aquí se usa el verificador LOCAL
  (LocalVerifier) sobre las métricas del candidato promovido.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from .json_directive import Directive, parse_directive
from .morph_tunnel import RULES
from .pipeline import Pipeline
from .step_plan import StepPlan
from .vqcc.verify import LocalVerifier

IMPLEMENTED_STEPS = ("tunnel", "proxy", "gate", "compile", "observe",
                     "calibrate", "verify")
NOT_WIRED = {
    "search": ("la búsqueda de mutaciones vive en vqcc/search.py "
               "(SearchLoop); no es un paso por candidato"),
}


@dataclass
class OrchestratorResult:
    screened: int
    proxy_rejected: int
    gate_rejected: int
    promoted: int
    tunneled: int
    best_gm: float
    goal_reached: bool
    artifacts: list[str] = field(default_factory=list)
    reprogrammings: list[dict[str, Any]] = field(default_factory=list)
    step_log: list[dict[str, Any]] = field(default_factory=list)
    stopped: str = ""
    elapsed_seconds: float = 0.0
    meta_mvp: float = 0.0


class AdaptiveOrchestrator:
    """Orquestador adaptativo sobre un Pipeline + un StepPlan."""

    def __init__(self, pipe: Pipeline, plan: StepPlan | None = None,
                 tunnel_rules: list | None = None):
        self.pipe = pipe
        self.plan = plan or StepPlan()
        self.tunnel_rules = list(RULES if tunnel_rules is None else tunnel_rules)
        self.pipe.tunnel_engine = self.tunnel_rules
        self.attack_block: str | None = None
        self.reprogrammings: list[dict[str, Any]] = []
        self.step_log: list[dict[str, Any]] = []

    def _record(self, action: str, detail: dict[str, Any],
                directive: str = "") -> None:
        self.reprogrammings.append(
            {"action": action, "detail": detail, "directive": directive,
             "ts": time.time(), "order_after": list(self.plan.order)})

    def apply_directive(self, directive: Directive | str) -> bool:
        """Aplica una directiva (decodificada o en texto) al plan o a la meta."""
        d = parse_directive(directive) if isinstance(directive, str) else directive
        if not d.parsed:
            self._record("unparsed", {"reason": d.reason}, d.raw)
            return False
        v, p = d.verb, d.params
        if v == "set_meta_mvp":
            old = self.pipe.gate.meta_mvp
            self.pipe.gate.meta_mvp = float(p["meta_mvp"])
            self.pipe.gate.threshold = self.pipe.gate.meta_mvp
            self._record("set_meta_mvp", {"from": old, "to": p["meta_mvp"]}, d.raw)
            return True
        if v == "set_budget":
            # El presupuesto se aplica en run() (se guarda aquí).
            self._pending_budget = p
            self._record("set_budget", p, d.raw)
            return True
        if v == "prune":
            old = self.pipe.proxy.margin
            self.pipe.proxy.margin = float(p.get("pct", 0.0)) / 100.0
            self._record("prune", {"from": old, "to": self.pipe.proxy.margin,
                                   "metric": p.get("metric", "T")}, d.raw)
            return True
        if v == "tunnel":
            self.attack_block = p["block"]
            self._record("attack_block", p, d.raw)
            return True
        # El resto son operaciones sobre el plan.
        ok = self.plan.apply(d)
        if ok:
            self._record(f"plan:{v}", p, d.raw)
        else:
            self._record("plan_no_aplica", {"verb": v, "params": p}, d.raw)
        return ok

    def run(self, stream: Iterable[dict[str, Any]],
            max_iterations: int | None = None,
            directives: list[Directive | str] | None = None,
            directives_at: dict[int, list[Directive | str]] | None = None
            ) -> OrchestratorResult:
        started = time.monotonic()
        self._pending_budget: dict[str, Any] = {}
        for d in (directives or []):
            self.apply_directive(d)
        directives_at = directives_at or {}
        pipe = self.pipe
        ctx = {"screened": 0, "proxy_rejected": 0, "gate_rejected": 0,
               "promoted": 0, "tunneled": 0, "shadow_skipped": 0,
               "best_gm": float(pipe.state.get("best_gm", 0.0)),
               "best": None, "best_kind": pipe.best_kind,
               "since_improvement": 0, "artifacts": []}
        run_limit = max_iterations if max_iterations is not None \
            else pipe.max_trials_default
        if "trials" in self._pending_budget:
            run_limit = int(self._pending_budget["trials"])
        time_budget = pipe.time_budget_seconds
        if "hours" in self._pending_budget:
            time_budget = float(self._pending_budget["hours"]) * 3600.0
        run_count = 0
        stopped = "stream agotado"
        for candidate in stream:
            if run_limit is not None and run_count >= run_limit:
                stopped = "límite de iteraciones"
                break
            if time_budget is not None and time.monotonic() - started >= time_budget:
                stopped = "presupuesto de tiempo agotado"
                break
            if (pipe.stagnation_limit is not None
                    and ctx["since_improvement"] >= pipe.stagnation_limit
                    and (pipe.partition is None or all(
                        v >= pipe.stagnation_limit
                        for v in pipe.since_improvement_by_side.values()))):
                stopped = "estancamiento"
                break
            if (ctx["best_gm"] >= pipe.gate.meta_mvp
                    and ctx["best_kind"] == "candidate"):
                stopped = (f"meta alcanzada: GM {ctx['best_gm']:.2f} >= "
                           f"meta_mvp {pipe.gate.meta_mvp:.2f}")
                break
            # Directivas programadas para esta iteración (en caliente).
            for d in directives_at.get(run_count + 1, []):
                self.apply_directive(d)
            pipe.iteration += 1
            run_count += 1
            ctx["screened"] += 1
            self._process_candidate(candidate, ctx)
            if (ctx["best_gm"] >= pipe.gate.meta_mvp
                    and ctx["best_kind"] == "candidate"):
                stopped = (f"meta alcanzada: GM {ctx['best_gm']:.2f} >= "
                           f"meta_mvp {pipe.gate.meta_mvp:.2f}")
                break
        pipe._observe()
        pipe.state["best_gm"] = ctx["best_gm"]
        pipe._save_state()
        return OrchestratorResult(
            screened=ctx["screened"], proxy_rejected=ctx["proxy_rejected"],
            gate_rejected=ctx["gate_rejected"], promoted=ctx["promoted"],
            tunneled=ctx["tunneled"], best_gm=ctx["best_gm"],
            goal_reached=(ctx["best_gm"] >= pipe.gate.meta_mvp
                          and ctx["best_kind"] == "candidate"),
            artifacts=ctx["artifacts"],
            reprogrammings=list(self.reprogrammings),
            step_log=list(self.step_log), stopped=stopped,
            elapsed_seconds=time.monotonic() - started,
            meta_mvp=pipe.gate.meta_mvp)

    def _process_candidate(self, candidate: dict[str, Any],
                           ctx: dict[str, Any]) -> None:
        pipe = self.pipe
        kind = candidate.get("kind", "candidate")
        side = pipe.side_of.get(candidate.get("name", "")) or None
        trial: dict[str, Any] = {"S": None, "passed": False,
                                 "accepted": False, "integrity_veto": False,
                                 "kind": kind, "compile_failed": False}
        pipe.trials_log.append(trial)
        est_S: float | None = None
        gate_v = None
        promoted = False
        for step in self.plan.steps:
            name = step["step"]
            method = step.get("method", "")
            trace = {"iteration": pipe.iteration, "step": name,
                     "method": method}
            if name == "tunnel":
                candidate, res = pipe.tunnel_candidate(candidate, method=method or "greedy")
                if res is not None and res.moves:
                    ctx["tunneled"] += 1
                    trial["tunnel"] = res.as_dict()
                trace["moves"] = len(res.moves) if res is not None else 0
            elif name == "proxy":
                verdict, est_S = pipe.proxy_eval(candidate)
                trace["ok"] = verdict.ok
                if not verdict.ok:
                    ctx["proxy_rejected"] += 1
                    self.step_log.append(trace)
                    return
                trial["S"] = est_S
                trial["passed"] = True
            elif name == "gate":
                if est_S is None:
                    trace["ok"] = False
                    trace["reason"] = "gate sin S estimado (proxy no corrió antes)"
                    self.step_log.append(trace)
                    return
                cand_S = {self._task_of(candidate): est_S}
                gate_v = pipe.gate.evaluate(cand_S)
                trace["gm"] = gate_v.gm
                trace["promote"] = gate_v.promote
                if gate_v.gm > ctx["best_gm"]:
                    ctx["best_gm"] = gate_v.gm
                    ctx["best_kind"] = kind
                    pipe.best_kind = kind
                    ctx["since_improvement"] = 0
                    ctx["best"] = {"iteration": pipe.iteration,
                                   "gm": gate_v.gm, "S": cand_S,
                                   "ratios": gate_v.ratios, "kind": kind}
                    if side is not None:
                        pipe.best_gm_by_side[side] = gate_v.gm
                        pipe.since_improvement_by_side[side] = 0
                else:
                    ctx["since_improvement"] += 1
                    if side is not None:
                        pipe.since_improvement_by_side[side] = (
                            pipe.since_improvement_by_side.get(side, 0) + 1)
                if not gate_v.promote:
                    ctx["gate_rejected"] += 1
                    self.step_log.append(trace)
                    return
                promoted = True
            elif name == "compile":
                if not promoted or gate_v is None:
                    trace["ok"] = False
                    trace["reason"] = "compile sin promoción (gate no promovió antes)"
                    self.step_log.append(trace)
                    return
                meta = candidate.get("meta")
                task = self._task_of(candidate)
                record = {"iteration": pipe.iteration, "gm": gate_v.gm,
                          "S": {task: est_S}, "ratios": gate_v.ratios,
                          "task": task, "kind": kind, "meta": meta,
                          "metrics": candidate.get("metrics", {}),
                          "source_commit": pipe.source_commit}
                trial["accepted"] = True
                ctx["promoted"] += 1
                dest, shadow = pipe.promote_and_compile(record, trial)
                if shadow:
                    ctx["shadow_skipped"] += 1
                elif dest is not None:
                    ctx["artifacts"].append(dest)
                trace["artifact"] = dest
            elif name == "observe":
                pipe._observe()
            elif name == "calibrate":
                probe = step.get("params", {}).get("probe")
                if probe is None:
                    trace["ok"] = False
                    trace["reason"] = "calibrate sin sonda en los params del paso"
                else:
                    from .vqcc.calibrate import calibrate_from_candidates
                    cal = calibrate_from_candidates(
                        pipe.proxy.spec, probe,
                        LocalVerifier(pipe.proxy.spec))
                    pipe.proxy.margin = cal.margin
                    pipe.calibration = cal
                    trace["margin"] = cal.margin
            elif name == "verify":
                if not promoted:
                    trace["ok"] = False
                    trace["reason"] = "verify sin promoción previa"
                else:
                    v = LocalVerifier(pipe.proxy.spec)
                    res = v.verify({"task": self._task_of(candidate),
                                    "metrics": candidate.get("metrics", {}),
                                    "S": est_S})
                    trace["ok"] = bool(res.ok)
                    trace["verified_by"] = res.verified_by
                    trace["failures"] = list(res.failures)
            elif name in NOT_WIRED:
                trace["ok"] = False
                trace["reason"] = NOT_WIRED[name]
            else:
                trace["ok"] = False
                trace["reason"] = f"paso desconocido: {name!r}"
            self.step_log.append(trace)

    def _task_of(self, candidate: dict[str, Any]) -> str:
        meta = candidate.get("meta")
        if isinstance(meta, dict):
            return str(meta.get("task", ""))
        return str(getattr(meta, "task", ""))

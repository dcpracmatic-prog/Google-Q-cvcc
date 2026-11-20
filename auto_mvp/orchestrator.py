"""AUTO_MVP — orquestador adaptativo (la capa de adaptación dinámica) (desde v0.6.0).

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
  reordena y adapta. EXCEPCIÓN (H14): el paso verify SÍ veta —
  si el verificador OFICIAL da FAIL sobre un artefacto real, el
  candidato no se promueve ni se compila. Para que el veto bloquee
  la compilación, verify debe ir ANTES de compile en el plan.

Pasos implementados: tunnel, proxy, gate, compile, observe,
calibrate (con sonda en los params del paso o por directiva
"sonda [...]"), search (SearchLoop real de vqcc/search.py) y
verify (cribado local, u oficial con veto si hay artefacto real).

Orden de los pasos (H17): gate exige que proxy haya corrido antes
(S estimado presente) y compile exige promoción previa. Un plan
que no cumple eso es un error de configuración: se lanza
StepOrderError con el motivo, en vez de tirar el candidato en
silencio.
"""
from __future__ import annotations

import inspect
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from .json_directive import Directive, parse_directive
from .morph_tunnel import RULES
from .pipeline import Pipeline
from .step_plan import StepPlan
from .vqcc.verify import (LocalVerifier, verify_chemistry_factorization,
                          verify_circuit_file)

IMPLEMENTED_STEPS = ("tunnel", "proxy", "gate", "compile", "observe",
                     "calibrate", "search", "verify")
# H15: "search" ya está cableado (SearchLoop real); el dict queda
# para pasos futuros reconocidos pero no cableados.
NOT_WIRED: dict[str, str] = {}

# Claves de candidato que señalan un artefacto real de circuito
# (archivo .kmb/.kmx) para la verificación oficial del paso verify.
_CIRCUIT_PATH_KEYS = ("circuit_path", "circuit_file", "kmb_path", "kmx_path")


class StepOrderError(ValueError):
    """El plan pide un paso antes de su requisito (H17).

    Ej. gate sin proxy antes, o compile sin promoción previa.
    Es un error de configuración del plan, no un rechazo del
    candidato: se lanza en vez de descartar el candidato en silencio.
    """


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
    # v0.8.0: módulos exportados al dataset de trabajo.
    exported: int = 0
    dataset_dir: str = ""


class _IdentityMutator:
    """Mutador mínimo para el paso search sin mutador explícito (H15).

    Propone el candidato actual tal cual en cada intento: el
    SearchLoop lo verifica (cribado local), lo acepta si baja el
    mejor S del spec y se estanca si no mejora. Es búsqueda de
    verdad (el lazo corre y decide), no un hueco: con un mutador
    real (params del paso "mutator" o search_mutator del
    constructor) el lazo propone mutaciones nuevas.
    """

    def __init__(self, candidate: dict[str, Any]):
        self._candidate = candidate

    def propose(self, spec, best, evidence) -> dict[str, Any]:
        return dict(self._candidate)


class AdaptiveOrchestrator:
    """Orquestador adaptativo sobre un Pipeline + un StepPlan."""

    def __init__(self, pipe: Pipeline, plan: StepPlan | None = None,
                 tunnel_rules: list | None = None,
                 search_mutator: Any | None = None):
        self.pipe = pipe
        self.plan = plan or StepPlan()
        self.tunnel_rules = list(RULES if tunnel_rules is None else tunnel_rules)
        # H23: respeta un motor de túnel ya configurado en el Pipeline;
        # solo se pone el propio si el Pipeline no trae ninguno.
        if pipe.tunnel_engine is None:
            self.pipe.tunnel_engine = self.tunnel_rules
        self.attack_block: str | None = None
        # H1: la directiva tunnel guarda también la regla, no solo el bloque.
        self.attack_rule: str | None = None
        # H16: sonda para calibrate, puesta por directiva ("sonda [...]").
        self.probe: list[dict[str, Any]] | None = None
        # H2: el presupuesto pendiente vive aquí desde el inicio; run()
        # ya no lo borra (una directiva antes de run() debe sobrevivir).
        self._pending_budget: dict[str, Any] = {}
        # H15: mutador para el paso search (si es None, mutador identidad).
        self.search_mutator = search_mutator
        self.reprogrammings: list[dict[str, Any]] = []
        self.step_log: list[dict[str, Any]] = []

    def _record(self, action: str, detail: dict[str, Any],
                directive: str = "") -> None:
        self.reprogrammings.append(
            {"action": action, "detail": detail, "directive": directive,
             "ts": time.time(), "order_after": list(self.plan.order)})

    def _set_probe(self, probe: Any, raw: str) -> bool:
        """Guarda la sonda para calibrate (H16). Acepta un candidato
        dict o una lista de candidatos dict."""
        if isinstance(probe, dict):
            probe = [probe]
        if (not isinstance(probe, list) or not probe
                or not all(isinstance(c, dict) for c in probe)):
            self._record("sonda_no_aplica", {
                "reason": "la sonda debe ser una lista de candidatos "
                          "(dicts con metrics), no " + type(probe).__name__},
                raw)
            return False
        self.probe = list(probe)
        self._record("set_probe", {
            "n": len(self.probe),
            "names": [c.get("name", c.get("mutation", "?"))
                      for c in self.probe]}, raw)
        return True

    def apply_directive(self, directive: Directive | str) -> bool:
        """Aplica una directiva (decodificada o en texto) al plan o a la meta."""
        # H16: "sonda [...]" no está en el vocabulario de
        # json_directive (no se toca ese archivo): se intercepta aquí.
        # Forma: sonda [{"name": ..., "task": "dqi", "metrics": {...}}, ...]
        if isinstance(directive, str):
            raw = directive.strip()
            if raw.lower().startswith("sonda"):
                rest = raw[5:].strip()
                if not rest:
                    self._record("sonda_no_aplica", {
                        "reason": "sonda sin lista: usa "
                                  "'sonda [{...candidato...}, ...]'"}, raw)
                    return False
                try:
                    probe = json.loads(rest)
                except ValueError as e:
                    self._record("sonda_no_aplica", {
                        "reason": f"la lista de la sonda no es JSON válido: {e}"},
                        raw)
                    return False
                return self._set_probe(probe, raw)
            d = parse_directive(directive)
        else:
            d = directive
        if not d.parsed:
            self._record("unparsed", {"reason": d.reason}, d.raw)
            return False
        v, p = d.verb, d.params
        if v in ("sonda", "set_probe"):
            return self._set_probe(p.get("probe", p.get("candidates")), d.raw)
        if v == "set_meta_mvp":
            old = self.pipe.gate.meta_mvp
            self.pipe.gate.meta_mvp = float(p["meta_mvp"])
            self.pipe.gate.threshold = self.pipe.gate.meta_mvp
            # H24: pipe.meta_mvp también (pipeline.py:304 lo lee de la puerta).
            self.pipe.meta_mvp = float(p["meta_mvp"])
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
            metric = p.get("metric", "T")
            # H25: el margen que se toca es GENÉRICO: MetadataProxy
            # solo tiene un margen (proxy.margin), no hay margen por
            # métrica. El % se aplica al S estimado completo, no solo
            # a la métrica nombrada; queda registrado así, no en silencio.
            self._record("prune", {
                "from": old, "to": self.pipe.proxy.margin,
                "metric": metric, "scope": "generic",
                "note": ("MetadataProxy solo tiene un margen "
                         "(proxy.margin): no hay margen por métrica, así "
                         "que el % se aplica al S estimado completo, no "
                         f"solo a {metric}")}, d.raw)
            return True
        if v == "tunnel":
            self.attack_block = p["block"]
            # H1: guarda también la regla (p.get, puede no venir).
            self.attack_rule = p.get("rule")
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
        # H2: NO se borra self._pending_budget aquí: un presupuesto
        # aplicado antes de run() (apply_directive) debe sobrevivir
        # y aplicarse en esta corrida.
        for d in (directives or []):
            self.apply_directive(d)
        directives_at = directives_at or {}
        pipe = self.pipe
        ctx = {"screened": 0, "proxy_rejected": 0, "gate_rejected": 0,
               "promoted": 0, "tunneled": 0, "shadow_skipped": 0,
               "exported": 0,
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
            meta_mvp=pipe.gate.meta_mvp,
            exported=ctx["exported"],
            dataset_dir=str(pipe.dataset.root))

    def _official_artifact(self, candidate: dict[str, Any],
                           ) -> tuple[str, Any] | None:
        """Artefacto real del candidato para verificación oficial (H14).

        Devuelve ("factorization", ruta) si trae factorization_path
        (química) o ("circuit", ruta) si trae ruta de circuito
        (.kmb/.kmx). Si no trae artefacto, None (cribado local).
        """
        if candidate.get("factorization_path"):
            return ("factorization", candidate["factorization_path"])
        for key in _CIRCUIT_PATH_KEYS:
            if candidate.get(key):
                return ("circuit", candidate[key])
        return None

    def _run_search(self, candidate: dict[str, Any],
                    step: dict[str, Any], trace: dict[str, Any],
                    ) -> dict[str, Any]:
        """Paso search: corre el SearchLoop real (H15).

        Mutador: params del paso ("mutator"), o search_mutator del
        constructor, o el mutador identidad (propone el candidato
        actual). Devuelve el candidato a usar en los pasos siguientes
        (el mejor de la búsqueda, si lo hay; si no, el mismo).
        Si la búsqueda falla, queda en el trace y el flujo sigue:
        un fallo de búsqueda no es un rechazo del candidato.
        """
        from .vqcc.search import SearchLoop
        params = step.get("params", {}) or {}
        mutator = params.get("mutator") or self.search_mutator
        if mutator is None:
            mutator = _IdentityMutator(candidate)
            trace["mutator"] = "identity: propone el candidato actual"
        else:
            trace["mutator"] = type(mutator).__name__
        max_trials = params.get("max_trials", params.get("trials", 5))
        stagnation = params.get("stagnation_limit")
        try:
            loop = SearchLoop(
                spec=self.pipe.proxy.spec, mutator=mutator,
                verifier=LocalVerifier(self.pipe.proxy.spec),
                max_trials=int(max_trials),
                stagnation_limit=(int(stagnation)
                                  if stagnation is not None else None))
            result = loop.run()
        except Exception as e:  # la búsqueda no debe matar la corrida
            trace["ok"] = False
            trace["reason"] = f"search falló: {e}"
            return candidate
        trace["ok"] = True
        trace["trials"] = result.trials
        trace["accepted"] = result.accepted
        trace["rejected"] = result.rejected
        trace["best_S"] = result.best_S
        trace["stagnated"] = result.stagnated
        if result.best is not None:
            trace["found"] = result.best.get(
                "name", result.best.get("mutation", "?"))
            # El mejor de la búsqueda NO sube aquí pipe.best_S ni
            # gate.current: eso solo pasa al promover (H20). Si se
            # subiera ya, el propio candidato encontrado fallaría su
            # proxy (su S es igual al mejor nuevo y el margen exige
            # batirlo); el listón lo sube la puerta al promoverlo.
            return result.best
        return candidate

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
                # H7: pasa block y rule al túnel (si el Pipeline los
                # acepta; si no, se registra que el filtro no se aplicó).
                tunnel_kwargs: dict[str, Any] = {}
                try:
                    sig_params = inspect.signature(
                        pipe.tunnel_candidate).parameters
                except (TypeError, ValueError):
                    sig_params = {}
                if "block" in sig_params and "rule" in sig_params:
                    tunnel_kwargs = {"block": self.attack_block,
                                     "rule": self.attack_rule}
                    trace["tunnel_filter"] = {"block": self.attack_block,
                                              "rule": self.attack_rule}
                elif (self.attack_block is not None
                        or self.attack_rule is not None):
                    trace["tunnel_filter"] = (
                        "sin aplicar: el Pipeline no acepta block/rule "
                        "todavía (pendiente en pipeline.py)")
                candidate, res = pipe.tunnel_candidate(
                    candidate, method=method or "greedy", **tunnel_kwargs)
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
                    # H17: gate sin proxy antes es error de plan, no
                    # rechazo del candidato: se lanza con el motivo.
                    trace["ok"] = False
                    trace["reason"] = ("gate sin S estimado: proxy no "
                                       "corrió antes; reordena el plan "
                                       "(proxy antes que gate)")
                    self.step_log.append(trace)
                    raise StepOrderError(trace["reason"])
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
                # H20: el listón sube con el candidato promovido: el
                # mejor por tarea (pipe.best_S, contra el que compara
                # el proxy) y el "current" de la puerta (contra el que
                # calcula la GM) pasan a ser este S, no el inicial.
                # Solo al promover: un candidato no promovido no cierra
                # la puerta a repetir el mismo diseño tras bajar la meta.
                task = self._task_of(candidate)
                prev_best = pipe.best_S.get(task)
                if est_S is not None and (prev_best is None
                                          or est_S < prev_best):
                    pipe.best_S[task] = est_S
                    pipe.gate.current[task] = est_S
                    trace["best_S_updated"] = {task: est_S}
            elif name == "compile":
                if not promoted or gate_v is None:
                    # H17: compile sin promoción es error de plan.
                    trace["ok"] = False
                    trace["reason"] = ("compile sin promoción: gate no "
                                       "promovió antes; reordena el plan "
                                       "(gate antes que compile)")
                    self.step_log.append(trace)
                    raise StepOrderError(trace["reason"])
                meta = candidate.get("meta")
                task = self._task_of(candidate)
                record = {"name": candidate.get("name"),
                          "iteration": pipe.iteration, "gm": gate_v.gm,
                          "S": {task: est_S}, "ratios": gate_v.ratios,
                          "task": task, "kind": kind, "meta": meta,
                          "metrics": candidate.get("metrics", {}),
                          # v0.8.0: la estructura completa y el código
                          # del módulo viajan con el record (export).
                          "call_graph": candidate.get("call_graph"),
                          "source": candidate.get("source"),
                          "integrity": candidate.get("integrity"),
                          "source_commit": pipe.source_commit}
                trial["accepted"] = True
                ctx["promoted"] += 1
                dest, shadow = pipe.promote_and_compile(record, trial)
                if shadow:
                    ctx["shadow_skipped"] += 1
                elif dest is not None:
                    ctx["artifacts"].append(dest)
                    if record.get("export") and "error" not in record["export"]:
                        ctx["exported"] += 1
                trace["artifact"] = dest
            elif name == "observe":
                pipe._observe()
            elif name == "calibrate":
                # H16: la sonda puede venir en los params del paso o
                # por directiva ("sonda [...]"); el paso manda si trae una.
                step_probe = step.get("params", {}).get("probe")
                probe = step_probe or self.probe
                if probe is None:
                    trace["ok"] = False
                    trace["reason"] = ("calibrate sin sonda: ni en los "
                                       "params del paso ni por directiva "
                                       "'sonda [...]'")
                else:
                    trace["probe_source"] = ("step" if step_probe
                                             else "directive")
                    try:
                        from .vqcc.calibrate import calibrate_from_candidates
                        cal = calibrate_from_candidates(
                            pipe.proxy.spec, probe,
                            LocalVerifier(pipe.proxy.spec))
                    except ValueError as e:
                        trace["ok"] = False
                        trace["reason"] = f"sonda inválida: {e}"
                    else:
                        pipe.proxy.margin = cal.margin
                        pipe.calibration = cal
                        trace["ok"] = True
                        trace["margin"] = cal.margin
            elif name == "search":
                # H15: SearchLoop real (ver _run_search).
                candidate = self._run_search(candidate, step, trace)
            elif name == "verify":
                if not promoted:
                    trace["ok"] = False
                    trace["reason"] = "verify sin promoción previa"
                else:
                    task = self._task_of(candidate)
                    artifact = self._official_artifact(candidate)
                    if artifact is not None:
                        # H14: artefacto real -> verificador OFICIAL,
                        # con veto: FAIL = no se promueve ni se compila.
                        kind, path = artifact
                        if kind == "factorization":
                            res = verify_chemistry_factorization(
                                path,
                                system=candidate.get("system",
                                                     "FeMoCo76o113e"))
                        else:
                            res = verify_circuit_file(path, task)
                        trace["ok"] = bool(res.ok)
                        trace["verified_by"] = res.verified_by
                        trace["failures"] = list(res.failures)
                        trace["official"] = True
                        if not res.ok:
                            trace["veto"] = True
                            trace["reason"] = (
                                "verificador oficial FAIL: el candidato "
                                "no se promueve ni se compila")
                            trial["official_veto"] = True
                            self.step_log.append(trace)
                            return
                    else:
                        v = LocalVerifier(pipe.proxy.spec)
                        res = v.verify({"task": task,
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

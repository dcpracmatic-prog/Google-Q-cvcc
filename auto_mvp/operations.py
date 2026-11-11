"""AUTO_MVP v0.7.0 — operaciones compartidas de la Skill / Tool.

Un solo punto de entrada para las operaciones REALES del repo, usado
por igual por:
- la CLI (``python -m auto_mvp.cli``),
- el servidor MCP (``skills/auto-mvp-vqcc/mcp_server.py``),
- las funciones para ChatGPT/Grok (``skills/auto-mvp-vqcc/tools.py``).

Cada operación recibe y devuelve JSON (dicts), sin efectos fuera de
lo que dice: ``run_orchestrator`` escribe sus artefactos en un
directorio temporal (o en el que se le pase) y nunca toca el repo.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from .goal import target_S_for_meta_mvp
from .integrity import IntegrityEvidence, IntegrityFilter
from .json_directive import load_plan
from .morph_tunnel import RULES, tunnel as morph_tunnel
from .orchestrator import AdaptiveOrchestrator
from .pipeline import Pipeline, PromotionGate, promotion_gm, required_dqi_ratio
from .proxy import CandidateMeta, MetadataProxy, estimate_S
from .qualtran_bridge import CallGraph
from .step_plan import StepPlan
from .vqcc import dfthcsos_spec, dqi_spec, invsqrt_spec

SPECS = {"invsqrt": invsqrt_spec, "dqi": dqi_spec, "dfthcsos": dfthcsos_spec}

DEFAULT_MARGIN = 0.10  # el margen calibrado (sonda de vecindario, v0.2.1)


def _spec(task: str):
    if task not in SPECS:
        raise ValueError(f"tarea desconocida: {task!r} (invsqrt | dqi | dfthcsos)")
    return SPECS[task]()


def _candidate_meta(candidate: dict[str, Any]) -> CandidateMeta:
    meta = candidate.get("meta") or {}
    if isinstance(meta, dict):
        return CandidateMeta(**meta)
    return meta


def evaluate_candidate(candidate: dict[str, Any],
                       meta_mvp: float = 30.0,
                       margin: float = DEFAULT_MARGIN,
                       best_S: float | None = None) -> dict[str, Any]:
    """Evalúa un candidato: proxy + puerta de promoción.

    Entrada: {"name", "kind", "meta": {"task", "metrics": {...}},
    "metrics": {...}}. El proxy compara contra el mejor S conocido
    (por defecto, el del mejor envío: DQI 3.7676e11). Salida: S
    estimado, GM, ratios, si promueve, si pasó el proxy y los
    motivos. No guarda artefactos.
    """
    from .pipeline import CURRENT_BEST_S
    meta = _candidate_meta(candidate)
    proxy = MetadataProxy(_spec(meta.task), margin=margin)
    best = CURRENT_BEST_S[meta.task] if best_S is None else best_S
    verdict = proxy.evaluate(meta, best)
    out: dict[str, Any] = {"task": meta.task, "proxy_ok": verdict.ok,
                           "reasons": list(verdict.reasons)}
    if not verdict.ok:
        return out
    est_S = verdict.s_estimate if verdict.s_estimate is not None \
        else estimate_S(meta)
    gate = PromotionGate(meta_mvp)
    gv = gate.evaluate({meta.task: est_S})
    out.update({"S": est_S, "gm": gv.gm, "ratios": gv.ratios,
                "promote": gv.promote, "meta_mvp": meta_mvp})
    return out


def apply_morph_tunnel(call_graph: dict[str, Any],
                       rules: list[dict[str, Any]] | None = None,
                       method: str = "greedy") -> dict[str, Any]:
    """Tunela un grafo de llamadas con las reglas MORPH.

    Entrada: el grafo (dict de CallGraph) y, opcionalmente, reglas
    (si no se pasan, las del registro, con evidencia medida). Salida:
    T/Q antes y después, movimientos y motivo de parada.
    """
    from .morph_tunnel import ReplacementRule
    graph = CallGraph.from_dict(call_graph)
    use = RULES
    if rules is not None:
        use = [ReplacementRule(**r) for r in rules]
    return morph_tunnel(graph, use, method=method).as_dict()


def decode_json_config(config: dict[str, Any]) -> dict[str, Any]:
    """Decodifica una configuración JSON (directivas en lenguaje natural).

    Salida: meta_mvp, pasos, directivas decodificadas y las no
    parseadas (con su motivo). Nada se descarta en silencio.
    """
    plan = load_plan(config)
    return {
        "meta_mvp": plan["meta_mvp"],
        "steps": plan["steps"],
        "budget": plan["budget"],
        "directives": [
            {"verb": d.verb, "params": d.params, "raw": d.raw,
             "parsed": d.parsed, "reason": d.reason}
            for d in plan["directives"]],
        "unparsed": [
            {"verb": d.verb, "raw": d.raw, "reason": d.reason}
            for d in plan["unparsed"]],
    }


def run_orchestrator(candidates: list[dict[str, Any]],
                     config: dict[str, Any] | None = None,
                     runs_dir: str | Path | None = None,
                     best_S: dict[str, float] | None = None
                     ) -> dict[str, Any]:
    """Corre el orquestador adaptativo sobre un flujo de candidatos.

    Entrada: la lista de candidatos y la config JSON (meta_mvp,
    pasos, directivas, presupuesto). ``best_S`` fija el mejor S
    conocido por tarea contra el que compara el proxy (por defecto,
    el del mejor envío). Los artefactos van a ``runs_dir`` (o a un
    temporal). Salida: el resultado del orquestador.
    """
    config = dict(config or {})
    meta_mvp = float(config.get("meta_mvp", 30.0))
    task = "dqi"
    for c in candidates:
        m = c.get("meta") or {}
        if isinstance(m, dict) and m.get("task"):
            task = str(m["task"])
            break
    tmp = tempfile.TemporaryDirectory() if runs_dir is None else None
    try:
        dest = Path(runs_dir) if runs_dir is not None else Path(tmp.name) / "runs"
        pipe = Pipeline(
            proxy=MetadataProxy(_spec(task), margin=DEFAULT_MARGIN),
            gate=PromotionGate(meta_mvp),
            runs_dir=dest, time_budget_seconds=None)
        if best_S:
            pipe.best_S.update({str(k): float(v) for k, v in best_S.items()})
        plan_cfg = load_plan(config)
        plan = StepPlan(steps=[dict(s) for s in plan_cfg["steps"]]) \
            if plan_cfg["steps"] else StepPlan()
        orch = AdaptiveOrchestrator(pipe, plan)
        directives = [d.raw for d in plan_cfg["directives"] if d.parsed]
        res = orch.run(iter(candidates), directives=directives)
        return {
            "screened": res.screened, "proxy_rejected": res.proxy_rejected,
            "gate_rejected": res.gate_rejected, "promoted": res.promoted,
            "tunneled": res.tunneled, "best_gm": res.best_gm,
            "goal_reached": res.goal_reached, "artifacts": res.artifacts,
            "reprogrammings": res.reprogrammings,
            "stopped": res.stopped, "meta_mvp": res.meta_mvp,
            "elapsed_seconds": res.elapsed_seconds,
            "unparsed": [{"raw": d.raw, "reason": d.reason}
                         for d in plan_cfg["unparsed"]],
        }
    finally:
        if tmp is not None:
            tmp.cleanup()


def check_integrity(evidence: dict[str, Any]) -> dict[str, Any]:
    """Pasa el filtro de integridad obligatorio sobre una evidencia.

    Entrada: la evidencia (kind, sigma, C/B, dreg, alpha, temporales,
    allowed_dirty). Salida: si pasa y los motivos. Un "projection"
    NUNCA pasa este filtro.
    """
    ok, reasons = IntegrityFilter().check(
        IntegrityEvidence.from_dict(evidence))
    return {"ok": ok, "reasons": reasons}


def export_module(record: dict[str, Any],
                  runs_dir: str | Path | None = None) -> dict[str, Any]:
    """Exporta e inyecta un módulo promovido al dataset de trabajo.

    Entrada: el record promovido (iteration, gm, S, ratios, task,
    kind, meta, metrics, call_graph, source, integrity). Escribe
    structure.json, module.py y source/... en el artefacto y en
    ``<runs_dir>/dataset/<nombre>/``, y actualiza el índice.
    Salida: las rutas y qué trae (grafo, código fuente).
    """
    from .dataset import WorkingDataset, export_candidate
    tmp = tempfile.TemporaryDirectory() if runs_dir is None else None
    try:
        dest = Path(runs_dir) if runs_dir is not None \
            else Path(tmp.name) / "runs"
        artifact_dir = dest / (record.get("artifact_name") or "i0-0.00")
        artifact_dir.mkdir(parents=True, exist_ok=True)
        # El manifiesto del artefacto (el de siempre) va primero.
        manifest = {"artifact": artifact_dir.name,
                    "iteration": record.get("iteration"),
                    "estimated_gm": record.get("gm"),
                    "kind": record.get("kind", "candidate"),
                    "task": record.get("task", ""),
                    "S": record.get("S"), "ratios": record.get("ratios", {}),
                    "source_commit": record.get("source_commit", ""),
                    "phase": "PROMOTED", "compiled": False}
        (artifact_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8")
        out = export_candidate(record, artifact_dir,
                               WorkingDataset(dest / "dataset").root)
        out["dataset_index"] = WorkingDataset(dest / "dataset").index()
        return out
    finally:
        if tmp is not None:
            tmp.cleanup()


def promotion_gate(meta_mvp: float = 30.0,
                   S: dict[str, float] | None = None) -> dict[str, Any]:
    """La puerta de promoción: GM de un S y lo que exige meta_mvp.

    Sin S, devuelve el DQI necesario (ratio) y el S objetivo para
    meta_mvp. Con S, la GM y si promueve.
    """
    out: dict[str, Any] = {
        "meta_mvp": meta_mvp,
        "required_dqi_ratio": required_dqi_ratio(meta_mvp),
        "target_S_dqi": target_S_for_meta_mvp("dqi", meta_mvp),
    }
    if S is not None:
        gv = promotion_gm(S)
        out.update({"gm": gv, "promote": gv >= meta_mvp, "ratios": S})
    return out


def validate_submission(path: str | Path,
                        task_statuses: dict[str, str] | None = None,
                        mode: str = "full") -> dict[str, Any]:
    """Valida el formato de un submission.zip (o su directorio).

    Entrada: la ruta del ZIP (o del directorio) y, si se dan, los
    estados de los tres verificadores (para la puerta fail-closed
    completa). Salida: si el formato pasa, los motivos, y si se
    puede armar el ZIP (READY solo si la puerta Y el formato pasan).
    """
    from .packaging import (submission_ready, validate_submission_dir,
                            validate_submission_zip)
    p = Path(path)
    packaging = (validate_submission_dir(p) if p.is_dir()
                 else validate_submission_zip(p))
    out = {"packaging": packaging}
    if task_statuses is not None:
        out["submission"] = submission_ready(task_statuses, packaging,
                                             mode=mode)
    return out


OPERATIONS = {
    "evaluate_candidate": evaluate_candidate,
    "apply_morph_tunnel": apply_morph_tunnel,
    "decode_json_config": decode_json_config,
    "run_orchestrator": run_orchestrator,
    "check_integrity": check_integrity,
    "export_module": export_module,
    "validate_submission": validate_submission,
    "promotion_gate": promotion_gate,
}

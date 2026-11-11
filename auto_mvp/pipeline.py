"""AUTO_MVP v0.3.2 — pipeline asíncrono por fases (6 h / 24 h).

El diseño de Arturo: un pipeline por fases que es la única estrategia
viable para pelear el primer lugar. Tres fases, una puerta y un
artefacto con nombre:

  Fase 1 — Filtro rápido (espacio de metadatos). El proxy evalúa
    variantes paramétricas (anchos, densidades, estructuras) en
    milisegundos y descarta millones de combinaciones inviables sin
    instanciar nada pesado. Nada se compila aquí.
  Fase 2 — Promoción por beneficio real. Solo si la estimación
    matemática alcanza la meta definida (por defecto GM estimada
    >= 30.00, frente al baseline 1.00) se da luz verde. La puerta
    usa la fórmula de ponderación de la competencia (media geométrica
    de los ratios por tarea). La estimación es una PROYECCIÓN: la
    promoción significa "vale la pena gastar compilación aquí", no
    "esto va a puntuar 30".
  Fase 3 — Compilación pesada y artefactos. Solo lo promovido llega
    aquí. Se invierten las horas de cómputo y, si el verificador
    oficial lo confirma, se guarda el artefacto en un dataset con
    el número de iteración y la calificación estimada:
    ``i<iteración>-<puntaje>`` (ej. i120549-34.16).

El pipeline es reanudable: corre en bloques con presupuesto de tiempo
(por ejemplo 6 h, lo que permite Kaggle por corrida), guarda el estado
al parar y la siguiente corrida retoma donde quedó. El estado vive en
``runs/state.json``; cada promoción guarda su artefacto en
``runs/i<iter>-<score>/``.

Qué es la meta 30.00 (medido, no prometido): con invsqrt certificado
(20.65x) y química propia (1.0x), una GM de 30.00 exige DQI ~1307x,
es decir S_DQI ~1.87e10, o sea Q²·T ~1.52e10: por ejemplo Q=400 con
T=95,000 da GM 29.99. Por eso "400 cúbits" y "30.00" son la misma meta
dicha dos veces. Con química pública (10.27x) bastaría DQI ~127x
(Q=892, T=196,000 o Q=1,414, T=78,000). La puerta lo calcula y lo
reporta: ``required_dqi_ratio``.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from .vqcc.contracts import REFERENCE_S
from .vqcc.costs import geometric_score, ratio
from .proxy import CandidateMeta, MetadataProxy

# Mejores S propios medidos (los que puntúan hoy). La puerta compara
# contra estos: una tarea que no se está optimizando aporta su mejor.
CURRENT_BEST_S: dict[str, float] = {
    "invsqrt": 100_568.5,      # certificado oficial
    "dqi": 1.99836e13,         # Toom-3+V1+E2 medido (102,400 shots)
    "dfthcsos": 3_355_599_588.32,  # baseline = referencia, ratio 1.0
}

PROMOTION_THRESHOLD = 30.0


def promotion_gm(candidate_S: dict[str, float],
                 current: dict[str, float] | None = None) -> float:
    """GM estimada con el candidato en su tarea y los mejores en las demás."""
    base = dict(CURRENT_BEST_S if current is None else current)
    base.update(candidate_S)
    return geometric_score(base)


def required_dqi_ratio(threshold: float = PROMOTION_THRESHOLD,
                       current: dict[str, float] | None = None) -> float:
    """El ratio DQI que exige la meta, con las otras tareas en su mejor."""
    base = dict(CURRENT_BEST_S if current is None else current)
    others = ratio("invsqrt", base["invsqrt"]) * ratio("dfthcsos", base["dfthcsos"])
    return threshold ** 3 / others


@dataclass
class GateVerdict:
    promote: bool
    gm: float
    ratios: dict[str, float]
    required_dqi_ratio: float
    reasons: list[str] = field(default_factory=list)


class PromotionGate:
    """Fase 2: la puerta de promoción por beneficio real."""

    def __init__(self, threshold: float = PROMOTION_THRESHOLD,
                 current: dict[str, float] | None = None):
        self.threshold = threshold
        self.current = dict(CURRENT_BEST_S if current is None else current)

    def evaluate(self, candidate_S: dict[str, float]) -> GateVerdict:
        scores = dict(self.current)
        scores.update(candidate_S)
        ratios = {t: ratio(t, s) for t, s in scores.items()}
        gm = math.exp(sum(math.log(r) for r in ratios.values()) / len(ratios))
        req = required_dqi_ratio(self.threshold, self.current)
        reasons: list[str] = []
        if gm >= self.threshold:
            reasons.append(
                f"GM estimada {gm:.2f} >= meta {self.threshold:.2f}")
        else:
            reasons.append(
                f"GM estimada {gm:.2f} < meta {self.threshold:.2f}; "
                f"faltan {self.threshold - gm:.2f} puntos "
                f"(DQI necesitaría {req:.0f}x, hoy {ratios.get('dqi', 0):.2f}x)")
        return GateVerdict(promote=gm >= self.threshold, gm=gm,
                           ratios=ratios, required_dqi_ratio=req,
                           reasons=reasons)


def artifact_name(iteration: int, estimated_gm: float) -> str:
    """i<iteración>-<puntaje> con 2 decimales (ej. i120549-34.16)."""
    return f"i{int(iteration)}-{estimated_gm:.2f}"


class ArtifactStore:
    """Fase 3: guarda artefactos promovidos con nombre i<iter>-<score>."""

    def __init__(self, runs_dir: str | Path):
        self.runs_dir = Path(runs_dir)
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def save(self, iteration: int, estimated_gm: float, candidate: dict[str, Any],
             manifest_extra: dict[str, Any] | None = None) -> Path:
        name = artifact_name(iteration, estimated_gm)
        dest = self.runs_dir / name
        dest.mkdir(parents=True, exist_ok=True)
        manifest = {
            "artifact": name,
            "iteration": int(iteration),
            "estimated_gm": round(float(estimated_gm), 2),
            "kind": candidate.get("kind", "candidate"),
            "task": candidate.get("task", ""),
            "S": candidate.get("S"),
            "ratios": candidate.get("ratios", {}),
            "source_commit": candidate.get("source_commit", ""),
            "phase": "PROMOTED",
            "compiled": False,
            "note": "Estimación por proxy. La compilación pesada y el "
                    "verificador oficial confirman o descartan el artefacto.",
        }
        if manifest_extra:
            manifest.update(manifest_extra)
        (dest / "candidate.json").write_text(
            json.dumps(candidate, indent=1, ensure_ascii=False, default=str),
            encoding="utf-8")
        (dest / "manifest.json").write_text(
            json.dumps(manifest, indent=1, ensure_ascii=False),
            encoding="utf-8")
        return dest

    def mark_compiled(self, artifact_dir: str | Path, measured: dict[str, Any]) -> Path:
        """Tras la compilación pesada: registra el resultado medido."""
        dest = Path(artifact_dir)
        manifest = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
        manifest["compiled"] = True
        manifest["measured"] = measured
        manifest["phase"] = ("PASS" if measured.get("official_pass")
                             else "FAIL")
        (dest / "manifest.json").write_text(
            json.dumps(manifest, indent=1, ensure_ascii=False),
            encoding="utf-8")
        return dest


@dataclass
class PipelineResult:
    screened: int
    proxy_rejected: int
    gate_rejected: int
    promoted: int
    best_gm: float
    best: dict[str, Any] | None
    iterations: int
    elapsed_seconds: float
    stopped: str
    artifacts: list[str] = field(default_factory=list)


class Pipeline:
    """Orquesta las 3 fases sobre un flujo de candidatos.

    ``candidate_stream`` produce dicts con "meta" (CandidateMeta o
    dict) y "metrics" (para el S estimado) y opcionalmente "kind"
    ("candidate" para un módulo real, "target" para un punto
    paramétrico hipotético del espacio de metadatos).
    ``compile_fn`` es el gancho de la fase 3: recibe el artefacto
    promovido y devuelve el resultado medido (o None si no se
    compila en esta corrida). Sin compile_fn, la promoción queda
    registrada como PENDING_COMPILATION.
    ``time_budget_seconds`` es el bloque (ej. 6 h = 21600 s): al
    agotarse, el pipeline guarda el estado y para limpio.
    """

    def __init__(self, proxy: MetadataProxy, gate: PromotionGate | None = None,
                 runs_dir: str | Path = "runs",
                 compile_fn: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None,
                 time_budget_seconds: float | None = None,
                 source_commit: str = ""):
        self.proxy = proxy
        self.gate = gate or PromotionGate()
        self.store = ArtifactStore(runs_dir)
        self.runs_dir = Path(runs_dir)
        self.compile_fn = compile_fn
        self.time_budget_seconds = time_budget_seconds
        self.source_commit = source_commit
        self.state_path = self.runs_dir / "state.json"
        self.state = self._load_state()
        self.best_S: dict[str, float] = dict(self.state.get("best_S", {}))
        self.iteration: int = int(self.state.get("iteration", 0))

    def _load_state(self) -> dict[str, Any]:
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                return {}
        return {}

    def _save_state(self) -> None:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps({
            "iteration": self.iteration,
            "best_S": self.best_S,
            "source_commit": self.source_commit,
        }, indent=1, ensure_ascii=False), encoding="utf-8")

    def run(self, candidate_stream: Iterable[dict[str, Any]],
            max_iterations: int | None = None) -> PipelineResult:
        started = time.monotonic()
        screened = proxy_rejected = gate_rejected = promoted = 0
        best_gm = float(self.state.get("best_gm", 0.0))
        best: dict[str, Any] | None = None
        artifacts: list[str] = []
        stopped = "stream agotado"
        for candidate in candidate_stream:
            if max_iterations is not None and self.iteration >= max_iterations:
                stopped = "límite de iteraciones"
                break
            if (self.time_budget_seconds is not None
                    and time.monotonic() - started >= self.time_budget_seconds):
                stopped = "presupuesto de tiempo agotado"
                break
            self.iteration += 1
            screened += 1
            meta = candidate.get("meta")
            if isinstance(meta, dict):
                meta = CandidateMeta(**meta)
            # Fase 1: proxy por metadatos (milisegundos, sin construir).
            best_task_S = self.best_S.get(meta.task, CURRENT_BEST_S[meta.task])
            verdict = self.proxy.evaluate(meta, best_task_S)
            if not verdict.ok:
                proxy_rejected += 1
                continue
            # S estimado del candidato (su tarea) y puerta de promoción.
            from .proxy import estimate_S
            est_S = verdict.s_estimate if verdict.s_estimate is not None else estimate_S(meta)
            cand_S = {meta.task: est_S}
            gate_v = self.gate.evaluate(cand_S)
            if gate_v.gm > best_gm:
                best_gm = gate_v.gm
                best = {"iteration": self.iteration, "gm": gate_v.gm,
                        "S": cand_S, "ratios": gate_v.ratios,
                        "meta": candidate.get("meta"),
                        "kind": candidate.get("kind", "candidate")}
            if not gate_v.promote:
                gate_rejected += 1
                continue
            # Fase 2 superada: promoción. Fase 3: artefacto + compilación.
            promoted += 1
            record = {"iteration": self.iteration, "gm": gate_v.gm,
                      "S": cand_S, "ratios": gate_v.ratios,
                      "task": meta.task, "kind": candidate.get("kind", "candidate"),
                      "meta": candidate.get("meta"),
                      "metrics": candidate.get("metrics", {}),
                      "source_commit": self.source_commit}
            dest = self.store.save(self.iteration, gate_v.gm, record)
            artifacts.append(str(dest))
            if self.compile_fn is not None:
                measured = self.compile_fn(record)
                if measured is not None:
                    self.store.mark_compiled(dest, measured)
        self.state["best_gm"] = best_gm
        self._save_state()
        return PipelineResult(
            screened=screened, proxy_rejected=proxy_rejected,
            gate_rejected=gate_rejected, promoted=promoted,
            best_gm=best_gm, best=best, iterations=self.iteration,
            elapsed_seconds=time.monotonic() - started, stopped=stopped,
            artifacts=artifacts)

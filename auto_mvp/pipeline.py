"""AUTO_MVP v0.3.2 — pipeline asíncrono por fases (6 h / 24 h).

El diseño de Arturo: un pipeline por fases que es la única estrategia
viable para pelear el primer lugar. Tres fases, una puerta y un
artefacto con nombre:

  Fase 1 — Filtro rápido (espacio de metadatos). El proxy evalúa
    variantes paramétricas (anchos, densidades, estructuras) en
    milisegundos y descarta millones de combinaciones inviables sin
    instanciar nada pesado. Nada se compila aquí.
  Fase 2 — Promoción por beneficio real. Solo si la estimación
    matemática alcanza la meta definida se da luz verde. La meta es
    un parámetro ABSOLUTO (``meta_mvp``): el puntaje que se le exige
    al sistema (ej. 30.00), no lo que dictó un envío anterior. Si se
    pide 2, el pipeline poda hasta un circuito que entregue 2; si se
    pide 30 o 50, quema ciclos de búsqueda y prefiltrado hasta topar
    con esa meta o agotar el presupuesto. La puerta usa la fórmula
    de ponderación de la competencia (media geométrica de los ratios
    por tarea) y evalúa la mejora REAL (Toffolis, cúbits, profundidad
    T) frente al baseline oficial, traducida de forma directa al
    puntaje: esa ganancia es la "ventaja pura". La estimación es una
    PROYECCIÓN: la promoción significa "vale la pena gastar
    compilación aquí", no "esto va a puntuar 30".
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

Qué es la meta (medido, no prometido): la puerta mide contra los
componentes del MEJOR ENVÍO, no contra los propios. El mejor envío
(23.94667) usa invsqrt propio certificado (20.65x), DQI público
híbrido (64.76x, S=3.7676e11) y química pública (10.27x,
S=3.268e8): producto 13,732. Medir contra los propios (ensamble
1.998e13, química 1.0x; GM base 2.93) da un GM que no corresponde
al envío real. La meta 30.00 NO es alcanzable con el enfoque
actual (veredicto 2026-11-11, verificado): para 30 el producto debe
ser 27,000 (30^3) contra 13,732 actual (x1.966); solo por DQI
habría que bajar T un 49.1% (DQI 127.3x con química pública). Por
eso la puerta, SIN directiva explícita, promueve mejoras pequeñas
por encima de 23.94667 (``meta_mvp`` por defecto = 23.94667), y
solo se envía lo que pasa los tres verificadores oficiales
(puerta fail-closed, ver numeric_lab.fail_closed_gate). Con una
directiva (ej. meta_mvp=30.00) la barra es ese umbral: el pipeline
quema ciclos hasta alcanzarlo o agotar el presupuesto, y reporta
honestamente si la meta quedó sin alcanzar.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from .healing.heal import Autonomy
from .maxcut import partition_conflict_graph
from .observer import Observer
from .vqcc.calibrate import Calibration, calibrate_from_candidates
from .vqcc.contracts import BEST_GLOBAL_SCORE, BEST_SUBMISSION_S
from .vqcc.costs import geometric_score, ratio
from .vqcc.verify import LocalVerifier
from .proxy import CandidateMeta, MetadataProxy

# Los S que puntúan HOY son los del mejor envío (23.94667), no los
# propios. La puerta compara contra estos: una tarea que no se está
# optimizando aporta su componente del mejor envío.
CURRENT_BEST_S: dict[str, float] = dict(BEST_SUBMISSION_S)

# Sin directiva explícita, la puerta promueve lo que bate el mejor
# envío (23.94667). 30.00 no es la meta por defecto: con el enfoque
# actual no es alcanzable (producto 27,000 vs 13,732).
PROMOTION_THRESHOLD = BEST_GLOBAL_SCORE


def pure_advantage(candidate_S: dict[str, float],
                   current: dict[str, float] | None = None) -> dict[str, Any]:
    """La ventaja pura de un candidato frente al baseline oficial.

    Evalúa la mejora REAL (Toffolis, cúbits, profundidad T) que el
    candidato trae en su tarea, frente al baseline oficial, y la
    traduce de forma directa al puntaje con la fórmula de la
    competencia: por tarea, el ratio = costo de referencia / costo
    propio; el puntaje es la media geométrica de los tres ratios.
    Devuelve {"ratios": {tarea: ratio}, "gm": puntaje}.
    """
    base = dict(CURRENT_BEST_S if current is None else current)
    base.update(candidate_S)
    ratios = {t: ratio(t, s) for t, s in base.items()}
    return {"ratios": ratios, "gm": geometric_score(base)}


def promotion_gm(candidate_S: dict[str, float],
                 current: dict[str, float] | None = None) -> float:
    """GM estimada con el candidato en su tarea y los mejores en las demás."""
    return float(pure_advantage(candidate_S, current)["gm"])


def required_dqi_ratio(meta_mvp: float = PROMOTION_THRESHOLD,
                       current: dict[str, float] | None = None) -> float:
    """El ratio DQI que exige la meta, con las otras tareas en su mejor."""
    base = dict(CURRENT_BEST_S if current is None else current)
    others = ratio("invsqrt", base["invsqrt"]) * ratio("dfthcsos", base["dfthcsos"])
    return meta_mvp ** 3 / others


@dataclass
class GateVerdict:
    promote: bool
    gm: float
    ratios: dict[str, float]
    required_dqi_ratio: float
    reasons: list[str] = field(default_factory=list)


class PromotionGate:
    """Fase 2: la puerta de promoción por beneficio real.

    ``meta_mvp`` es el parámetro ABSOLUTO que se le exige al sistema
    (ej. 30.00). Sin directiva, es el mejor envío (23.94667): la
    puerta promueve lo que lo bate. ``threshold`` es solo el alias
    histórico de ``meta_mvp``.
    """

    def __init__(self, meta_mvp: float = PROMOTION_THRESHOLD,
                 current: dict[str, float] | None = None,
                 threshold: float | None = None):
        self.meta_mvp = float(threshold if threshold is not None else meta_mvp)
        self.threshold = self.meta_mvp  # alias histórico
        self.current = dict(CURRENT_BEST_S if current is None else current)

    def evaluate(self, candidate_S: dict[str, float]) -> GateVerdict:
        adv = pure_advantage(candidate_S, self.current)
        ratios = adv["ratios"]
        gm = adv["gm"]
        req = required_dqi_ratio(self.meta_mvp, self.current)
        reasons: list[str] = []
        if gm >= self.meta_mvp:
            reasons.append(
                f"GM estimada {gm:.2f} >= meta_mvp {self.meta_mvp:.2f}")
        else:
            reasons.append(
                f"GM estimada {gm:.2f} < meta_mvp {self.meta_mvp:.2f}; "
                f"faltan {self.meta_mvp - gm:.2f} puntos "
                f"(DQI necesitaría {req:.0f}x, hoy {ratios.get('dqi', 0):.2f}x)")
        return GateVerdict(promote=gm >= self.meta_mvp, gm=gm,
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
    shadow_skipped: int = 0
    mode: str = "AUTO"
    mode_transitions: list[dict[str, Any]] = field(default_factory=list)
    last_observation: dict[str, Any] | None = None
    partition: dict[str, Any] | None = None
    calibration: dict[str, Any] | None = None
    best_gm_by_side: dict[str, float] = field(default_factory=dict)
    goal_reached: bool = False
    meta_mvp: float = 0.0
    # v0.8.0: módulos exportados al dataset de trabajo.
    exported: int = 0
    dataset_dir: str = ""


class Pipeline:
    """Orquesta las 3 fases sobre un flujo de candidatos.

    ``candidate_stream`` produce dicts con "meta" (CandidateMeta o
    dict) y "metrics" (para el S estimado) y opcionalmente "kind"
    ("candidate" para un módulo real, "target" para un punto
    paramétrico hipotético del espacio de metadatos) y "name" (el
    nombre de la mutación, para ubicarla en la partición MaxCut).
    ``compile_fn`` es el gancho de la fase 3: recibe el artefacto
    promovido y devuelve el resultado medido (o None si no se
    compila en esta corrida). Sin compile_fn, la promoción queda
    registrada como PENDING_COMPILATION.
    ``time_budget_seconds`` es el bloque (ej. 6 h = 21600 s): al
    agotarse, el pipeline guarda el estado y para limpio.

    v0.4.0 — los tres componentes de Arturo engranan aquí:
    - Calibración DCP (``probe``): si se pasa una sonda, el margen
      del proxy, la paciencia (estancamiento) y el presupuesto de
      intentos salen de la calibración, no de un número a mano. La
      sonda debe parecerse a la carga (lección v0.2.1).
    - MaxCut (``conflict_graph``): (nodos, aristas) del grafo de
      conflictos; la partición divide la búsqueda en dos lados y el
      resultado reporta el mejor GM por lado y el estancamiento por
      lado. La partición no reordena el flujo (eso lo hace quien lo
      alimenta): estructura la búsqueda y el reporte.
    - Observer (``observer``): solo observa. Lee el registro de
      trials y escribe observations.jsonl / events.jsonl; nunca veta
      ni cambia nada. Se observa cada ``observe_every`` iteraciones
      y al final de la corrida.
    - Modo (gobernanza DSP, como SearchLoop): 3 fallos seguidos de
      compilación bajan AUTO -> PROPOSE (promueve y guarda, sin
      compilar) -> SHADOW (ni guarda). El modo es de la corrida
      (cada bloque nuevo empieza en AUTO); las transiciones quedan
      en state.json y en el resultado.
    """

    def __init__(self, proxy: MetadataProxy, gate: PromotionGate | None = None,
                 runs_dir: str | Path = "runs",
                 compile_fn: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None,
                 time_budget_seconds: float | None = None,
                 source_commit: str = "",
                 calibration: Calibration | None = None,
                 probe: list[dict[str, Any]] | None = None,
                 verifier: Any | None = None,
                 conflict_graph: tuple[list[str], list[tuple]] | None = None,
                 observer: Observer | None = None,
                 observe_every: int = 50,
                 max_consecutive_compile_failures: int = 3,
                 meta_mvp: float | None = None,
                 tunnel_engine: Any | None = None):
        self.proxy = proxy
        # Motor de tunelamiento MORPH (v0.6.0): si se pasa, el paso
        # "tunnel" del orquestador adaptativo lo usa para transformar
        # candidatos antes (o después) de la puerta.
        self.tunnel_engine = tunnel_engine
        # meta_mvp: la directiva absoluta (ej. 30.00). Si se pasa, manda
        # sobre la puerta por defecto; si se pasa una puerta, manda ella.
        if gate is None and meta_mvp is not None:
            gate = PromotionGate(meta_mvp)
        self.gate = gate or PromotionGate()
        self.meta_mvp = float(self.gate.meta_mvp)
        self.store = ArtifactStore(runs_dir)
        self.runs_dir = Path(runs_dir)
        # Dataset de trabajo (v0.8.0): los módulos promovidos se
        # exportan e inyectan aquí con su estructura completa y su
        # código ejecutable (nunca en /kaggle/input, que es intocable).
        from .dataset import WorkingDataset
        self.dataset = WorkingDataset(self.runs_dir / "dataset")
        self.compile_fn = compile_fn
        self.time_budget_seconds = time_budget_seconds
        self.source_commit = source_commit
        self.state_path = self.runs_dir / "state.json"
        self.state = self._load_state()
        self.best_S: dict[str, float] = dict(self.state.get("best_S", {}))
        self.iteration: int = int(self.state.get("iteration", 0))
        # La clase del mejor (candidate | target): la meta solo la
        # alcanza un candidato real; un target es una hipótesis.
        self.best_kind: str = str(self.state.get("best_kind", ""))
        # Calibración DCP: la sonda manda (margen, paciencia, presupuesto).
        self.calibration = calibration
        if probe is not None:
            self.calibration = calibrate_from_candidates(
                proxy.spec, probe, verifier or LocalVerifier(proxy.spec))
        if self.calibration is not None:
            self.proxy.margin = self.calibration.margin
            self.stagnation_limit: int | None = self.calibration.stagnation_limit
            self.max_trials_default: int | None = self.calibration.max_trials
        else:
            self.stagnation_limit = None
            self.max_trials_default = None
        # MaxCut: partición del grafo de conflictos (una vez, al inicio).
        # conflict_graph: (nodos, aristas) o (nodos, aristas, ganancias);
        # con ganancias la selección por lado es MWIS (v0.5.0).
        self.partition = None
        self.side_of: dict[str, str] = {}
        if conflict_graph is not None:
            nodes, edges = conflict_graph[0], conflict_graph[1]
            gains = conflict_graph[2] if len(conflict_graph) > 2 else None
            self.partition = partition_conflict_graph(nodes, edges)
            for name in self.partition.side_a:
                self.side_of[name] = "A"
            for name in self.partition.side_b:
                self.side_of[name] = "B"
        self.best_gm_by_side: dict[str, float] = dict(
            self.state.get("best_gm_by_side", {}))
        self.since_improvement_by_side: dict[str, int] = {}
        # Observer: solo observa.
        self.observer = observer
        self.observe_every = observe_every
        self.last_observation: dict[str, Any] | None = None
        self.trials_log: list[dict[str, Any]] = []
        # Modo: AUTO -> PROPOSE -> SHADOW (pegajoso dentro de la corrida).
        self.mode = Autonomy.AUTO
        self.mode_transitions: list[dict[str, Any]] = list(
            self.state.get("mode_transitions", []))
        self._consecutive_compile_failures = 0
        self.max_consecutive_compile_failures = max_consecutive_compile_failures

    def tunnel_candidate(self, candidate: dict[str, Any],
                         method: str = "greedy") -> tuple[dict[str, Any], Any | None]:
        """Paso "tunnel": tunela el candidato si trae un grafo de llamadas.

        El candidato trae su grafo en ``candidate["call_graph"]``
        (un CallGraph o su dict). Si el motor no está configurado o
        el candidato no trae grafo, devuelve el candidato tal cual y
        None. Si el túnel baja el T, actualiza las métricas del
        candidato (Q, T) con el costo tunelado y devuelve el
        resultado del túnel.
        """
        from .morph_tunnel import tunnel as morph_tunnel
        from .qualtran_bridge import CallGraph
        if self.tunnel_engine is None:
            return candidate, None
        raw = candidate.get("call_graph")
        if raw is None:
            return candidate, None
        graph = raw if isinstance(raw, CallGraph) else CallGraph.from_dict(raw)
        rules = self.tunnel_engine if isinstance(self.tunnel_engine, list) \
            else getattr(self.tunnel_engine, "rules", None) or []
        res = morph_tunnel(graph, rules, method=method)
        if res.final_T is None or res.baseline_T is None \
                or res.final_T >= res.baseline_T or not res.moves:
            return candidate, res
        new = dict(candidate)
        meta = candidate.get("meta")
        metrics = dict(candidate.get("metrics", {}))
        if res.final_Q is not None:
            metrics["Q"] = res.final_Q
        metrics["T"] = res.final_T
        if isinstance(meta, dict):
            new_meta = dict(meta)
            new_meta["metrics"] = dict(new_meta.get("metrics", {}))
            if res.final_Q is not None:
                new_meta["metrics"]["Q"] = res.final_Q
            new_meta["metrics"]["T"] = res.final_T
            new["meta"] = new_meta
        elif meta is not None:
            from .proxy import CandidateMeta
            new["meta"] = CandidateMeta(
                task=meta.task, metrics=dict(metrics),
                register_widths=dict(getattr(meta, "register_widths", {})),
                gate_density=getattr(meta, "gate_density", None),
                topology=dict(getattr(meta, "topology", {})))
        new["metrics"] = metrics
        new["tunnel"] = res.as_dict()
        # v0.8.0: el grafo que viaja con el candidato es el TUNELADO
        # (res.graph, no el base: tunnel() trabaja sobre una copia).
        # Si el export llevara el grafo base con las métricas
        # tuneladas, la estructura y el S no coincidirían.
        new["call_graph"] = res.graph.to_dict()
        return new, res

    def proxy_eval(self, candidate: dict[str, Any]) -> tuple[Any, float | None]:
        """Fase 1 (extraída para el orquestador): proxy + S estimado."""
        from .proxy import CandidateMeta, estimate_S
        meta = candidate.get("meta")
        if isinstance(meta, dict):
            meta = CandidateMeta(**meta)
        best_task_S = self.best_S.get(meta.task, CURRENT_BEST_S[meta.task])
        verdict = self.proxy.evaluate(meta, best_task_S)
        est = None
        if verdict.ok:
            est = verdict.s_estimate if verdict.s_estimate is not None \
                else estimate_S(meta)
        return verdict, est

    def promote_and_compile(self, record: dict[str, Any],
                            trial: dict[str, Any]) -> tuple[str | None, bool]:
        """Fase 3 (extraída para el orquestador): artefacto + compilación.

        Devuelve (ruta del artefacto o None, shadow_skipped). En
        SHADOW no se guarda nada; en PROPOSE se guarda sin compilar;
        en AUTO se compila con compile_fn y el modo baja si falla
        3 veces seguidas (la gobernanza vive aquí, no en MORPH).

        En PROPOSE y AUTO, el módulo promovido se EXPORTA e INYECTA
        al dataset de trabajo (v0.8.0): su estructura completa y su
        código ejecutable quedan en ``runs/dataset/<nombre>/`` con
        su índice, para evaluarlo y compilarlo. El export queda en
        ``record["export"]``. Esto NO es el submission.zip: ese sigue
        fail-closed (solo los tres verificadores en modo full lo arman).
        """
        if self.mode == Autonomy.SHADOW:
            return None, True
        dest = self.store.save(record["iteration"], record["gm"], record)
        record["artifact_name"] = dest.name
        from .dataset import export_candidate
        try:
            record["export"] = export_candidate(
                record, dest, self.dataset.root)
        except Exception as e:  # el export no debe matar la promoción
            record["export"] = {"error": str(e)}
        if self.mode == Autonomy.PROPOSE:
            return str(dest), False
        if self.compile_fn is not None:
            try:
                measured = self.compile_fn(record)
            except Exception as e:  # el gancho falló: se cuenta, no se muere
                measured = {"official_pass": False, "error": str(e)}
            if measured is not None:
                self.store.mark_compiled(dest, measured)
                if measured.get("official_pass"):
                    self._consecutive_compile_failures = 0
                else:
                    trial["compile_failed"] = True
                    self._consecutive_compile_failures += 1
                    if (self._consecutive_compile_failures
                            >= self.max_consecutive_compile_failures):
                        self._drop_mode(
                            f"compilación falló "
                            f"{self._consecutive_compile_failures} veces seguidas")
        return str(dest), False

    def _drop_mode(self, reason: str) -> None:
        order = [Autonomy.AUTO, Autonomy.PROPOSE, Autonomy.SHADOW]
        i = order.index(self.mode)
        if i >= len(order) - 1:
            return
        old = self.mode
        self.mode = order[i + 1]
        transition = {"from": old.value, "to": self.mode.value,
                      "reason": reason, "iteration": self.iteration,
                      "ts": time.time()}
        self.mode_transitions.append(transition)
        self._consecutive_compile_failures = 0

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
            "best_gm": self.state.get("best_gm", 0.0),
            "best_kind": self.best_kind,
            "best_gm_by_side": self.best_gm_by_side,
            "mode_transitions": self.mode_transitions,
            "source_commit": self.source_commit,
        }, indent=1, ensure_ascii=False), encoding="utf-8")

    def _observe(self) -> None:
        if self.observer is not None:
            self.last_observation = self.observer.observe(
                self.trials_log, self.iteration)
            # El observador NUNCA veta: solo reporta. Es el LAZO el
            # que lee su reporte y gobierna (como en primitive.v7, donde
            # la gobernanza es una capa aparte y desactivada por
            # defecto): un régimen CONFLICTO o INSUFICIENTE baja un
            # escalón de autonomía.
            regime = self.last_observation.get("regime")
            if regime in ("CONFLICTO", "INSUFICIENTE"):
                self._drop_mode(f"observer: régimen {regime}")

    def run(self, candidate_stream: Iterable[dict[str, Any]],
            max_iterations: int | None = None) -> PipelineResult:
        started = time.monotonic()
        screened = proxy_rejected = gate_rejected = promoted = 0
        shadow_skipped = 0
        exported = 0  # v0.8.0: módulos exportados al dataset en esta corrida
        best_gm = float(self.state.get("best_gm", 0.0))
        best_kind = self.best_kind
        best: dict[str, Any] | None = None
        artifacts: list[str] = []
        stopped = "stream agotado"
        # Presupuesto de intentos: el explícito, o el calibrado (DCP).
        run_limit = (max_iterations if max_iterations is not None
                     else self.max_trials_default)
        run_count = 0
        since_improvement = 0
        for candidate in candidate_stream:
            if run_limit is not None and run_count >= run_limit:
                stopped = "límite de iteraciones"
                break
            if (self.time_budget_seconds is not None
                    and time.monotonic() - started >= self.time_budget_seconds):
                stopped = "presupuesto de tiempo agotado"
                break
            if (self.stagnation_limit is not None
                    and since_improvement >= self.stagnation_limit
                    and (self.partition is None or all(
                        v >= self.stagnation_limit
                        for v in self.since_improvement_by_side.values()))):
                stopped = "estancamiento"
                break
            # Meta ya alcanzada en una corrida anterior (estado reanudado):
            # solo cuenta si el mejor era un candidato real, no un target.
            if best_gm >= self.gate.meta_mvp and best_kind == "candidate":
                stopped = (f"meta alcanzada: GM {best_gm:.2f} >= "
                           f"meta_mvp {self.gate.meta_mvp:.2f}")
                break
            self.iteration += 1
            run_count += 1
            screened += 1
            meta = candidate.get("meta")
            if isinstance(meta, dict):
                meta = CandidateMeta(**meta)
            side = self.side_of.get(candidate.get("name", "")) or None
            kind = candidate.get("kind", "candidate")
            trial: dict[str, Any] = {"S": None, "passed": False,
                                     "accepted": False, "integrity_veto": False,
                                     "kind": kind, "compile_failed": False}
            self.trials_log.append(trial)
            # Fase 1: proxy por metadatos (milisegundos, sin construir).
            best_task_S = self.best_S.get(meta.task, CURRENT_BEST_S[meta.task])
            verdict = self.proxy.evaluate(meta, best_task_S)
            if not verdict.ok:
                proxy_rejected += 1
                if self.observer is not None and self.iteration % self.observe_every == 0:
                    self._observe()
                continue
            # S estimado del candidato (su tarea) y puerta de promoción.
            from .proxy import estimate_S
            est_S = verdict.s_estimate if verdict.s_estimate is not None else estimate_S(meta)
            trial["S"] = est_S
            trial["passed"] = True
            cand_S = {meta.task: est_S}
            gate_v = self.gate.evaluate(cand_S)
            improved = gate_v.gm > best_gm
            if improved:
                best_gm = gate_v.gm
                best_kind = kind
                self.best_kind = kind
                since_improvement = 0
                best = {"iteration": self.iteration, "gm": gate_v.gm,
                        "S": cand_S, "ratios": gate_v.ratios,
                        "meta": candidate.get("meta"),
                        "kind": kind}
                if side is not None:
                    self.best_gm_by_side[side] = gate_v.gm
                    self.since_improvement_by_side[side] = 0
            else:
                since_improvement += 1
                if side is not None:
                    self.since_improvement_by_side[side] = (
                        self.since_improvement_by_side.get(side, 0) + 1)
            if not gate_v.promote:
                gate_rejected += 1
                if self.observer is not None and self.iteration % self.observe_every == 0:
                    self._observe()
                continue
            # Fase 2 superada: promoción. Fase 3: artefacto + compilación.
            trial["accepted"] = True
            promoted += 1
            record = {"iteration": self.iteration, "gm": gate_v.gm,
                      "S": cand_S, "ratios": gate_v.ratios,
                      "task": meta.task, "kind": kind,
                      "meta": candidate.get("meta"),
                      "metrics": candidate.get("metrics", {}),
                      # v0.8.0: la estructura completa y el código del
                      # módulo viajan con el record (para el export al
                      # dataset de trabajo, no solo las métricas).
                      "call_graph": candidate.get("call_graph"),
                      "source": candidate.get("source"),
                      "integrity": candidate.get("integrity"),
                      "source_commit": self.source_commit}
            dest, shadow = self.promote_and_compile(record, trial)
            if shadow:
                shadow_skipped += 1
                if self.observer is not None and self.iteration % self.observe_every == 0:
                    self._observe()
                continue
            if dest is not None:
                artifacts.append(dest)
                if record.get("export") and "error" not in record["export"]:
                    exported += 1
            if self.observer is not None and self.iteration % self.observe_every == 0:
                self._observe()
            # Parada por meta: la barra la dicta meta_mvp, no el flujo.
            # Solo un CANDIDATO real (un circuito/módulo) alcanza la
            # meta: un target es una hipótesis paramétrica (vale la
            # pena compilarla, pero no es el circuito que entrega el
            # puntaje), así que su promoción no para la búsqueda.
            if best_gm >= self.gate.meta_mvp and best_kind == "candidate":
                stopped = (f"meta alcanzada: GM {best_gm:.2f} >= "
                           f"meta_mvp {self.gate.meta_mvp:.2f}")
                break
        self._observe()
        self.state["best_gm"] = best_gm
        self._save_state()
        return PipelineResult(
            screened=screened, proxy_rejected=proxy_rejected,
            gate_rejected=gate_rejected, promoted=promoted,
            best_gm=best_gm, best=best, iterations=self.iteration,
            elapsed_seconds=time.monotonic() - started, stopped=stopped,
            artifacts=artifacts, shadow_skipped=shadow_skipped,
            mode=self.mode.value, mode_transitions=self.mode_transitions,
            last_observation=self.last_observation,
            partition=(self.partition.as_dict() if self.partition else None),
            calibration=(self.calibration.as_dict() if self.calibration else None),
            best_gm_by_side=dict(self.best_gm_by_side),
            goal_reached=(best_gm >= self.gate.meta_mvp
                          and best_kind == "candidate"),
            meta_mvp=self.gate.meta_mvp,
            exported=exported,
            dataset_dir=str(self.dataset.root))

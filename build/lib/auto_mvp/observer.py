"""AUTO_MVP v0.4.0 — Observer (port de PRIMITIVE OBSERVER v0.7).

El Observer de Arturo (``primitive.v7``, 2026-11-11) tiene dos ideas
que aquí se respetan al pie de la letra:

1. OBSERVE_ONLY: gobernanza DESACTIVADA, veto DESACTIVADO. El
   observador lee, reporta y escribe su bitácora; nunca decide,
   nunca veta, nunca toca la búsqueda. Los vetos viven en el lazo
   (SearchLoop / Pipeline), no en el observador. Cada observación
   lleva ``governance: {enabled: False, veto: False,
   decision: "OBSERVE_ONLY"}``.
2. La membrana de observabilidad adaptativa (AOM): term_u =
   exp(-|valor - baseline| / baseline); regímenes ESTABLE (>=0.95),
   MODERADO (>=0.70), INESTABLE (resto); inercia por régimen
   (ESTABLE 12, MODERADO 5, INESTABLE 0); observable suavizado;
   divergencia = |term_u - observable|; si la divergencia pasa de
   0.25, observable = term_u, inercia 0, régimen INESTABLE.

LA CORRECCIÓN RESPECTO A v0.7: en ``text_observe`` el régimen
dependía del parámetro ``condition`` — el mismo texto neutro daba
ESTABLE con NONE y CONFLICTO con CONFLICT porque el código fijaba
conflict=0.85 por decreto. Aquí NO hay parámetro ``condition``:
cada señal se DERIVA de la bitácora de la corrida (los trials del
ledger). El régimen es una función pura de los datos; el test lo
prueba (mismos trials, mismo régimen, no hay entrada que lo
decrete).

Señales (de los trials, nunca inventadas):
- noise: dispersión relativa de los |ΔS|/S recientes (hasta 12,
  el HIST_N base de la calibración DCP).
- conflict: (vetos de integridad + fallos) / trials. Fallo real es
  un módulo real que rompe el contrato o una compilación que falló;
  el cribado de un target sintético no cuenta (es el filtro
  trabajando).
- sufficiency: fracción de trials con veredicto usable
  (pasó el contrato y S finito).
- term_u: la membrana sobre la S reciente contra la mediana anterior.
Régimen (mismos cortes que text_observe): conflict > 0.65 →
CONFLICTO; sufficiency < 0.40 → INSUFICIENTE; noise > 0.30 →
RUIDOSO; term_u < 0.75 → MODERADO; si no, ESTABLE.
"""
from __future__ import annotations

import json
import math
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

OBSERVE_ONLY = {"enabled": False, "veto": False, "decision": "OBSERVE_ONLY"}


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(x)))


class AdaptiveObservabilityMembrane:
    """Port fiel de la AOM de primitive.v7."""

    def __init__(self):
        self.term_u = 1.0
        self.observable = 1.0
        self.divergence = 0.0
        self.regime = "INESTABLE"
        self.previous_regime = "INESTABLE"
        self.inertia_cycles = 0
        self.transition_count = 0

    def update(self, value: float, baseline: float) -> bool:
        baseline = baseline if baseline > 0 else 1.0
        self.term_u = _clamp(math.exp(-abs(value - baseline) / baseline))
        if self.term_u >= 0.95:
            new_regime = "ESTABLE"
        elif self.term_u >= 0.70:
            new_regime = "MODERADO"
        else:
            new_regime = "INESTABLE"
        transitioned = new_regime != self.previous_regime
        if transitioned:
            self.transition_count += 1
            self.inertia_cycles = {"ESTABLE": 12, "MODERADO": 5,
                                    "INESTABLE": 0}[new_regime]
            self.previous_regime = new_regime
        self.regime = new_regime
        if self.inertia_cycles > 0:
            self.inertia_cycles -= 1
            self.observable = _clamp(0.85 + 0.6 * (self.observable - 0.85),
                                     0.82, 0.91)
            if abs(self.term_u - self.observable) > 0.25:
                self.observable = self.term_u
                self.inertia_cycles = 0
                self.regime = "INESTABLE"
        else:
            self.observable = self.term_u
        self.divergence = abs(self.term_u - self.observable)
        return transitioned


def observe_trials(trials: list[dict[str, Any]]) -> dict[str, Any]:
    """Régimen de la corrida, derivado SOLO de los trials.

    Cada trial: {"S": float, "accepted": bool, "passed": bool,
    "integrity_veto": bool}. Sin trials, no hay observación (se
    devuelve regime "SIN_DATOS", no se inventa un régimen).
    """
    if not trials:
        return {"schema": "auto_mvp.observation.v0.4.0",
                "regime": "SIN_DATOS", "term_u": None, "noise": None,
                "conflict": None, "sufficiency": None,
                "governance": dict(OBSERVE_ONLY)}
    n = len(trials)
    usable = [t for t in trials
              if t.get("passed") and isinstance(t.get("S"), (int, float))
              and math.isfinite(t["S"]) and t["S"] > 0]
    sufficiency = len(usable) / n
    vetoes = sum(1 for t in trials if t.get("integrity_veto"))
    # Fallos reales: un módulo real que rompe el contrato, o una
    # compilación que falló. El cribado de un target sintético no es
    # un fallo: es el filtro trabajando.
    failures = sum(1 for t in trials
                   if (not t.get("passed")
                       and t.get("kind", "candidate") == "candidate")
                   or t.get("compile_failed"))
    conflict = (vetoes + failures) / n
    # Noise: dispersión relativa de los |ΔS|/S recientes (máx. 12).
    s_vals = [t["S"] for t in usable]
    if len(s_vals) >= 2:
        rel = [abs((b - a) / a) for a, b in zip(s_vals, s_vals[1:])][-12:]
        noise = statistics.pstdev(rel) if len(rel) >= 2 else 0.0
    else:
        noise = 0.0
    # term_u: la S reciente contra la mediana anterior (membrana).
    if len(s_vals) >= 2:
        half = max(1, len(s_vals) // 2)
        baseline = statistics.median(s_vals[:-half]) if len(s_vals[:-half]) else s_vals[0]
        value = statistics.median(s_vals[-half:])
        term_u = _clamp(math.exp(-abs(value - baseline) / baseline)) if baseline > 0 else 1.0
    else:
        term_u = 1.0
    if conflict > 0.65:
        regime = "CONFLICTO"
    elif sufficiency < 0.40:
        regime = "INSUFICIENTE"
    elif noise > 0.30:
        regime = "RUIDOSO"
    elif term_u < 0.75:
        regime = "MODERADO"
    else:
        regime = "ESTABLE"
    return {"schema": "auto_mvp.observation.v0.4.0",
            "regime": regime, "term_u": round(term_u, 6),
            "noise": round(noise, 6), "conflict": round(conflict, 6),
            "sufficiency": round(sufficiency, 6),
            "trials": n, "usable": len(usable),
            "vetoes": vetoes, "failures": failures,
            "governance": dict(OBSERVE_ONLY)}


@dataclass
class Observer:
    """Observador de la corrida: lee el ledger, escribe su bitácora.

    Nunca veta ni modifica nada. Escribe ``observations.jsonl`` y,
    en transición de régimen o divergencia >= 0.05, ``events.jsonl``.
    """

    runs_dir: str | Path
    _membrane: AdaptiveObservabilityMembrane = field(
        default_factory=AdaptiveObservabilityMembrane)
    _last_regime: str | None = None
    observations: int = 0

    def __post_init__(self):
        self.runs_dir = Path(self.runs_dir)
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def _append(self, path: Path, record: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def observe(self, trials: list[dict[str, Any]],
                iteration: int) -> dict[str, Any]:
        obs = observe_trials(trials)
        obs["iteration"] = int(iteration)
        obs["ts"] = time.time()
        # La membrana sigue la S reciente (si hay datos usables).
        usable = [t["S"] for t in trials
                  if t.get("passed") and isinstance(t.get("S"), (int, float))
                  and math.isfinite(t["S"]) and t["S"] > 0]
        transitioned = False
        if len(usable) >= 2:
            half = max(1, len(usable) // 2)
            baseline = statistics.median(usable[:-half]) if usable[:-half] else usable[0]
            value = statistics.median(usable[-half:])
            transitioned = self._membrane.update(value, baseline)
            obs["membrane"] = {"term_u": round(self._membrane.term_u, 6),
                               "observable": round(self._membrane.observable, 6),
                               "divergence": round(self._membrane.divergence, 6),
                               "regime": self._membrane.regime,
                               "transition_count": self._membrane.transition_count}
        self._append(self.runs_dir / "observations.jsonl", obs)
        self.observations += 1
        regime_changed = self._last_regime is not None and obs["regime"] != self._last_regime
        self._last_regime = obs["regime"]
        div = obs.get("membrane", {}).get("divergence", 0.0)
        if transitioned or regime_changed or div >= 0.05:
            self._append(self.runs_dir / "events.jsonl", {
                "schema": "auto_mvp.event.v0.4.0",
                "ts": time.time(), "iteration": int(iteration),
                "event_type": ("REGIME_TRANSITION" if (transitioned or regime_changed)
                               else "OBSERVABLE_DIVERGENCE"),
                "regime": obs["regime"],
                "membrane": obs.get("membrane", {}),
                "governance": dict(OBSERVE_ONLY)})
        return obs

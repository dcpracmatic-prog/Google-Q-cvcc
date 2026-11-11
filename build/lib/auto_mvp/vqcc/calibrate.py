"""Calibración de arranque del harness VQCC — v0.2.1-vqcc.

Idea tomada de los archivos DSP de Arturo (calibrar_dsp.py /
dsp_profiler_11.py y _15.py): no poner las constantes del lazo a mano,
medir primero con algo barato y derivarlas de la medida.

En el DSP la medida es el jitter de latencia de un micro-benchmark
(matmul 120x120) y la firma es [C, B, G, A_adapt], adimensional y
comparable entre máquinas. Aquí la medida es una sonda de S: se evalúan
unos pocos candidatos de prueba (por ejemplo el baseline y varias
mutaciones de un solo nodo, como la tabla del Notebook 1) con el
cribado barato de costo, y la firma se calcula sobre esos S reales.

Lo que se deriva de la sonda (nunca se inventa):
- margin: el percentil 95 de |ΔS|/S entre los candidatos de prueba.
  Una mejora solo cuenta si baja S más que ese margen: así un cambio
  de 0.001% no reinicia el contador de estancamiento como si fuera real.
- stagnation_limit: paciencia del detector, 5 + ruido*10 (5..15).
  Análogo a HIST_N = 12 + ruido*48 del DSP.
- max_trials: presupuesto de intentos, 20 + ruido*40 (20..60).
  Análogo a intervalo = 5 + ruido*15 del DSP.
- regime: ESTABLE / MODERADO / RUIDOSO, con los mismos cortes del
  DSP (ruido < 0.25 / < 0.55). El régimen solo etiqueta; lo que manda
  son los números derivados.

La calibración es costosa en tiempo (una evaluación por candidato de
prueba) y determinista por sonda: se cachea a nivel de módulo (una sola
medición por sonda, como dsp_profiler_15.py); `force=True` re-mide.

LÍMITES HONESTOS:
- La sonda mide la dispersión del vecindario del baseline con el
  cribado de costo, no el ruido del verificador oficial. El margen es
  una escala del paisaje, no una incertidumbre estadística de S.
- Si todos los candidatos de prueba dan el mismo S, el margen es 0
  y el comportamiento es el viejo (cualquier baja cuenta). Eso se
  registra en la calibración, no se esconde.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Optional

from .contracts import CircuitSpec

# Cortes de régimen, los mismos que dsp_profiler (factor_ruido < 0.25 /
# < 0.55). Son etiquetas, no umbrales de contrato.
NOISE_STABLE_MAX = 0.25
NOISE_MODERATE_MAX = 0.55
# El margen nunca pasa de 25%: una sonda más dispersa que eso no es
# un paisaje, es que los candidatos de prueba no son comparables.
MARGIN_CAP = 0.25

_CALIBRATION_CACHE: dict[tuple, "Calibration"] = {}


def _percentile(values: list[float], pct: float) -> float:
    """Percentil lineal (sin numpy: el harness es stdlib)."""
    if not values:
        raise ValueError("percentil de lista vacía")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (pct / 100.0)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return ordered[lo]
    frac = rank - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


def extract_signature(probe_S: list[float], baseline_S: float) -> dict[str, float]:
    """Firma [C, B, G, A_adapt] de una sonda de S reales.

    probe_S: S medidos (cribado de costo) de los candidatos de prueba.
    baseline_S: S del baseline del spec (debe ser > 0 y finito).
    Las cuatro componentes son adimensionales en [0, 1], como en el DSP:
    - C: estabilidad, 1/(1+var(r)), r = (S-baseline)/baseline.
    - B: cercanía, exp(-|mediana(r)|): qué tan lejos del baseline está
      el candidato típico de la sonda.
    - G: suavidad, 1/(1+media|Δr|): cuánto salta S entre sondas vecinas.
    - A_adapt: cola, exp(-|p99-p95|/(p95+eps)) sobre los S crudos
      (positivos, como las latencias del DSP). Si p95 es ~0, A=1 cuando
      la cola también es ~0, 0 en caso contrario.
    """
    if baseline_S <= 0 or not math.isfinite(baseline_S):
        raise ValueError(f"baseline_S debe ser > 0 y finito, no {baseline_S!r}")
    if not probe_S:
        raise ValueError("la sonda necesita al menos un S medido")
    for s in probe_S:
        if not math.isfinite(s) or s <= 0:
            raise ValueError(f"la sonda recibió un S no válido: {s!r}")
    rel = [(s - baseline_S) / baseline_S for s in probe_S]
    var_r = statistics.pvariance(rel) if len(rel) > 1 else 0.0
    c = 1.0 / (1.0 + var_r)
    b = math.exp(-abs(statistics.median(rel)))
    diffs = [abs(rel[i + 1] - rel[i]) for i in range(len(rel) - 1)]
    g = 1.0 / (1.0 + (sum(diffs) / len(diffs) if diffs else 0.0))
    p95 = _percentile(probe_S, 95)
    p99 = _percentile(probe_S, 99)
    if p95 < 1e-12:
        a = 1.0 if p99 < 1e-12 else 0.0
    else:
        a = math.exp(-abs(p99 - p95) / (p95 + 1e-9))
    return {"C": c, "B": b, "G": g, "A_adapt": a}


@dataclass(frozen=True)
class Calibration:
    """Resultado de la calibración de arranque. Todo derivado, nada a mano."""
    task: str
    baseline_S: float
    signature: dict[str, float]
    noise_factor: float  # 1 - A_adapt, en [0, 1]
    margin: float  # p95(|ΔS|/S) de la sonda, cap 0.25
    stagnation_limit: int  # 5 + ruido*10
    max_trials: int  # 20 + ruido*40
    regime: str  # ESTABLE / MODERADO / RUIDOSO
    n_probes: int
    probe_median_S: float = field(default=0.0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "baseline_S": self.baseline_S,
            "signature": dict(self.signature),
            "noise_factor": self.noise_factor,
            "margin": self.margin,
            "stagnation_limit": self.stagnation_limit,
            "max_trials": self.max_trials,
            "regime": self.regime,
            "n_probes": self.n_probes,
            "probe_median_S": self.probe_median_S,
        }


def calibrate(spec: CircuitSpec, probe_S: list[float],
              force: bool = False) -> Calibration:
    """Calibra a partir de S ya medidos de la sonda. Cachea por sonda.

    probe_S: lista de S reales (cribado de costo) de los candidatos de
    prueba. No se inventan: si la lista está vacía o trae un S no
    finito o <= 0, falla visible (regla del DSP v9: nunca correr con
    datos falsos).
    """
    key = (spec.task, spec.baseline_S, tuple(probe_S))
    if not force and key in _CALIBRATION_CACHE:
        return _CALIBRATION_CACHE[key]
    signature = extract_signature(probe_S, spec.baseline_S)
    noise = float(min(1.0, max(0.0, 1.0 - signature["A_adapt"])))
    rel_abs = [abs((s - spec.baseline_S) / spec.baseline_S) for s in probe_S]
    margin = min(_percentile(rel_abs, 95), MARGIN_CAP)
    stagnation_limit = 5 + round(noise * 10)
    max_trials = 20 + round(noise * 40)
    if noise < NOISE_STABLE_MAX:
        regime = "ESTABLE"
    elif noise < NOISE_MODERATE_MAX:
        regime = "MODERADO"
    else:
        regime = "RUIDOSO"
    cal = Calibration(
        task=spec.task,
        baseline_S=spec.baseline_S,
        signature=signature,
        noise_factor=noise,
        margin=margin,
        stagnation_limit=stagnation_limit,
        max_trials=max_trials,
        regime=regime,
        n_probes=len(probe_S),
        probe_median_S=statistics.median(probe_S),
    )
    _CALIBRATION_CACHE[key] = cal
    return cal


def calibrate_from_candidates(spec: CircuitSpec, candidates: list[dict[str, Any]],
                              verifier: Any, force: bool = False) -> Calibration:
    """Calibración de arranque: evalúa los candidatos de prueba y calibra.

    candidates: dicts de candidato (con "metrics"), típicamente el
    baseline y varias mutaciones de un solo nodo. verifier: un
    LocalVerifier (o compatible con .verify(candidate)). Cada candidato
    se evalúa una vez con el cribado barato; si alguno no da un S
    finito, la calibración falla visible en vez de calibrar con basura.
    """
    probe_S: list[float] = []
    for cand in candidates:
        result = verifier.verify(cand)
        s = result.S
        if not result.ok:
            raise ValueError(
                f"la sonda no puede usar el candidato "
                f"{cand.get('name', cand.get('mutation', '?'))}: rompe el "
                f"contrato (fallos: {result.failures})")
        if not math.isfinite(s) or s <= 0:
            raise ValueError(
                f"la sonda no pudo medir S del candidato "
                f"{cand.get('name', cand.get('mutation', '?'))}: S={s!r} "
                f"(fallos: {result.failures})")
        probe_S.append(float(s))
    return calibrate(spec, probe_S, force=force)


def clear_calibration_cache() -> None:
    """Vacía el caché de calibración (para tests o cambio de máquina)."""
    _CALIBRATION_CACHE.clear()

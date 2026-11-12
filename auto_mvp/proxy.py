"""AUTO_MVP — evaluación proxy en el espacio de metadatos (desde v0.3.0).

La propuesta de Arturo (2026-11-11): en lugar de compilar, sintetizar
o simular cada variante completa, evaluar una función de costo
simplificada sobre la representación abstracta o los parámetros de
entrada (anchos de registro, densidades de compuertas, restricciones
topológicas). Si la estimación preliminar viola las ponderaciones del
validador, la variante se descarta al instante, sin consumir recursos
de compilación.

Reglas de este módulo (las dos lecciones medidas):

1. El proxy es FILTRO y RANKING, nunca veredicto. El proxy rechaza
   lo que viola restricciones duras (el validador como filtro de
   entrada) y ordena el resto por S estimado. Solo el verificador
   oficial y el filtro de integridad aceptan un candidato.
2. El proxy se CALIBRA con una sonda parecida a la carga real. El
   margen es p95(|estimado - medido| / medido), acotado a 0.25 (la
   misma regla de vqcc/calibrate.py). Con una sonda ancha el margen
   capaba en 25% y habría descartado la mejora real del 13.9%: por
   eso la sonda debe parecerse al vecindario que se va a explorar.

El mérito de aceptación sigue siendo el S OFICIAL. La función
ponderada de la especificación v0.0.1 (alpha·Q² + beta·Toffoli +
gamma·T) existe aquí solo como ``proxy_merit`` explícito: ordena
distinto que S y nunca decide una aceptación.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .vqcc.costs import s_dqi, s_invsqrt, s_chem
from .vqcc.contracts import CircuitSpec

MARGIN_CAP = 0.25


@dataclass
class CandidateMeta:
    """Metadatos de una variante, antes de construir nada.

    task: 'invsqrt' | 'dqi' | 'dfthcsos'.
    metrics: los números que pide la fórmula de S de su tarea
        (DQI: Q, T, eps_plus; invsqrt: Q, toffoli, t_count, y
        rotations + rel_error si el circuito tiene rotaciones Z_POW
        finas (v0.9.1: sin rel_error no se puede cobrar la síntesis
        y el proxy lo rechaza); química: lambda_eff, Ttot, Qtot).
        Pueden ser estimados, no medidos.
    register_widths: ancho en qubits por registro (ej. {"S": 840,
        "C": 432, "B": 432}).
    gate_density: Toffolis estimados por unidad que se quiera auditar
        (opcional, informativo).
    topology: restricciones que la variante declara (ej. {"max_qubits":
        1414, "max_toffoli": 1500000}).
    """
    task: str
    metrics: dict[str, Any] = field(default_factory=dict)
    register_widths: dict[str, int] = field(default_factory=dict)
    gate_density: float | None = None
    topology: dict[str, Any] = field(default_factory=dict)

    @property
    def total_qubits(self) -> int:
        return sum(self.register_widths.values())


@dataclass
class ProxyVerdict:
    verdict: str  # "pass" | "reject"
    s_estimate: float | None
    margin: float
    reasons: list[str] = field(default_factory=list)
    proxy_merit: float | None = None  # suma ponderada, solo ranking

    @property
    def ok(self) -> bool:
        return self.verdict == "pass"


def proxy_merit(meta: CandidateMeta, alpha: float = 1.0,
                beta: float = 1.0, gamma: float = 1.0) -> float | None:
    """Mérito ponderado alpha·Q² + beta·Toffoli + gamma·T (spec v0.0.1).

    SOLO para ordenar. No es el S oficial y nunca decide una
    aceptación: una suma ponderada ordena los candidatos distinto
    que S. Si falta algún número, devuelve None.
    """
    m = meta.metrics
    try:
        if meta.task == "dqi":
            return alpha * float(m["Q"]) ** 2 + beta * float(m["T"]) + gamma * 0.0
        if meta.task == "invsqrt":
            return alpha * float(m["Q"]) ** 2 + beta * float(m.get("toffoli", 0)) + gamma * float(m.get("t_count", 0))
        return None
    except (KeyError, TypeError, ValueError):
        return None


def estimate_S(meta: CandidateMeta) -> float:
    """S estimado desde los metadatos, con la fórmula oficial."""
    m = meta.metrics
    if meta.task == "dqi":
        return s_dqi(m["Q"], m["T"], m["eps_plus"])
    if meta.task == "invsqrt":
        # v0.9.1: el costo incluye la síntesis de rotaciones (la
        # fórmula del verificador oficial). El rel_error es el e1
        # del prefiltro: si el candidato trae grado/segmentos y no
        # trae rel_error, se saca de la tabla del Lab.
        rel_error = m.get("rel_error")
        if rel_error is None and "degree" in m and "segments" in m:
            from .numeric_lab import rel_error_for
            rel_error = rel_error_for(int(m["degree"]), int(m["segments"]))
        return s_invsqrt(m["Q"], m.get("toffoli", 0), m.get("t_count", 0),
                         rotations=m.get("rotations", 0),
                         rel_error=rel_error)
    if meta.task == "dfthcsos":
        return s_chem(m["lambda_eff"], m["Ttot"], m["Qtot"])
    raise ValueError(f"tarea desconocida: {meta.task!r}")


def calibrate_proxy(pairs: list[tuple[float, float]]) -> float:
    """Margen del proxy desde pares (estimado, medido).

    p95(|estimado - medido| / medido), acotado a 0.25. Con menos de
    3 pares no hay estadística: margen conservador 0.25.
    """
    if len(pairs) < 3:
        return MARGIN_CAP
    rel = [abs(est - meas) / meas for est, meas in pairs if meas > 0]
    if not rel:
        return MARGIN_CAP
    rel.sort()
    idx = min(len(rel) - 1, int(math.ceil(0.95 * len(rel))) - 1)
    return min(MARGIN_CAP, rel[idx])


class MetadataProxy:
    """Prefiltro por metadatos: el validador como filtro de entrada.

    ``hard_caps`` son las restricciones que ninguna variante puede
    violar (ej. {"max_qubits": 2000, "max_toffoli": 2000000}).
    ``margin`` es el margen calibrado: una variante solo se considera
    prometedora si su S estimado baja del mejor S visto por más que
    el margen (igual que la regla de aceptación de v0.2.1).
    ``numeric_prefilter`` activa el prefiltro en flotante del Lab
    (numeric_lab): si la variante invsqrt trae "degree" y "segments"
    en sus métricas y esa combinación no puede pasar 2^-24 ni en
    flotante, se descarta antes de estimar el costo. Es un filtro
    barato (una tabla), no un veredicto: pasar el prefiltro no
    significa que el circuito exista.
    """

    def __init__(self, spec: CircuitSpec, hard_caps: dict[str, Any] | None = None,
                 margin: float = MARGIN_CAP, numeric_prefilter: bool = False):
        self.spec = spec
        self.hard_caps = dict(hard_caps or {})
        self.margin = margin
        self.numeric_prefilter = numeric_prefilter

    def evaluate(self, meta: CandidateMeta, best_S: float) -> ProxyVerdict:
        reasons: list[str] = []
        if meta.task != self.spec.task:
            return ProxyVerdict("reject", None, self.margin,
                                [f"tarea {meta.task!r} != {self.spec.task!r}"])
        # 0. Prefiltro numérico del Lab (invsqrt: grado/segmentos).
        if (self.numeric_prefilter and meta.task == "invsqrt"
                and "degree" in meta.metrics and "segments" in meta.metrics):
            from .numeric_lab import float_pass_table
            key = (int(meta.metrics["degree"]), int(meta.metrics["segments"]))
            if not float_pass_table().get(key, False):
                return ProxyVerdict(
                    "reject", None, self.margin,
                    [f"prefiltro numérico: grado {key[0]} / {key[1]} segmentos "
                     f"no pasa 2^-24 ni en flotante (Lab numeric_lab)"])
        # 1. Restricciones duras: el validador como filtro de entrada.
        max_q = self.hard_caps.get("max_qubits")
        if max_q is not None and meta.total_qubits > max_q:
            reasons.append(
                f"qubits {meta.total_qubits} > tope {max_q}")
        max_t = self.hard_caps.get("max_toffoli")
        t = meta.metrics.get("T", meta.metrics.get("toffoli"))
        if max_t is not None and t is not None and t > max_t:
            reasons.append(f"toffolis {t} > tope {max_t}")
        # 2. Contrato oficial sobre las métricas (eps+, errores, ...).
        fails = self.spec.check_metrics(dict(meta.metrics))
        reasons.extend(fails)
        if reasons:
            return ProxyVerdict("reject", None, self.margin, reasons)
        # 3. Estimación y comparación con margen.
        try:
            est = estimate_S(meta)
        except (KeyError, TypeError, ValueError) as e:
            return ProxyVerdict("reject", None, self.margin,
                                [f"S no estimable desde metadatos: {e}"])
        if not (math.isfinite(est) and est > 0):
            return ProxyVerdict("reject", None, self.margin,
                                ["S estimado no finito o <= 0"])
        if est >= best_S * (1.0 - self.margin):
            reasons.append(
                f"S estimado {est:.6g} no baja del mejor {best_S:.6g} "
                f"más que el margen {self.margin:.2%}")
            return ProxyVerdict("reject", est, self.margin, reasons,
                                proxy_merit=proxy_merit(meta))
        return ProxyVerdict("pass", est, self.margin, [],
                            proxy_merit=proxy_merit(meta))

    def rank(self, metas: list[CandidateMeta],
             best_S: float) -> list[tuple[CandidateMeta, ProxyVerdict]]:
        """Ordena las variantes: primero las que pasan, por S estimado."""
        scored = [(m, self.evaluate(m, best_S)) for m in metas]
        scored.sort(key=lambda mv: (not mv[1].ok,
                                    mv[1].s_estimate if mv[1].s_estimate is not None else float("inf")))
        return scored


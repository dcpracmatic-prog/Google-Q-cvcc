"""Fórmulas oficiales de costo S. Puras, sin simulación, sin red.

- invsqrt: S = Q * C, C = Toffoli + T/4
- DQI:     S = R(eps+) * Q^2 * T, R(eps) = ln2 / -ln(1/2 + 2*sqrt(eps))
- química: S = lambda_eff * Ttot * Qtot
- puntaje total: media geométrica de (S_ref / S_propio) en las 3 tareas.
  La referencia puntúa 1.0. El mejor envío global es 23.94667.
"""
from __future__ import annotations

import math

from .contracts import BEST_GLOBAL_SCORE, REFERENCE_S


def repetition_overhead(eps: float) -> float:
    """R(eps) del verificador DQI. Requiere 0 <= eps < 1/16."""
    if not 0.0 <= eps < 1 / 16:
        raise ValueError(f"eps debe estar en [0, 1/16), got {eps}")
    if eps == 0.0:
        return 1.0
    return math.log(2.0) / -math.log(0.5 + 2.0 * math.sqrt(eps))


def s_invsqrt(Q: float, toffoli: float, t_count: float) -> float:
    return float(Q) * (float(toffoli) + float(t_count) / 4.0)


def s_dqi(Q: float, T: float, eps_plus: float) -> float:
    return repetition_overhead(eps_plus) * float(Q) ** 2 * float(T)


def s_chem(lambda_eff: float, Ttot: float, Qtot: float) -> float:
    return float(lambda_eff) * float(Ttot) * float(Qtot)


def ratio(task: str, S: float) -> float:
    """S_ref / S_propio. >1 mejora la referencia, <1 está por debajo."""
    return REFERENCE_S[task] / float(S)


def geometric_score(scores_S: dict[str, float]) -> float:
    """Media geométrica de los ratios en las 3 tareas."""
    import math as _m

    rs = [ratio(t, s) for t, s in scores_S.items()]
    return _m.exp(sum(_m.log(r) for r in rs) / len(rs))


def beats_best_global(scores_S: dict[str, float]) -> bool:
    return geometric_score(scores_S) > BEST_GLOBAL_SCORE

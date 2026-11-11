"""Fórmulas oficiales de costo S. Puras, sin simulación, sin red.

- invsqrt: S = Q * C, C = Toffoli + T/4, con T INCLUYENDO la
  síntesis de rotaciones (v0.9.1): el verificador oficial cobra
  por cada rotación Z_POW fina ``rotation_t_count(eps) =
  0.56*log2(1/eps) + 5.3`` T, con eps sacado del margen de
  tolerancia que deja la aproximación. Ignorar ese término
  subestima el costo (la guía VQCC lo advierte). Sin rotaciones,
  la fórmula es la de siempre.
- DQI:     S = R(eps+) * Q^2 * T, R(eps) = ln2 / -ln(1/2 + 2*sqrt(eps))
- química: S = lambda_eff * Ttot * Qtot
- puntaje total: media geométrica de (S_ref / S_propio) en las 3 tareas.
  La referencia puntúa 1.0. El mejor envío global es 23.94667.
"""
from __future__ import annotations

import math

from .contracts import BEST_GLOBAL_SCORE, INVSQRT_MAX_X, REFERENCE_S

# Tolerancia oficial de fase invsqrt: 2^-24 (beta=1).
INVSQRT_TOL = 2.0 ** -24


def rotation_t_count(eps: float) -> float:
    """T por rotación para sintetizarla con error eps (radianes).

    Copia exacta del verificador oficial de invsqrt
    (verify_submission_invsqrt.py): ``0.56 * log2(1/eps) + 5.3``.
    """
    if not eps > 0:
        raise ValueError(f"eps debe ser > 0, got {eps}")
    return 0.56 * math.log2(1.0 / eps) + 5.3


def rotation_margin_turns(rel_error: float) -> float:
    """Cota inferior del margen de tolerancia que queda, en vueltas.

    El verificador reparte TODO el margen sobrante entre las
    rotaciones (eps = pi * margen / n_rot). El margen real es
    min_x (tol(x) - |error(x)|), con tol(x) = 2^-24/sqrt(x) y
    |error(x)| = rel_err(x)/sqrt(x). Como rel_err(x) <= rel_error
    y sqrt(x) <= sqrt(x_max), el margen es >= (2^-24 - rel_error)
    / sqrt(x_max). Usar esta cota inferior es conservador: el costo
    de síntesis estimado nunca es menor que el real (dado el
    rel_error del prefiltro; el error real del circuito puede ser
    mayor por cuantización, y eso lo mide el verificador oficial).
    """
    margin = (INVSQRT_TOL - float(rel_error)) / math.sqrt(INVSQRT_MAX_X)
    if not margin > 0:
        raise ValueError(
            f"sin tolerancia para la síntesis de rotaciones: "
            f"rel_error {rel_error:.3g} >= 2^-24 ({INVSQRT_TOL:.3g})")
    return margin


def repetition_overhead(eps: float) -> float:
    """R(eps) del verificador DQI. Requiere 0 <= eps < 1/16."""
    if not 0.0 <= eps < 1 / 16:
        raise ValueError(f"eps debe estar en [0, 1/16), got {eps}")
    if eps == 0.0:
        return 1.0
    return math.log(2.0) / -math.log(0.5 + 2.0 * math.sqrt(eps))


def s_invsqrt(Q: float, toffoli: float, t_count: float,
              rotations: int = 0, rel_error: float | None = None) -> float:
    """S de invsqrt con la fórmula oficial, incluida la síntesis.

    rotations: número de rotaciones Z_POW finas del circuito.
    rel_error: error relativo máximo de la aproximación (el e1 del
    prefiltro numeric_lab). Obligatorio si rotations > 0: sin el
    margen no se puede estimar el costo de síntesis (fail-closed,
    ValueError). Con rotations = 0, la fórmula es la de siempre.
    """
    t_total = float(t_count)
    n_rot = int(rotations)
    if n_rot < 0:
        raise ValueError(f"rotations debe ser >= 0, got {n_rot}")
    if n_rot > 0:
        if rel_error is None:
            raise ValueError(
                "rotations > 0 sin rel_error: el costo de síntesis "
                "de rotaciones no se puede estimar sin el margen "
                "de tolerancia (fail-closed)")
        margin = rotation_margin_turns(rel_error)
        eps = math.pi * margin / n_rot
        t_total += n_rot * rotation_t_count(eps)
    return float(Q) * (float(toffoli) + t_total / 4.0)


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

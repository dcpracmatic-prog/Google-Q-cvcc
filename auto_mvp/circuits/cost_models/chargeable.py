"""Compuertas cobrables: T-count y conteo de Toffolis (v2.14.0).

El puntaje oficial solo cobra ciertas compuertas; el resto (Clifford)
es gratis. La regla, leída del verificador invsqrt
(verify_submission_invsqrt.py):

- S = Q x C, C = Toffolis + T/4.
- Un Z_POW cobra según su ángulo: Clifford (múltiplo de pi/2) = 0 T;
  ángulo T (múltiplo impar de pi/4) = 1 T; otro ángulo = coste de
  síntesis rotation_t_cost(eps) = 0.56*log2(1/eps)+5.3 T.
- El eps NO es fijo: el verificador lo deriva del margen de error
  que queda (eps = pi*min_margin/2^64/n_rot). En la semilla da
  28.62 T por rotación, no 18.74 (que sería con eps=2^-24). Por eso
  el conteo estático aquí es una ESTIMACIÓN con un eps de
  referencia; el número exacto lo da el verificador (fast_verify) y
  es el que reporta el benchmark.
- Un CCX o un CSWAP cobra 1 Toffoli (conteo estático; la media por
  shot del verificador es menor si hay condicionales).
- DQI: S = R x Q^2 x T, T = Toffolis. El Z_POW está prohibido, así
  que el T-count es 0 y solo cuenta el Toffoli.
- DFTHC: S = lambda_eff x T_total x Q_total, T_total = Toffolis.

Los ángulos se manejan en Decimal exacto: pasar por float pierde
~1e-16 y mueve el S medido (hallazgo de la auditoría de v2.5).
"""
from __future__ import annotations

import math
from decimal import Decimal

# eps de referencia para la estimación estática (el verificador usa
# el suyo, derivado del margen; ver arriba).
EPS_REF = 2.0 ** -24


def rotation_t_cost(eps: float) -> float:
    """T-count de una rotación arbitraria con error de síntesis eps."""
    return 0.56 * math.log2(1.0 / eps) + 5.3


def zpow_t_cost(theta, eps: float = EPS_REF) -> float:
    """T-count de un Z_POW con ángulo theta (en unidades de pi).

    0 si es Clifford, 1 si es ángulo T, rotation_t_cost(eps) si es
    otro ángulo.
    """
    t = Decimal(str(theta)) % 2
    # Clifford: múltiplo de 1/2 (0, 0.5, 1, 1.5).
    if (t * 2) == (t * 2).to_integral_value():
        return 0.0
    # T: múltiplo impar de 1/4 (0.25, 0.75, 1.25, 1.75).
    if (t * 4) == (t * 4).to_integral_value():
        return 1.0
    return rotation_t_cost(eps)


def count_chargeable(lines, eps: float = EPS_REF) -> dict:
    """Cuenta compuertas cobrables en líneas .kmx (estimación estática).

    Devuelve {"toffoli": int, "t": float, "clifford": int,
    "total": int}. Un CCX o CSWAP es 1 Toffoli; un Z_POW cobra
    según su ángulo; el resto es Clifford (gratis). El "t" usa el
    eps de referencia; el exacto lo da el verificador.
    """
    toffoli = 0
    t = 0.0
    clifford = 0
    total = 0
    for raw in lines:
        s = raw.split("#", 1)[0].strip()
        if not s:
            continue
        parts = s.split()
        op, args = parts[0], parts[1:]
        if op in ("REGISTER", "APPEND_TO_REGISTER", "PUSH_CONDITION",
                  "POP_CONDITION"):
            continue
        total += 1
        if op in ("CCX", "CSWAP"):
            toffoli += 1
        elif op == "Z_POW":
            # Condicional ("if bN"): cobra en los shots en que aplica;
            # para el conteo estático se cuenta como si aplicara.
            t += zpow_t_cost(args[1], eps)
        else:
            clifford += 1
    return {"toffoli": toffoli, "t": t, "clifford": clifford,
            "total": total}

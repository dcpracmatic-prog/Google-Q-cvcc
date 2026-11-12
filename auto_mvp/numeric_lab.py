"""AUTO_MVP — laboratorio numérico y puerta fail-closed (Lab package) (desde v0.5.0).

Incorporación fiel del ``Quantum_Compilation_Lab_Package`` de Arturo
(``competition_suite.py``), adaptada a este repo: solo stdlib, sin
numpy. Dos piezas:

1. ``numeric_lab`` — prefiltro en flotante para invsqrt. Ajusta
   polinomios de Chebyshev de 1/sqrt(x) en [1,4] (grados 2-8, 1/2/4/8
   segmentos), un paso de Newton-Raphson, y reporta si el error
   relativo tras NR es <= 2^-24. Es SOLO un prefiltro en flotante:
   la cuantización, la fase coherente y los costos kickmix NO están
   validados. Ningún candidato de aquí es un submission. (La
   advertencia es la del Lab, textual.)
2. ``fail_closed_gate`` — la puerta de envío del Lab: solo un
   portafolio que pasa los tres verificadores oficiales en modo
   completo puede armar el submission.zip. Un solo fallo o el modo
   smoke cierran la puerta: NOT_CREATED. Sin adivinanzas.

Verificación del port: la tabla (grado, segmentos) -> float_pass y
los errores e1 se contrastan contra el ``numeric_lab`` original
(numpy) en los tests: 28 candidatos, 17 factibles en flotante,
mejor prefiltrado grado 7 / 1 segmento (e1 3.444e-08).
"""
from __future__ import annotations

import math
from functools import lru_cache

TASKS = ("invsqrt", "dqi", "dfthcsos")

NUMERIC_WARNING = (
    "Floating-point prefilter only: quantization, coherent phase and "
    "kickmix costs NOT validated. No candidate is a submission."
)

# El verificador oficial de invsqrt: tol(x) = 2^-24 * beta / sqrt(x).
INVSQRT_TOL = 2.0 ** -24


def _cheb_basis(t: float, degree: int) -> list[float]:
    """T_0..T_degree en t (recurrencia de Chebyshev)."""
    vals = [1.0]
    if degree >= 1:
        vals.append(t)
    for _ in range(2, degree + 1):
        vals.append(2.0 * t * vals[-1] - vals[-2])
    return vals


def _solve_linear(A: list[list[float]], b: list[float]) -> list[float]:
    """Eliminación gaussiana con pivoteo parcial (sistema pequeño)."""
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-300:
            raise ValueError("sistema singular en el ajuste de Chebyshev")
        M[col], M[piv] = M[piv], M[col]
        for r in range(col + 1, n):
            f = M[r][col] / M[col][col]
            for c in range(col, n + 1):
                M[r][c] -= f * M[col][c]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (M[i][n] - sum(M[i][j] * x[j] for j in range(i + 1, n))) / M[i][i]
    return x


def chebyshev_fit(lo: float, hi: float, degree: int,
                  n_points: int = 4097) -> list[float]:
    """Ajuste por mínimos cuadrados de 1/sqrt(x) en [lo, hi].

    Mismo problema que ``Chebyshev.fit`` del Lab (4097 puntos, base
    de Chebyshev): coeficientes en la variable mapeada t en [-1, 1].
    """
    xs = [lo + (hi - lo) * i / (n_points - 1) for i in range(n_points)]
    # Ecuaciones normales A^T A c = A^T y.
    ata = [[0.0] * (degree + 1) for _ in range(degree + 1)]
    aty = [0.0] * (degree + 1)
    for x in xs:
        t = (2.0 * x - lo - hi) / (hi - lo)
        basis = _cheb_basis(t, degree)
        y = 1.0 / math.sqrt(x)
        for i in range(degree + 1):
            aty[i] += basis[i] * y
            for j in range(degree + 1):
                ata[i][j] += basis[i] * basis[j]
    return _solve_linear(ata, aty)


def chebyshev_eval(coeffs: list[float], x: float, lo: float, hi: float) -> float:
    """Evalúa el ajuste de Chebyshev (Clenshaw) en x."""
    t = (2.0 * x - lo - hi) / (hi - lo)
    b1 = b2 = 0.0
    for c in reversed(coeffs[1:]):
        b0 = 2.0 * t * b1 - b2 + c
        b2, b1 = b1, b0
    return t * b1 - b2 + coeffs[0]


def chebyshev_to_power(coeffs: list[float]) -> list[float]:
    """Coeficientes de Chebyshev -> base de potencias (misma variable t).

    Igual que ``fit.convert(kind=Polynomial).coef`` del Lab: T_k(t)
    como serie de potencias en t, combinadas por los coeficientes.
    """
    # T_k(t) en base de potencias.
    polys: list[list[float]] = [[1.0]]
    if len(coeffs) > 1:
        polys.append([0.0, 1.0])
    for _ in range(2, len(coeffs)):
        prev, prev2 = polys[-1], polys[-2]
        cur = [0.0] * (len(prev) + 1)
        for i, c in enumerate(prev):
            cur[i + 1] += 2.0 * c
        for i, c in enumerate(prev2):
            cur[i] -= c
        polys.append(cur)
    out = [0.0] * len(coeffs)
    for k, c in enumerate(coeffs):
        for i, pc in enumerate(polys[k]):
            out[i] += c * pc
    return out


def numeric_lab() -> dict:
    """Prefiltro en flotante de invsqrt (grados 2-8, segmentos 1/2/4/8).

    Replica ``competition_suite.numeric_lab``: para cada (grado,
    segmentos) ajusta 1/sqrt(x) por segmentos en [1, 4], un paso de
    Newton-Raphson, y reporta el error relativo máximo antes y
    después de NR y si pasa 2^-24. Devuelve la misma estructura
    (warning, candidates, float_feasible, best_prefilter).
    """
    xs = [1.0 + 3.0 * i / 40000 for i in range(40001)]
    truth = [1.0 / math.sqrt(x) for x in xs]
    rows = []
    for degree in (2, 3, 4, 5, 6, 7, 8):
        for split in (1, 2, 4, 8):
            edges = [1.0 + 3.0 * i / split for i in range(split + 1)]
            y = [0.0] * len(xs)
            coeff = []
            for i, (lo, hi) in enumerate(zip(edges[:-1], edges[1:])):
                fit = chebyshev_fit(lo, hi, degree)
                coeff.append(chebyshev_to_power(fit))
                for idx, x in enumerate(xs):
                    if lo <= x <= hi if i == split - 1 else lo <= x < hi:
                        y[idx] = chebyshev_eval(fit, x, lo, hi)
            yr = [0.5 * v * (3.0 - x * v * v) for v, x in zip(y, xs)]
            e0 = max(abs(v / t - 1.0) for v, t in zip(y, truth))
            e1 = max(abs(v / t - 1.0) for v, t in zip(yr, truth))
            rows.append({
                "degree": degree,
                "segments": split,
                "initial_float_relative_error": e0,
                "after_NR_float_relative_error": e1,
                "float_pass_2^-24": e1 <= INVSQRT_TOL,
                "coefficients_power_basis_by_segment": coeff,
            })
    rows.sort(key=lambda r: (not r["float_pass_2^-24"],
                             r["degree"] * r["segments"],
                             r["after_NR_float_relative_error"]))
    return {
        "warning": NUMERIC_WARNING,
        "candidates": rows,
        "float_feasible": sum(r["float_pass_2^-24"] for r in rows),
        "best_prefilter": {k: v for k, v in rows[0].items()
                           if k != "coefficients_power_basis_by_segment"},
    }


@lru_cache(maxsize=1)
def float_pass_table() -> dict[tuple[int, int], bool]:
    """(grado, segmentos) -> si pasa 2^-24 en flotante (tabla del Lab)."""
    lab = numeric_lab()
    return {(r["degree"], r["segments"]): r["float_pass_2^-24"]
            for r in lab["candidates"]}


def rel_error_for(degree: int, segments: int) -> float | None:
    """El e1 (error relativo máximo tras NR) de un (grado, segmentos).

    Es el margen que la aproximación deja para la síntesis de
    rotaciones: el proxy lo usa para cobrar ese costo en el S de
    invsqrt (v0.9.1). None si esa combinación no está en la tabla.
    """
    lab = numeric_lab()
    for r in lab["candidates"]:
        if r["degree"] == degree and r["segments"] == segments:
            return float(r["after_NR_float_relative_error"])
    return None


def fail_closed_gate(task_statuses: dict[str, str],
                     mode: str = "full") -> dict[str, str]:
    """Puerta de envío fail-closed del Lab.

    Solo un portafolio que pasa los tres verificadores oficiales en
    modo completo puede armar el submission.zip. El modo smoke no
    implica puntaje de competencia. Un solo fallo cierra la puerta.
    """
    missing = [t for t in TASKS if task_statuses.get(t) != "PASS"]
    if mode != "full":
        return {"status": "NOT_CREATED",
                "reason": ("Requires all three official task verifiers "
                           "PASS in --mode full; fail closed.")}
    if missing:
        return {"status": "NOT_CREATED",
                "reason": ("Requires all three official task verifiers "
                           f"PASS in --mode full; fail closed "
                           f"(no pasan: {', '.join(missing)}).")}
    return {"status": "FULL_LOCAL_VERIFIERS_PASS",
            "reason": "Los tres verificadores oficiales pasaron en modo full."}

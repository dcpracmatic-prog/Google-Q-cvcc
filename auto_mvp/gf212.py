"""Aritmética GF(2^12) mod 0x1053, elemento primitivo alpha = 2.

Es el campo del DQI (el mismo que kickmix y que
``sandbox-run/dqi-ajustes/bm-forney/bm_sim.py``: verificado contra ese
archivo en los tests). Solo stdlib.

Para qué sirve aquí: el sigma del circuito BM es k × sigma mónico
(mismas raíces, misma decodificación; paso 51 v3: k=2314 en el shot 0,
k=1967 en el shot 4). Comparar hashes directos falla aunque el
circuito sea correcto; hay que normalizar a la forma mónica antes de
comparar. Este módulo es esa normalización, con el campo exacto.
"""
from __future__ import annotations

MOD = 0x1053
DEG = 12
ORDER = (1 << DEG) - 1  # 4095


def gf_mul(a: int, b: int) -> int:
    """Multiplicación en GF(2^12) mod 0x1053 (base polinómica)."""
    p = 0
    while b:
        if b & 1:
            p ^= a
        a <<= 1
        if a & 0x1000:
            a ^= MOD
        b >>= 1
    return p


def _gf_pow(a: int, e: int) -> int:
    r = 1
    while e:
        if e & 1:
            r = gf_mul(r, a)
        a = gf_mul(a, a)
        e >>= 1
    return r


def gf_inv(a: int) -> int:
    """Inverso multiplicativo (a^(4094)). Lanza si a == 0."""
    if a == 0:
        raise ValueError("0 no tiene inverso en GF(2^12)")
    return _gf_pow(a, ORDER - 1)


# Tablas log/antilog para multiplicar rápido (alpha = 2 primitivo).
ANTILOG = [1]
for _ in range(ORDER - 1):
    ANTILOG.append(gf_mul(ANTILOG[-1], 2))
LOG = [0] * (1 << DEG)
for _i, _v in enumerate(ANTILOG):
    LOG[_v] = _i


def gf_mul_t(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return ANTILOG[(LOG[a] + LOG[b]) % ORDER]


def monic(sigma: list[int]) -> list[int]:
    """Forma mónica del sigma: divide todo por sigma[0] en el campo.

    El resultado tiene primer coeficiente 1. Dos sigmas con las
    mismas raíces tienen la misma forma mónica, sea cual sea su
    escala k. Lanza ValueError si sigma[0] == 0 (sigma degenerado:
    no es un sigma BM válido en esta representación).
    """
    if not sigma:
        raise ValueError("sigma vacío")
    if sigma[0] == 0:
        raise ValueError("sigma[0] == 0: no se puede normalizar a mónico")
    inv = gf_inv(sigma[0])
    return [gf_mul(c, inv) for c in sigma]


def scale_factor(sigma: list[int], ref: list[int]) -> int | None:
    """k tal que sigma == k·ref en GF(2^12), o None si no lo es.

    k se calcula con el primer coeficiente y se verifica en todos.
    """
    if len(sigma) != len(ref) or not sigma or ref[0] == 0 or sigma[0] == 0:
        return None
    k = gf_mul(sigma[0], gf_inv(ref[0]))
    for s, r in zip(sigma, ref):
        if gf_mul(r, k) != s:
            return None
    return k

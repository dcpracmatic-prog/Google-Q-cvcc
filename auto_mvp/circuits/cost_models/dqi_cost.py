"""AUTO_MVP v2.3 — el modelo de costos DQI (vendido fiel del sandbox).

Es el motor de búsqueda de diseño DQI de Arturo
(``~/workspace/sandbox-run/dqi-ajustes/eea-bezout/dqi_search_engine.py``),
vendido tal cual en sus números: la fórmula CORREGIDA reproduce
EXACTOS los cuatro decodificadores construidos y medidos (63/51/45/42):

    sweep      = 32,408 * (mult + 12)          [mult controlada]
    divisiones = 888 * (inv + mult + 12)       [inv = 5*mult, Itoh-Tsujii]
    chien      = 4,095 * (inv + 36) + 7,392    [inv por posición + pre_align]
    CSWAPs EEA = 1,107,264 ; resto EEA = 334,716 ; shifts = 61,824
    Q          = 1,893 + 12 si mult != 63

La corrección (medida, no supuesta): el modelo original solo aplicaba
el multiplicador al sweep y a las divisiones; el decodificador medido
también lo aplica a las inversiones de Chien (351 -> 291 por posición
con 51T, -> 261 con Toom-3, -> 246 con Toom-4) y suma +12 qubits de
scaffold (Q 1,893 -> 1,905).

Los micro-costes de multiplicador son MEDIDOS en kickmix 1.0.0
(63T librería, 51T, Toom-3 45T, Toom-4 42T). R = 1.1912605 es el
MEDIDO (0 fallos en 102,400 shots), no 1.19.

ESTADO DE CADA NÚMERO: lo que sale de aquí es MODELADO (derivado de
números medidos con fórmula explícita). El circuito construido lo
confirmará o corregirá. El S que cuenta es siempre el MEDIDO con el
verificador oficial; esto solo ORDENA candidatos en milisegundos
para que el paso caro (construir + verificar) solo se gaste en los
que pueden ganar.
"""
from __future__ import annotations

R_MEASURED = 1.1912605  # medido, 0 fallos en 102,400 shots
S_BASELINE_REF = 2.44395e13  # baseline medido (T dinámico)
S_ENSEMBLE_REF = 1.99836e13  # ensamble Toom-3+V1+E2 medido

# Conteos / bloques del baseline medido.
SWEEP_N = 32_408
DIV_N = 888
CHIEN_POS = 4_095
PRE_ALIGN = 7_392
EEA_CSWAP = 1_107_264
EEA_RESIDUAL = 334_716
SHIFTS = 61_824
Q_BASE = 1_893
Q_SCAFFOLD = 12  # +12 qubits de scaffold con mult != 63

# Deltas V1 (punteros 8->7 bits) y E2 (n_a/n_b a 6 bits), MEDIDOS.
# V1: kernel dcpracmatic/dqi-v1-verify-102400 id 144267968.
# E2: candidato Toom-3+V1+E2 (kernel 144307906). Se asume que el delta
# es independiente del multiplicador: es una hipótesis MODELADA cuando
# se aplica a otro multiplicador, no un medido.
V1_DQ, V1_DT = -5, -16_632
E2_DQ, E2_DT = -1, -9_004

# Micro-costes de multiplicador MEDIDOS en kickmix 1.0.0.
MULTS = {
    63: {"name": "libreria 63T", "plain": 63,
         "source": "kickmix 1.0.0 ixor_gf2_mul (medido)"},
    51: {"name": "51T", "plain": 51,
         "source": "mult-inv/mult51.py, verificado 76/76 Simulator"},
    45: {"name": "Toom-3 45T", "plain": 45,
         "source": "mult-inv/toom3.py, verificado 76/76 + GF(2^4) 256/256"},
    42: {"name": "Toom-4 42T", "plain": 42,
         "source": "mult-inv/toom4.py, verificado 76/76 + GF(2^3) 64/64"},
}

# Los cuatro decodificadores MEDIDOS (T estático, Q) que la fórmula
# reproduce exactos. Sirven de prueba: si el modelo no los reproduce,
# el modelo está roto, no la medición.
MEASURED_DECODERS = {
    63: {"T": 5_725_461, "Q": 1_893},
    51: {"T": 5_026_929, "Q": 1_905},
    45: {"T": 4_677_663, "Q": 1_905},
    42: {"T": 4_503_030, "Q": 1_905},
}


def inv_cost(mult: int) -> int:
    """Coste de una inversión Itoh-Tsujii: 5 multiplicaciones."""
    return 5 * mult


def explicit_corrected(mult: int) -> dict:
    """Decodificador explícito con multiplicador `mult` (fórmula corregida).

    Reproduce EXACTOS los cuatro decodificadores construidos:
    63T -> 5,725,461 / Q 1,893 ; 51T -> 5,026,929 / Q 1,905 ;
    45T -> 4,677,663 / Q 1,905 ; 42T -> 4,503,030 / Q 1,905.
    """
    if mult not in MULTS:
        raise ValueError(
            f"multiplicador {mult} sin micro-coste medido "
            f"(medidos: {sorted(MULTS)})")
    inv = inv_cost(mult)
    sweep = SWEEP_N * (mult + 12)
    divs = DIV_N * (inv + mult + 12)
    chien = CHIEN_POS * (inv + 36) + PRE_ALIGN
    total = sweep + divs + chien + EEA_CSWAP + EEA_RESIDUAL + SHIFTS
    q = Q_BASE + (Q_SCAFFOLD if mult != 63 else 0)
    return {"T": total, "Q": q, "sweep": sweep, "divisions": divs,
            "chien_forney": chien, "eea_cswap": EEA_CSWAP,
            "eea_residual": EEA_RESIDUAL, "shifts": SHIFTS}


def score(T: int, Q: int, R: float = R_MEASURED) -> float:
    """S = R * Q^2 * T (la fórmula oficial de DQI)."""
    return R * Q * Q * T


def estimate_variant(mult: int = 63, v1: bool = False,
                     e2: bool = False) -> dict:
    """S MODELADO de una variante (mult, V1, E2) en milisegundos.

    Aplica los deltas medidos V1/E2 sobre el decodificador explícito.
    El delta es MODELADO cuando se aplica a otro multiplicador que
    aquel en el que se midió: el circuito construido lo confirmará.
    Devuelve {mult, v1, e2, Q, T, S, detail}.
    """
    e = explicit_corrected(mult)
    q, t = e["Q"], e["T"]
    if v1:
        q += V1_DQ
        t += V1_DT
    if e2:
        q += E2_DQ
        t += E2_DT
    return {"mult": mult, "v1": v1, "e2": e2, "Q": q, "T": t,
            "S": score(t, q), "detail": e}


def sweep() -> list[dict]:
    """Las 16 variantes (mult × V1 × E2), ordenadas por S modelado."""
    out = []
    for mult in sorted(MULTS):
        for v1 in (False, True):
            for e2 in (False, True):
                out.append(estimate_variant(mult, v1, e2))
    return sorted(out, key=lambda v: v["S"])

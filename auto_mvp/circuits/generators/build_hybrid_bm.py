"""Generador híbrido de circuitos DQI: Berlekamp-Massey + Forney con
descomposición híbrida de medición y descomputación clásica.

Qué implementa (la descomposición híbrida, medida en el DQI público
Q=892, ``sandbox-run/public-dqi/INFORME_DQI_PUBLICO.md``):

1. **Sin reg_b ni estado persistente del decodificador en qubits.**
   Se trabaja in situ sobre el síndrome S (70 × 12 = 840 qubits) y los
   intermedios van a **bits clásicos** (gratis: no cuentan para Q ni T).
   El público no materializa sigma/omega/Bézout en qubits; este generador
   tampoco materializa el par (resto, Bézout) de la EEA: usa BM + Forney.

2. **Contrato solo de fase.** El verificador DQI exige: restaurar S,
   resto de qubits a |0>, y multiplicar la fase global por
   (-1) ** sum_j popcount(e_j & M_j). El circuito nunca construye el
   vector de error en qubits: calcula máscaras clásicamente y aplica la
   fase con ``gf2_phase_by_product`` / Z_IF / CZ_IF condicionadas a bits.

3. **Descomputación por medición (MBUC / HMR).** Los ANDs intermedios no
   se descomputan cuánticamente (eso costaría Toffolis): se calculan con
   CCX en un qubit de trabajo, se **miden con HMR** (Hadamard + medida
   en base X + reset) a un bit clásico, se aplica la corrección de fase
   condicionada a ese bit (CZ_IF), y el qubit se **resetea y reutiliza**.
   Un pool pequeño de qubits de trabajo se recicla miles de veces
   (el público: 11 qubits × 4,025 iteraciones en `scan`).

4. **Inversiones compartidas, no una por posición.** El Forney de
   referencia invierte una vez por posición (4,095 inversiones).
   Aquí se usa **inversión por lotes de Montgomery**: 1 inversión +
   3(k-1) multiplicaciones por lote de k posiciones (verificado V1-V4
   en ``sandbox-run/dqi-ajustes/bm-forney/montgomery-v4/``), con el
   **arreglo de cero obligatorio** (un a_j = 0 envenena su lote).

5. **BM en vez de EEA.** El decodificador es Berlekamp-Massey + Forney
   (Gu et al., arXiv:2610.22367), no la EEA de Proos-Zalka. BM no divide
   polinomios: cada ronda es un producto punto (discrepancia) + una
   actualización lineal. Forma d (mónica, C_0 = 1) con b^{-1} cacheado:
   una inversión solo cuando L sube (~31 por shot), no por ronda.

Alcance honesto (2026-11-14, medido):
- La matemática exacta del pipeline público (extract/synthesis/convert/
  scan) NO está establecida; este generador NO lo reproduce. Implementa
  la descomposición híbrida (los 5 mecanismos de arriba) sobre el
  decodificador BM + Forney, cuya correctitud SÍ está verificada a
  escala chica contra la referencia clásica (``--verify``: PASS;
  sigma 24/24, scan limpio 12/12, circuito completo S restaurado
  10/10 y ancillas a |0> 6/6+6/6).
- El circuito usa por defecto las operaciones GF nativas de kickmix
  (``ixor_gf2_mul``, 63 T/mult). El multiplicador Toom-3 vendoreado
  (``toom3.emit_ixor_toom3``, 45 T/mult) está DESACTIVADO: rompe la
  restauración de B/Lreg en ``bm_backward``, así que ``_ixor_mul``
  ignora el flag y ``toom3=True`` da el mismo circuito que el nativo.
  El knob `toom3` lo mueve el LLM estratega
  (``auto_mvp/llm_auto_dqi.py``) durante la ejecución, pero hoy no
  cambia el circuito.
- CORRECCIÓN v2.17.9 (2026-11-18, MEDIDO): el scan usa inversos
  directos por posición (`_single_position`); la inversión por lotes
  Montgomery está desactivada porque CORROMPE la fase DQI en kickmix
  1.0.0 (ver `hybrid_scan` y notes/v2.17.9.md). Medido a escala
  completa (n=70, m=4095, batch=17, sin efecto desde v2.17.9):
  Q=6,407, T=2,283,981 (nativo), S proyectado = 1.12e14
  (R=1.1912605). Es 4.6x peor que el baseline (2.44e13) y 5.6x peor
  que el ensamble (1.998e13), y muy lejos del público híbrido
  (3.77e11). El S Montgomery con Toom-4 (7.99e13) era FICTICIO:
  ese circuito nunca pasó la verificación de fase (0 PASS en 510
  intentos); el S correcto es el de inversos directos. La limpieza
  de temporales (paso 22: mult/ainv/scaffold, hist_mult) ya está
  aplicada y bajó Q de 10,991 a 6,791; los inversos directos bajan
  Q a 6,407 (sin cadena p/q). Lo que falta para competir es la
  reutilización de slots S + reconstrucción de B
  (``PLAN_SLOT_REUSE.md``) para bajar Q hacia ~1,414. Eso es el
  siguiente paso, no un resultado de este generador.
- Verificado a escala chica (n <= 10) contra la referencia clásica.
  La construcción a escala completa (n=70, m=4095) usa los mismos
  bloques; su Q/T se mide con ``--measure`` (solo construcción).

Uso:
    python build_hybrid_bm.py [--n 70] [--degree 12] [--m 4095]
        [--batch 17] [--format kmb|kmx] [--out dqi_hybrid.kmb]
        [--verify] [--shots N] [--seed S]
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import kickmix as km

# El campo del DQI: GF(2^12) mod 0x1053, alfa = 2 (primitivo).
# Se reutiliza la aritmética clásica del repo (auto_mvp/gf212.py).
import os as _os
_REPO = _os.path.dirname(_os.path.dirname(_os.path.dirname(
    _os.path.dirname(_os.path.abspath(__file__)))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)
from auto_mvp.gf212 import (  # noqa: E402
    DEG as GF_DEG,
    MOD as GF_MOD,
    ORDER as GF_ORDER,
    gf_inv,
    gf_mul,
    monic,
)

DEGREE = GF_DEG            # 12 bits por coeficiente
FIELD = km.GF2Field(DEGREE)
ORDER = GF_ORDER           # 4095 = 2^12 - 1
ALPHA = 2                  # elemento primitivo


# ------------------------------------------------------------------
# Referencia clásica (pura Python, para verificar el circuito)
# ------------------------------------------------------------------
def syndrome_from_errors_n(err, n):
    """Síndrome de n coeficientes a partir de {j: e_j}.

    S_r = sum_j e_j * alfa^((r+1)*j), r = 0..n-1.
    """
    S = [0] * n
    for j, e in err.items():
        if e == 0:
            continue
        for r in range(n):
            S[r] ^= gf_mul(e, _pow_alpha((r + 1) * j))
    return S


def _pow_alpha(e):
    """alfa^e en GF(2^12), con e reducido mod 4095."""
    r = 1
    a = ALPHA
    e %= ORDER
    while e:
        if e & 1:
            r = gf_mul(r, a)
        a = gf_mul(a, a)
        e >>= 1
    return r


def berlekamp_massey(S):
    """BM clásico (forma mónica estándar). Devuelve sigma (lista de
    coeficientes, sigma[0] = 1) y L = grado. Es la referencia contra la
    que se verifica el BM cuántico (``bm_sim.berlekamp_massey_correct``).
    """
    n = len(S)
    C = [1] + [0] * n
    B = [1] + [0] * n
    L, m, b = 0, 1, 1
    for r in range(n):
        d = S[r]
        for i in range(1, L + 1):
            d ^= gf_mul(C[i], S[r - i])
        if d == 0:
            m += 1
            continue
        T = C[:]
        coef = gf_mul(d, gf_inv(b))
        for i in range(n - (m - 1)):
            if i + m <= n and B[i] != 0:
                C[i + m] ^= gf_mul(coef, B[i])
        if 2 * L <= r:
            L = r + 1 - L
            B = T
            b = d
            m = 1
        else:
            m += 1
    return C[: L + 1], L


def omega_from_sigma(sigma, S):
    """Omega(z) = sigma(z) * S(z) mod z^n, grado < L.

    omega_k = sum_{i=0..min(k,L)} sigma_i * S_{k-i}, k = 0..L-1.
    """
    L = len(sigma) - 1
    n = len(S)
    omg = []
    for k in range(L):
        acc = 0
        for i in range(min(k, L) + 1):
            if k - i < n:
                acc ^= gf_mul(sigma[i], S[k - i])
        omg.append(acc)
    return omg


def sigma_prime(sigma):
    """Derivada formal de sigma en característica 2: solo los términos
    impares sobreviven (sigma'_k = sigma_{k+1} si k+1 impar, si no 0).
    Devuelve la lista de coeficientes de sigma' (grado L-1).
    """
    out = []
    for k in range(1, len(sigma)):
        out.append(sigma[k] if (k % 2 == 1) else 0)
    return out


def eval_poly(coeffs, x):
    """Evalúa un polinomio (lista de coeficientes) en x (Horner)."""
    acc = 0
    for c in reversed(coeffs):
        acc = gf_mul(acc, x) ^ c
    return acc


def forney_errors(sigma, omega, m):
    """Errores de Forney: para cada posición j (0..m-1), si
    sigma(alfa^-j) == 0, el error es e_j = omega(alfa^-j) /
    sigma'(alfa^-j). Devuelve {j: e_j} (solo posiciones con error).
    """
    sp = sigma_prime(sigma)
    errs = {}
    for j in range(m):
        x = _pow_alpha(-j)
        if eval_poly(sigma, x) == 0:
            den = eval_poly(sp, x)
            if den == 0:
                continue
            errs[j] = gf_mul(eval_poly(omega, x), gf_inv(den))
    return errs


def expected_phase_parity(errs, masks):
    """Paridad de la fase DQI: sum_j popcount(e_j & M_j) mod 2.

    `masks`: dict {j: M_j} (máscaras clásicas, 12 bits). Es lo que el
    verificador comprueba como fase (``phase_errors``).
    """
    parity = 0
    for j, e in errs.items():
        parity ^= bin(e & masks.get(j, 0)).count("1") & 1
    return parity


# ------------------------------------------------------------------
# Primitivas cuánticas (kickmix nativo)
# ------------------------------------------------------------------
def hmr_uncompute_and(bld, a, b, work, bit):
    """Descomputación por medición de un AND (el núcleo híbrido).

    `work` contiene a AND b (calculado con CCX/init_and). En vez de
    descomputarlo cuánticamente (del_and, 1 Toffoli), se mide con HMR
    (Hadamard + medida en base X + reset) a un bit clásico `bit`, y se
    aplica la corrección de fase: CZ(a, b) condicionada a `bit`.

    Por qué es correcto (MBUC): tras CCX(a,b,work)|0>, medir `work` en
    base X da m en {0,1} y deja en (a,b) una fase (-1)^{m*a*b}. El
    CZ(a,b) condicionado a m == 1 cancela esa fase. El qubit `work`
    queda en |0> y se reutiliza (reciclaje). Coste: 0 Toffolis (la
    medida y el CZ condicionado son gratis en Q/T); se ahorra el
    Toffoli del del_and y se libera el qubit.

    Es el patrón medido en el `scan` del público: CCX -> HMR -> CZ_IF
    -> R, 11 qubits × 4,025 iteraciones.
    """
    bld.hmr(work, bit)
    bld.push_condition(bit)
    bld.cz(a, b)
    bld.pop_condition()


def gf_mul_acc(bld, x, y, target):
    """target ^= x * y en GF(2^12).

    `x`, `y`, `target` son registros de 12 qubits. Por defecto usa
    ``ixor_gf2_mul`` (el multiplicador nativo, 63 T). Si el módulo
    está en modo Toom-3 (``set_toom3(True)``, que activa
    ``build_hybrid_bm_circuit(..., toom3=True)``), usa el emisor
    Toom-3 vendoreado (``toom3.emit_ixor_toom3``, 45 T, verificado
    4/4 en el repo incl. target no cero).
    """
    _ixor_mul(bld, x, y, target)


# El multiplicador que usa el generador: nativo (63 T) o Toom-3 (45 T).
# Lo mueve `build_hybrid_bm_circuit(..., toom3=...)` y lo propone el
# LLM estratega como delta. Es un flag de módulo (no un parámetro
# por función) porque `ixor_gf2_mul` se llama directo en bm_forward,
# compute_omega, montgomery_batch, hybrid_scan y bm_backward.
_TOOM3 = False


def set_toom3(on: bool) -> None:
    """Activa/desactiva el multiplicador Toom-3 para todo el módulo."""
    global _TOOM3
    _TOOM3 = bool(on)


def _ixor_mul(bld, x, y, target):
    """target ^= x * y. Usa SIEMPRE el multiplicador nativo (63 T/mult).

    El Toom-3 vendoreado (45 T/mult) ROMPE la restauración de B/Lreg
    en ``bm_backward`` (B queda con 27 qubits en 1 a n=10, Lreg con
    3; con el nativo quedan en 0), así que está desactivado hasta
    que se arregle. El flag ``_TOOM3`` se ignora por ahora.
    """
    bld.ixor_gf2_mul(x, y, target=target, field=FIELD)


def gf_mul_new(bld, x, y):
    """x * y en GF(2^12), en un registro nuevo de 12 qubits."""
    out = bld.alloc_qubits(DEGREE)
    gf_mul_acc(bld, x, y, out)
    return out


def gf_inv_new(bld, x):
    """1/x en GF(2^12), en un registro nuevo. Devuelve (out, scaffold).

    Usa ``init_gf2_inverse_with_scaffold``. El llamador debe liberar
    con ``gf_inv_del`` cuando ya no necesite el inverso.
    """
    out = bld.alloc_qubits(DEGREE)
    _, scaf = bld.init_gf2_inverse_with_scaffold(x, target=out,
                                                field=FIELD)
    return out, scaf


def gf_inv_del(bld, x, out, scaf):
    """Descomputa el inverso creado por ``gf_inv_new`` (0 T)."""
    bld.del_gf2_inverse_with_scaffold(x, target=out, scaffold=scaf,
                                      field=FIELD)
    bld.free(out)
    bld.free(km.array(list(scaf)))


def gf_const_mul(bld, c, target):
    """target *= c (constante clásica) en GF(2^12). 0 Toffolis
    (multiplicación por constante = red de CNOTs)."""
    if c == 0:
        # target = 0: se pone a cero con X en los bits que sean 1.
        # (No se usa en este generador; se deja como guarda.)
        raise ValueError("multiplicación por constante 0 no soportada")
    if c == 1:
        return
    bld.gf2_imul(c, target=target, field=FIELD)


def horner_eval(bld, coeffs, x):
    """Evalúa un polinomio en x (constante clásica) con Horner.

    `coeffs`: lista de registros de 12 qubits (coeficientes vivos).
    `x`: valor clásico en GF(2^12). Devuelve un registro nuevo de 12
    qubits con el valor. Coste: 0 Toffolis (las multiplicaciones por
    la constante x son gf2_imul, y las sumas son XOR/CNOT).
    Es el ``horner_eval`` verificado de montgomery_v4 (V2: 0 T).
    """
    acc = bld.alloc_qubits(DEGREE)
    # acc = 0; por cada coeficiente de mayor a menor grado:
    # acc = acc * x + c_i.
    for c in reversed(coeffs):
        gf_const_mul(bld, x, acc)
        bld.cx(c, acc)
    return acc


def horner_uneval(bld, coeffs, x, acc):
    """Descomputa el registro creado por ``horner_eval`` (0 T).

    Inversa exacta del Horner: se deshacen los pasos en orden inverso
    (primero el último coeficiente) y la multiplicación por x se
    deshace multiplicando por 1/x (x != 0 siempre: x = alfa^-j).
    """
    inv_x = gf_inv(x)
    for c in coeffs:
        bld.cx(c, acc)
        gf_const_mul(bld, inv_x, acc)
    bld.free(acc)


def zero_fix(bld, acc):
    """Arreglo de cero (obligatorio en cada evaluación de a_j).

    Si `acc` == 0, lo cambia a 1 (para que la inversión por lotes no
    se envenene: un a_j = 0 da inversa 0 y contamina todo su lote).
    Devuelve (is_zero, fix) donde `is_zero` es un qubit que vale 1 si
    acc era 0, y `fix` es el registro (acc o su copia corregida).
    Coste: 11 T por el test de cero (árbol AND), medido en V4.
    En una posición con a_j = 0, located = 0 (no es raíz), así que el
    inverso basura (1) es inofensivo.
    """
    is_zero = bld.alloc_qubits(1)[0]
    bld.flip_if_equal(acc, 0, target=is_zero)
    # Si acc == 0, acc ^= 1 (solo el bit 0: 1 = 0b...0001). Si acc != 0,
    # no cambia. El registro `acc` queda como a_j' (a_j si a_j != 0,
    # 1 si a_j == 0).
    bld.cx(is_zero, acc[0])
    return is_zero


def zero_fix_del(bld, acc, is_zero):
    """Descomputa el arreglo de cero (0 T): quita el 1 si se puso."""
    bld.cx(is_zero, acc[0])
    bld.free(km.array([is_zero]))


# ------------------------------------------------------------------
# BM adelante (Berlekamp-Massey, forma reescalada de Gu et al.)
# ------------------------------------------------------------------
def bm_forward(bld, S, n, nslot=36):
    """BM adelante: calcula sigma (C) a partir del síndrome S.

    Adaptación verificada de ``bm_forward_step16.py`` (sigma
    normalizado correcto 144/144 a n=70, 4 shots DQI reales). Usa las
    operaciones GF nativas de kickmix (``ixor_gf2_mul``) en vez del
    Toom-3 del sandbox (45 T); la T medida aquí es una cota superior.

    `S`: lista de n registros de 12 qubits (síndrome, entrada; se
    restaura con ``bm_backward``). `nslot`: nº de slots de C y B
    (36 a escala completa: L <= 35, y deg(sigma)+deg(tau)=r+1 implica
    que los coeficientes más allá de 35 no afectan el cálculo).

    Por ronda r (compile-time, r = 0..n-1):
      a. discrepancia (Gu Ec. 33): d = C[0]*S[r] + sum_{i>=1} C[i]*S[r-i].
         Sin gating por L: los slots C[i] con i > L valen 0, así que
         los términos extra aportan 0. (Antes se copiaba S[r] asumiendo
         sigma_0 = 1; en la forma reescalada sigma_0 != 1, por eso el
         término C[0]*S[r].)
      b. alpha = d * C[0]; ainv = 1/alpha (1 inversión, scaffold).
      c. flag replace = (d != 0) AND (2L <= r).
      d. mult = alpha; swap condicional mult <-> ainv (por flag).
         mult = alpha si no hay replace, = 1/alpha si lo hay.
      e. swap C <-> B (por flag) + update C[i] += mult * B[i].
      f. L <- r+1-L si flag.
      g. desplaza B 1 slot (verdadero: el tope se descarta a trash,
         abajo entra 0). Es el desplazamiento z^m (m crece 1/ronda).

    Devuelve (C, B, Lreg, hist) donde C es sigma (nslot registros),
    B la plantilla, Lreg el contador de grado, e hist la historia por
    ronda (flag, mult) que necesita ``bm_backward``. Los temporales
    por ronda (dreg, alpha, ainv, mult, flags) NO se limpian aquí;
    ``bm_backward`` los libera al revertir.
    """
    N = n
    NSLOT = nslot
    LBITS = 7
    C = [bld.alloc_qubits(DEGREE) for _ in range(NSLOT)]
    B = [bld.alloc_qubits(DEGREE) for _ in range(NSLOT)]
    Lreg = bld.alloc_qubits(LBITS)
    # Inicialización: C[0] = 1, B[1] = 1, L = 0. (El resto a |0>.)
    bld.x(km.array([C[0][0]]))
    if NSLOT > 1:
        bld.x(km.array([B[1][0]]))
    hist = []
    for r in range(N):
        dreg = bld.alloc_qubits(DEGREE)
        alpha_reg = bld.alloc_qubits(DEGREE)
        ainv_reg = bld.alloc_qubits(DEGREE)
        mult_reg = bld.alloc_qubits(DEGREE)
        is_d_nonzero = bld.alloc_qubits(1)[0]
        is_le = bld.alloc_qubits(1)[0]
        flag = bld.alloc_qubits(1)
        # a. discrepancia
        _ixor_mul(bld, C[0], S[r], dreg)
        for i in range(1, NSLOT):
            if r - i >= 0:
                _ixor_mul(bld, C[i], S[r - i], dreg)
        # b. alpha y alpha_inv
        _ixor_mul(bld, dreg, C[0], alpha_reg)
        _, scaffold = bld.init_gf2_inverse_with_scaffold(
            alpha_reg, target=ainv_reg, field=FIELD)
        # c. flag replace = (d != 0) AND (2L <= r)
        bld.flip_if_equal(dreg, 0, target=is_d_nonzero)
        bld.x(km.array([is_d_nonzero]))
        bld.flip_if_less_than(Lreg, r // 2 + 1, target=is_le)
        bld.init_and(is_d_nonzero, is_le, flag)
        # d. mult = alpha; swap condicional mult <-> ainv
        for k in range(DEGREE):
            bld.cx(alpha_reg[k], mult_reg[k])
        for k in range(DEGREE):
            bld.cswap(flag[0], mult_reg[k], ainv_reg[k])
        # e. swap C <-> B + update
        for i in range(NSLOT):
            for k in range(DEGREE):
                bld.cswap(flag[0], C[i][k], B[i][k])
        for i in range(NSLOT):
            _ixor_mul(bld, mult_reg, B[i], C[i])
        # e2. LIMPIEZA (paso 22): guardar mult en historia persistente
        #    y liberar el mult de trabajo, el inverso y su scaffold.
        #    El atrás usa hist_mult (no el mult de trabajo). Ahorra
        #    ~72q/ronda (mult 12 + ainv 12 + scaffold ~48). Quedan sin
        #    limpiar dreg/alpha/flags/tmpL/trash (~47q/ronda) porque
        #    dependen de C_old (que cambia en el update).
        #    Orden exacto (paso 22): (1) copiar mult a hist_mult;
        #    (2) deshacer el CSWAP mult<->ainv (mismo flag); (3)
        #    deshacer el CX alpha->mult (mult vuelve a |0>); (4) del
        #    del inverso (ainv a |0>); (5) free. Sin (2)-(3), mult se
        #    libera con valor != 0 y corrompe el pool de qubits.
        hist_mult = bld.alloc_qubits(DEGREE)
        for k in range(DEGREE):
            bld.cx(mult_reg[k], hist_mult[k])
        for k in range(DEGREE):
            bld.cswap(flag[0], mult_reg[k], ainv_reg[k])
        for k in range(DEGREE):
            bld.cx(alpha_reg[k], mult_reg[k])
        bld.del_gf2_inverse_with_scaffold(alpha_reg, target=ainv_reg,
                                          scaffold=scaffold, field=FIELD)
        bld.free(km.array(list(mult_reg) + list(ainv_reg)
                          + list(scaffold)))
        # f. L <- r+1-L si flag
        tmpL = bld.alloc_qubits(LBITS)
        for k in range(LBITS):
            if (r + 1) >> k & 1:
                bld.x(km.array([tmpL[k]]))
        bld.isub(Lreg, target=tmpL)
        for k in range(LBITS):
            bld.cswap(flag[0], Lreg[k], tmpL[k])
        # g. desplaza B 1 slot verdadero (tope a trash, abajo 0)
        ctrl1 = bld.alloc_qubits(1)[0]
        bld.x(km.array([ctrl1]))
        trash = bld.alloc_qubits(DEGREE)
        for k in range(DEGREE):
            bld.cswap(ctrl1, B[NSLOT - 1][k], trash[k])
        for i in range(NSLOT - 1, 0, -1):
            for k in range(DEGREE):
                bld.cswap(ctrl1, B[i][k], B[i - 1][k])
        hist.append({
            "r": r, "dreg": dreg, "alpha": alpha_reg,
            "hist_mult": hist_mult, "flag": flag,
            "tmpL": tmpL, "trash": trash, "ctrl1": ctrl1,
            "is_d_nonzero": is_d_nonzero, "is_le": is_le,
        })
    return C, B, Lreg, hist


def compute_omega(bld, C, S, n, nslot=36):
    """Omega(z) = sigma(z) * S(z) mod z^n, grado < L.

    omega_k = sum_{i=0..min(k,L)} sigma_i * S_{k-i}, k = 0..nslot-1.
    Es el mecanismo verificado del paso 17 (T = 630 mults a n=70).
    Devuelve OMG, lista de (nslot) registros de 12 qubits.
    """
    OMG = [bld.alloc_qubits(DEGREE) for _ in range(nslot)]
    for k in range(nslot):
        for i in range(min(k, nslot - 1) + 1):
            if k - i < n:
                _ixor_mul(bld, C[i], S[k - i], OMG[k])
    return OMG


def uncompute_omega(bld, C, S, OMG, n, nslot=36):
    """Descomputa ``compute_omega`` (0 T extra en conteo neto: XOR es
    su propia inversa). Reaplica los mismos productos para devolver
    OMG a |0> y lo libera. Sin esto, OMG queda con los valores de
    omega y es basura para el verificador (otros qubits deben ser 0).
    """
    for k in range(nslot):
        for i in range(min(k, nslot - 1) + 1):
            if k - i < n:
                _ixor_mul(bld, C[i], S[k - i], OMG[k])
    for reg in OMG:
        bld.free(km.array(list(reg)))


# ------------------------------------------------------------------
# Hybrid scan: evaluación Chien + Forney por lotes de Montgomery
# ------------------------------------------------------------------
def eval_sigma_prime(bld, C, L, x, zero_reg):
    """Evalúa sigma'(x) con Horner y aplica el arreglo de cero.

    sigma'(z) = sum_{k impar} C[k] * z^{k-1}. Los coeficientes pares
    son 0 (derivada formal en característica 2) y se representan con
    `zero_reg` (un registro |0> compartido).
    Devuelve (a_reg, is_zero): a_reg es sigma'(x) corregido (a_j' =
    a_j si a_j != 0, 1 si a_j == 0) e is_zero el flag del arreglo.
    """
    coeffs = []
    for j in range(L):
        coeffs.append(C[j + 1] if ((j + 1) % 2 == 1) else zero_reg)
    a_reg = horner_eval(bld, coeffs, x)
    is_zero = zero_fix(bld, a_reg)
    return a_reg, is_zero


def uneval_sigma_prime(bld, C, L, x, a_reg, is_zero, zero_reg):
    """Descomputa ``eval_sigma_prime`` (0 T)."""
    zero_fix_del(bld, a_reg, is_zero)
    coeffs = []
    for j in range(L):
        coeffs.append(C[j + 1] if ((j + 1) % 2 == 1) else zero_reg)
    horner_uneval(bld, coeffs, x, a_reg)


def eval_sigma_omega(bld, C, OMG, L, x, kj):
    """Evalúa sigma(x) y omega(x) con Horner.

    Devuelve (s_acc, o_acc). `kj` se IGNORA (se recibe por
    compatibilidad con la llamada): la constante K_j =
    alfa^{j*(m-2)} de montgomery_v4 ESCALA el error de Forney
    (e_j -> K_j * e_j) y cambia la fase (-1)^popcount(e_j & M_j),
    así que la fase salía mal (1 error en j=1 con M=1 daba False
    en vez de True; alpha^13 tiene LSB 0). El Forney clásico
    (forney_errors, sin K_j) da el error verdadero, así que aquí
    NO se aplica K_j. Sin K_j la fase coincide con la esperada.
    """
    s_acc = horner_eval(bld, list(C[: L + 1]), x)
    o_acc = horner_eval(bld, list(OMG[:L]), x)
    return s_acc, o_acc


def uneval_sigma_omega(bld, C, OMG, L, x, kj, s_acc, o_acc):
    """Descomputa ``eval_sigma_omega`` (0 T). `kj` se ignora igual
    que en ``eval_sigma_omega`` (ya no se aplica K_j)."""
    horner_uneval(bld, list(OMG[:L]), x, o_acc)
    horner_uneval(bld, list(C[: L + 1]), x, s_acc)


def phase_kick(bld, s_acc, o_acc, inv_reg, mask_reg):
    """Patea la fase de Forney de una posición. Devuelve (is_root, located).

    is_root = (sigma(x) == 0). located = is_root ? omega(x) : 0.
    La fase (-1)^popcount(e_j & M_j) se aplica con
    ``gf2_phase_by_product(located, inv, mask)`` donde inv = 1/sigma'(x)
    y mask = M_j (clásico). Es el ``phase_kick`` modo flip36 de
    montgomery_v4 (12 T por el test de cero + 12 T por el AND).
    """
    is_root = bld.alloc_qubits(1)[0]
    bld.flip_if_equal(s_acc, 0, target=is_root)
    located = bld.alloc_qubits(DEGREE)
    bld.init_and(is_root, o_acc, located)
    bld.gf2_phase_by_product(located, inv_reg, mask=mask_reg, field=FIELD)
    bld.del_and(is_root, o_acc, located)
    bld.flip_if_equal(s_acc, 0, target=is_root)
    return is_root, located


def montgomery_batch(bld, C, OMG, E, b, L, j0, m, zero_reg):
    """Un lote Montgomery del hybrid scan (b posiciones j0..j0+b-1).

    ADVERTENCIA v2.17.9 (2026-11-18, MEDIDO): esta función CORROMPE
    la fase DQI en kickmix 1.0.0 y NO se usa. Cualquier lote >= 2 da
    2-5 errores de fase de 8 shots en verify_small (n=10, m=15),
    con sigma y registros intactos y con los inversos derivados
    correctos en valor (Exp C3: 0/32 mismatches). La bisección
    (Exp A-I, notes/v2.17.9.md) exoneró la limpieza final, los
    valores derivados, del_gf2_mul, el multiplicador nativo y
    Toom-3, y mostró que solo pasan las patadas con inversos
    directos y sin maquinaria Montgomery viva: la copia CNOT de un
    inverso (Exp H) y las multiplicaciones de la cadena q (Exp I)
    rompen la fase por sí solas. Se conserva solo como referencia;
    `hybrid_scan` usa siempre `_single_position`.

    `C`: sigma (lista de registros, C[0..L]). `OMG`: omega (lista de
    registros). `E`: lista de b registros clásicos (máscaras M_j).
    `m`: longitud del código (4095). `zero_reg`: registro |0> compartido.

    Estructura (variante A de montgomery_v4, verificada V1-V4):
      adelante: p_i = p_{i-1} * a_i' (a_i' = sigma'(x_i) con arreglo
        de cero). p_1 = a_1' virtual.
      1 inversión de p_b (Itoh-Tsujii, scaffold).
      atrás i=b..2: inv_i = q_i * p_{i-1}; patada de fase posición i;
        descomputar inv_i; q_{i-1} = q_i * a_i'. En i=2, q_1 = inv_1
        con su propia patada de fase.
      limpieza final en orden inverso exacto (0 T).

    T por lote (con arreglo de cero, modo flip36):
      T = 3(b-1)*45 + 225 + b*24 + 11*(4b-3)  [con Toom-3 a 45 T]
    Con las ops GF nativas la T es mayor (se mide); la estructura
    (1 inversión por lote, no una por posición) es la ganancia híbrida.
    """
    xs = [_pow_alpha(-(j0 + i)) for i in range(b)]
    kjs = [_pow_alpha((m - 2) * (j0 + i)) for i in range(b)]
    # ---- adelante: prefijos p_2..p_b ----
    p = [None] * (b + 1)
    for i in range(2, b + 1):
        if i == 2:
            a1, f1 = eval_sigma_prime(bld, C, L, xs[0], zero_reg)
            a2, f2 = eval_sigma_prime(bld, C, L, xs[1], zero_reg)
            p[2] = bld.alloc_qubits(DEGREE)
            _ixor_mul(bld, a1, a2, p[2])
            uneval_sigma_prime(bld, C, L, xs[0], a1, f1, zero_reg)
            uneval_sigma_prime(bld, C, L, xs[1], a2, f2, zero_reg)
        else:
            ai, fi = eval_sigma_prime(bld, C, L, xs[i - 1], zero_reg)
            p[i] = bld.alloc_qubits(DEGREE)
            _ixor_mul(bld, p[i - 1], ai, p[i])
            uneval_sigma_prime(bld, C, L, xs[i - 1], ai, fi, zero_reg)
    # ---- una inversión ----
    q = [None] * (b + 1)
    q[b] = bld.alloc_qubits(DEGREE)
    _, scaf = bld.init_gf2_inverse_with_scaffold(p[b], target=q[b],
                                                 field=FIELD)
    # ---- atrás i=b..2 ----
    for i in range(b, 1, -1):
        r_inv = bld.alloc_qubits(DEGREE)
        if i == 2:
            a1, f1 = eval_sigma_prime(bld, C, L, xs[0], zero_reg)
            _ixor_mul(bld, q[2], a1, r_inv)
        else:
            _ixor_mul(bld, q[i], p[i - 1], r_inv)
        s_acc, o_acc = eval_sigma_omega(bld, C, OMG, L, xs[i - 1],
                                        kjs[i - 1])
        is_root, located = phase_kick(bld, s_acc, o_acc, r_inv, E[i - 1])
        uneval_sigma_omega(bld, C, OMG, L, xs[i - 1], kjs[i - 1],
                           s_acc, o_acc)
        bld.free(located)
        bld.free(km.array([is_root]))
        if i == 2:
            bld.del_gf2_mul(q[2], a1, target=r_inv, field=FIELD)
            bld.free(r_inv)
            uneval_sigma_prime(bld, C, L, xs[0], a1, f1, zero_reg)
        else:
            bld.del_gf2_mul(q[i], p[i - 1], target=r_inv, field=FIELD)
            bld.free(r_inv)
        ai, fi = eval_sigma_prime(bld, C, L, xs[i - 1], zero_reg)
        q[i - 1] = bld.alloc_qubits(DEGREE)
        _ixor_mul(bld, q[i], ai, q[i - 1])
        uneval_sigma_prime(bld, C, L, xs[i - 1], ai, fi, zero_reg)
        if i == 2:
            s_acc, o_acc = eval_sigma_omega(bld, C, OMG, L, xs[0], kjs[0])
            is_root, located = phase_kick(bld, s_acc, o_acc, q[1], E[0])
            uneval_sigma_omega(bld, C, OMG, L, xs[0], kjs[0], s_acc, o_acc)
            bld.free(located)
            bld.free(km.array([is_root]))
            a2, f2 = eval_sigma_prime(bld, C, L, xs[1], zero_reg)
            bld.del_gf2_mul(q[2], a2, target=q[1], field=FIELD)
            bld.free(q[1])
            uneval_sigma_prime(bld, C, L, xs[1], a2, f2, zero_reg)
    # ---- limpieza final (orden inverso exacto, 0 T) ----
    for k in range(2, b):
        ak1, fk1 = eval_sigma_prime(bld, C, L, xs[k], zero_reg)
        bld.del_gf2_mul(q[k + 1], ak1, target=q[k], field=FIELD)
        uneval_sigma_prime(bld, C, L, xs[k], ak1, fk1, zero_reg)
        bld.free(q[k])
    bld.del_gf2_inverse_with_scaffold(p[b], target=q[b], scaffold=scaf,
                                      field=FIELD)
    bld.free(q[b])
    bld.free(km.array(list(scaf)))
    for k in range(b, 1, -1):
        if k == 2:
            a1, f1 = eval_sigma_prime(bld, C, L, xs[0], zero_reg)
            a2, f2 = eval_sigma_prime(bld, C, L, xs[1], zero_reg)
            bld.del_gf2_mul(a1, a2, target=p[2], field=FIELD)
            uneval_sigma_prime(bld, C, L, xs[0], a1, f1, zero_reg)
            uneval_sigma_prime(bld, C, L, xs[1], a2, f2, zero_reg)
        else:
            ak, fk = eval_sigma_prime(bld, C, L, xs[k - 1], zero_reg)
            bld.del_gf2_mul(p[k - 1], ak, target=p[k], field=FIELD)
            uneval_sigma_prime(bld, C, L, xs[k - 1], ak, fk, zero_reg)
        bld.free(p[k])
    return {"batch": b, "j0": j0}


def hybrid_scan(bld, C, OMG, E, m, batch, L, zero_reg):
    """El hybrid scan completo: recorre las m posiciones.

    CORRECCIÓN v2.17.9 (2026-11-18, MEDIDO): el scan usa SIEMPRE
    inversos directos por posición (`_single_position`), sin
    Montgomery. La inversión por lotes (`montgomery_batch`) corrompe
    la fase DQI en kickmix 1.0.0: cualquier lote >= 2 da 2-5 errores
    de fase de 8 shots en verify_small, con sigma y registros
    intactos (Exp A-I, notes/v2.17.9.md). Solo la configuración sin
    maquinaria Montgomery — inversos directos, uno por posición —
    pasa 8/8. El parámetro `batch` queda sin efecto para el scan
    (se conserva por compatibilidad de API y para el conteo
    informativo de lotes); el costo es 1 inversión por posición
    en vez de 1 por lote.

    `C`: sigma, `OMG`: omega, `E`: lista de m registros clásicos
    (máscaras M_j, entradas). `batch`: tamaño de lote (sin efecto
    desde v2.17.9). Aplica la fase DQI de todas las posiciones.
    """
    for j in range(m):
        _single_position(bld, C, OMG, E, L, j, m, zero_reg)
    nbatches = (m + batch - 1) // batch if batch and batch > 0 else m
    return {"batches": nbatches, "mode": "directo",
            "note": "Montgomery desactivado por fase (v2.17.9)"}


def _single_position(bld, C, OMG, E, L, j, m, zero_reg):
    """Una posición suelta (cola del scan): inversión directa."""
    x = _pow_alpha(-j)
    kj = _pow_alpha((m - 2) * j)
    a_reg, f = eval_sigma_prime(bld, C, L, x, zero_reg)
    inv, scaf = gf_inv_new(bld, a_reg)
    s_acc, o_acc = eval_sigma_omega(bld, C, OMG, L, x, kj)
    is_root, located = phase_kick(bld, s_acc, o_acc, inv, E[j])
    uneval_sigma_omega(bld, C, OMG, L, x, kj, s_acc, o_acc)
    bld.free(located)
    bld.free(km.array([is_root]))
    gf_inv_del(bld, a_reg, inv, scaf)
    uneval_sigma_prime(bld, C, L, x, a_reg, f, zero_reg)


# ------------------------------------------------------------------
# BM atrás (descomputación del BM adelante)
# ------------------------------------------------------------------
def bm_backward(bld, S, C, B, Lreg, hist, n, nslot=36):
    """BM atrás: revierte ``bm_forward`` ronda por ronda (de n-1 a 0)
    para restaurar S y liberar C/B.

    Cada ronda se deshace en orden inverso (g, f, e, d, c, b, a),
    usando la historia `hist` (los registros por ronda). Todas las
    operaciones son su propia inversa (XOR, CSWAP, o se reaplican):
      g. deshacer el shift de B: shift ARRIBA (B[i] <- B[i+1], el tope
         se restaura desde trash).
      f. deshacer L: L <- r+1-L si flag (la misma operación, que es
         su propia inversa).
      e. deshacer el update: C[i] ^= mult*B[i] otra vez (cancela),
         luego CSWAP C<->B otra vez (restaura).
      d. deshacer mult: CSWAP mult<->ainv otra vez, luego CX
         alpha->mult otra vez (mult vuelve a 0).
      c. deshacer flag: del_and, X, flip_if_less_than, flip_if_equal
         (cada uno su propia inversa, en orden inverso).
      b. deshacer ainv (del_gf2_inverse_with_scaffold) y alpha
         (ixor_gf2_mul otra vez, cancela).
      a. deshacer la discrepancia: ixor_gf2_mul otra vez (cancela).
    Al final C y B vuelven a su estado inicial (C[0]=1, B[1]=1, resto
    0) y S queda intacto. Los temporales de `hist` se liberan.
    """
    NSLOT = nslot
    LBITS = 7
    for r in range(n - 1, -1, -1):
        h = hist[r]
        dreg, alpha_reg = h["dreg"], h["alpha"]
        hist_mult = h["hist_mult"]
        flag, tmpL = h["flag"], h["tmpL"]
        trash, ctrl1 = h["trash"], h["ctrl1"]
        # g. deshacer shift de B (shift arriba)
        for i in range(0, NSLOT - 1):
            for k in range(DEGREE):
                bld.cswap(ctrl1, B[i][k], B[i + 1][k])
        for k in range(DEGREE):
            bld.cswap(ctrl1, B[NSLOT - 1][k], trash[k])
        # ctrl1 se puso a 1 con X en el adelante; se devuelve a 0
        # con X otra vez (es su propia inversa). Si no, queda en 1
        # y es basura para el verificador.
        bld.x(km.array([ctrl1]))
        # f. deshacer L y descomputar tmpL (sin tmpL2).
        #    Antes de este paso: Lreg = (r+1)-L0 (si flag) o L0
        #    (si no), tmpL = L0 (si flag) o (r+1)-L0 (si no).
        #    (1) cswap(flag, Lreg, tmpL): restaura Lreg a L0 y deja
        #    tmpL = (r+1)-L0 en AMBOS casos. (2) iadd(Lreg, tmpL):
        #    tmpL = (r+1). (3) X en los bits de (r+1): tmpL = 0.
        #    Sin esto, tmpL quedaba con basura y tmpL2 también (el
        #    mecanismo viejo con tmpL2 dejaba ambos en 1).
        for k in range(LBITS):
            bld.cswap(flag[0], Lreg[k], tmpL[k])
        bld.iadd(Lreg, target=tmpL)
        for k in range(LBITS):
            if (r + 1) >> k & 1:
                bld.x(km.array([tmpL[k]]))
        # e. deshacer update (con hist_mult, no el mult de trabajo) y
        #    swap C<->B. hist_mult se libera tras usarlo.
        for i in range(NSLOT):
            _ixor_mul(bld, hist_mult, B[i], C[i])
        for i in range(NSLOT):
            for k in range(DEGREE):
                bld.cswap(flag[0], C[i][k], B[i][k])
        bld.free(hist_mult)
        # d. (sin efecto: mult/ainv ya se liberaron en el adelante tras
        #    guardar hist_mult; no hay nada que deshacer aquí.)
        # c. deshacer flag (usa los is_d_nonzero/is_le ORIGINALES de
        #    la ronda, guardados en hist; del_and los necesita vivos).
        is_d_nonzero = h["is_d_nonzero"]
        is_le = h["is_le"]
        bld.del_and(is_d_nonzero, is_le, flag)
        bld.flip_if_less_than(Lreg, r // 2 + 1, target=is_le)
        bld.x(km.array([is_d_nonzero]))
        bld.flip_if_equal(dreg, 0, target=is_d_nonzero)
        # b. deshacer alpha (ainv/scaffold ya se liberaron en el
        #    adelante). alpha ^= d*C[0] otra vez (cancela).
        _ixor_mul(bld, dreg, C[0], alpha_reg)
        # a. deshacer discrepancia
        _ixor_mul(bld, C[0], S[r], dreg)
        for i in range(1, NSLOT):
            if r - i >= 0:
                _ixor_mul(bld, C[i], S[r - i], dreg)
        # liberar temporales de la ronda
        bld.free(dreg)
        bld.free(alpha_reg)
        bld.free(flag)
        bld.free(tmpL)
        bld.free(trash)
        bld.free(km.array([ctrl1]))
        bld.free(km.array([is_d_nonzero]))
        bld.free(km.array([is_le]))
    # C y B vuelven a C[0]=1, B[1]=1: se quitan esas X (vuelven a 0).
    bld.x(km.array([C[0][0]]))
    if NSLOT > 1:
        bld.x(km.array([B[1][0]]))


# ------------------------------------------------------------------
# Ensamblaje: el decodificador híbrido completo
# ------------------------------------------------------------------
def build_hybrid_bm_circuit(n=70, degree=12, m=4095, batch=17,
                            nslot=36, toom3=False):
    """Construye el circuito DQI híbrido completo.

    Entradas: S (n registros de 12 qubits, síndrome) + E (m registros
    clásicos de 12 bits, máscaras M_j). Salida: la fase DQI aplicada
    y S restaurado.

    Knobs que mueve el LLM estratega (deltas DQI):
      batch: tamaño del lote Montgomery (T).
      nslot: slots C/B (Q; debe ser >= Lmax+1).
      toom3: RESERVADO (sin efecto por ahora). El multiplicador
        Toom-3 vendoreado (45 T/mult) ROMPE la restauración de
        B/Lreg en ``bm_backward`` (B queda con 27 qubits en 1 a
        n=10, Lreg con 3; con el nativo quedan en 0), así que el
        generador usa siempre el nativo (63 T/mult) hasta que
        Toom-3 se arregle. El knob se guarda en info pero no
        cambia el circuito. Un circuito válido con T mayor vale
        más que uno inválido con T menor.

    Fases:
      1. BM adelante -> sigma C (y B, L, hist).
      2. Omega = sigma * S mod z^n.
      3. Hybrid scan (lotes Montgomery) -> fase DQI.
      4. Descomputar omega -> OMG a |0>.
      5. BM atrás -> restaura S, libera C/B.
    Devuelve (circ, info) donde info trae Q, T y los registros.
    """
    set_toom3(False)
    try:
        return _build_hybrid_bm_circuit(n, degree, m, batch, nslot)
    finally:
        set_toom3(False)


def _build_hybrid_bm_circuit(n, degree, m, batch, nslot):
    bld = km.CircuitBuilder()
    # CORRECCIÓN registros (verificador oficial): los registros deben
    # llamarse EXACTAMENTE S0..S{n-1} y E0..E{m-1}. alloc_qubits /
    # alloc_bits crean registros anónimos y el verificador rechaza el
    # circuito ("Registers must be exactly S0..S{n-1} and E0..E{m-1}").
    S = [bld.create_quantum_register(DEGREE, name=f'S{i}') for i in range(n)]
    # E son las máscaras M_j: entradas CLÁSICAS (bits, no qubits).
    # No cuentan para Q ni T (son el plano clásico del híbrido).
    E = [bld.create_classical_register(DEGREE, name=f'E{j}') for j in range(m)]
    zero_reg = bld.alloc_qubits(DEGREE)
    C, B, Lreg, hist = bm_forward(bld, S, n, nslot=nslot)
    OMG = compute_omega(bld, C, S, n, nslot=nslot)
    L = nslot - 1
    scan_info = hybrid_scan(bld, C, OMG, E, m, batch, L, zero_reg)
    # Descomputar omega: OMG vuelve a |0> (si no, es basura).
    uncompute_omega(bld, C, S, OMG, n, nslot=nslot)
    bm_backward(bld, S, C, B, Lreg, hist, n, nslot=nslot)
    bld.free(zero_reg)
    circ = bld.finish_circuit()
    st = circ.operation_statistics()
    info = {
        "n": n, "degree": degree, "m": m, "batch": batch,
        "nslot": nslot, "toom3": bool(_TOOM3),
        "qubits": circ.num_qubits,
        "toffoli_like": st.num_toffoli_like,
        "instructions": st.num_instructions,
        "scan": scan_info,
    }
    return circ, info


# ------------------------------------------------------------------
# Verificación a escala chica y CLI
# ------------------------------------------------------------------
def _read_reg(sim, reg):
    """Lee un registro de 12 qubits como entero (1 shot)."""
    bits = sim.read_across_shots(km.array(reg))
    return sum(int(bits[k, 0]) << k for k in range(DEGREE))


def verify_small(n=10, m=15, batch=4, seed=12345, nshots=8, toom3=False):
    """Verifica BM, restauración de registros y fase DQI a escala chica.

    La fase se contrasta por shot usando read_phase_flipped_across_shots
    contra la paridad calculada desde los errores de entrada conocidos.
    Esta prueba es un filtro de regresión, no sustituye al verificador DQI
    completo ni constituye certificación estadística de competición.
    """
    set_toom3(bool(toom3))
    try:
        return _verify_small(n, m, batch, seed, nshots)
    finally:
        set_toom3(False)


def _verify_small(n, m, batch, seed, nshots):
    import numpy as np

    rng = np.random.default_rng(seed)
    res = {"n": n, "m": m, "batch": batch, "seed": seed}
    # --- errores aleatorios de peso <= n//2 y su síndrome ---
    errs_list = []
    S_list = []
    for _ in range(nshots):
        w = int(rng.integers(1, max(2, n // 2)))
        pos = rng.choice(m, size=w, replace=False)
        err = {}
        for j in pos:
            err[int(j)] = int(rng.integers(1, 1 << DEGREE))
        errs_list.append(err)
        S_list.append(syndrome_from_errors_n(err, n))
    # --- 1. BM adelante: sigma ---
    nslot = (n // 2) + 1
    bld = km.CircuitBuilder()
    S = [bld.alloc_qubits(DEGREE) for _ in range(n)]
    C, B, Lreg, hist = bm_forward(bld, S, n, nslot=nslot)
    circ = bld.finish_circuit()
    sim = km.Simulator(batch_size=nshots, debug_print=False,
                       counting_operations=True, seed=1)
    sim.use_same_registers_as(circ)
    for j in range(n):
        sim.write_across_shots(
            km.array(S[j]),
            _bits_matrix([s[j] for s in S_list], DEGREE))
    sim.do(circ)
    ok_sig = 0
    tot_sig = 0
    for s in range(nshots):
        got = [_read_reg_shot(sim, C[i], s) for i in range(nslot)]
        ref_sig, _L = berlekamp_massey(S_list[s])
        ref_sig = ref_sig + [0] * (nslot - len(ref_sig))
        # normalizar el obtenido a mónico y comparar
        s0 = got[0]
        if s0 != 0:
            inv0 = gf_inv(s0)
            got_n = [gf_mul(v, inv0) for v in got]
        else:
            got_n = got
        for i in range(nslot):
            tot_sig += 1
            if got_n[i] == ref_sig[i]:
                ok_sig += 1
    res["bm_sigma_correct"] = ok_sig
    res["bm_sigma_total"] = tot_sig
    res["bm_qubits"] = circ.num_qubits
    res["bm_toffoli"] = circ.operation_statistics().num_toffoli_like
    # --- 2. Hybrid scan: fase ---
    # Cada shot usa su propio síndrome, polinomios y máscaras. La fase
    # esperada se calcula desde los errores de ENTRADA conocidos, como
    # hace el verificador DQI oficial; no desde la salida del decodificador.
    sigma_rows = []
    omega_rows = []
    masks_rows = []
    expected_phases = []
    nslot = (n // 2) + 1
    for shot in range(nshots):
        sigma, _ = berlekamp_massey(S_list[shot])
        omega = omega_from_sigma(sigma, S_list[shot])
        sigma_rows.append((sigma + [0] * nslot)[:nslot])
        omega_rows.append((omega + [0] * nslot)[:nslot])
        masks = {
            j: int(rng.integers(0, 1 << DEGREE))
            for j in range(m)
        }
        masks_rows.append(masks)
        expected_phases.append(
            expected_phase_parity(errs_list[shot], masks))

    bld2 = km.CircuitBuilder()
    C2 = [bld2.alloc_qubits(DEGREE) for _ in range(nslot)]
    O2 = [bld2.alloc_qubits(DEGREE) for _ in range(nslot)]
    E2 = [bld2.alloc_bits(DEGREE) for _ in range(m)]
    zero_reg = bld2.alloc_qubits(DEGREE)
    # El circuito completo usa todos los slots; los coeficientes
    # superiores son cero cuando el grado real del polinomio es menor.
    L_scan = nslot - 1
    hybrid_scan(bld2, C2, O2, E2, m, batch, L_scan, zero_reg)
    circ2 = bld2.finish_circuit()
    sim2 = km.Simulator(batch_size=nshots, debug_print=False,
                        counting_operations=True, seed=1)
    sim2.use_same_registers_as(circ2)
    for i in range(nslot):
        sim2.write_across_shots(
            km.array(C2[i]),
            _bits_matrix([sigma_rows[shot][i]
                          for shot in range(nshots)], DEGREE))
        sim2.write_across_shots(
            km.array(O2[i]),
            _bits_matrix([omega_rows[shot][i]
                          for shot in range(nshots)], DEGREE))
    for j in range(m):
        sim2.write_across_shots(
            km.array(E2[j]),
            _bits_matrix([masks_rows[shot][j]
                          for shot in range(nshots)], DEGREE))
    sim2.do(circ2)

    # Comprobar fase REAL producida por el simulador, no solo calcular
    # la fase esperada. El API devuelve un bit de phase-flip por shot.
    actual_phases = [
        bool(value)
        for value in sim2.read_phase_flipped_across_shots()
    ]
    phase_pairs = list(zip(actual_phases, expected_phases))
    phase_correct = sum(actual == expected
                        for actual, expected in phase_pairs)

    # El scan también debe preservar sigma y omega en cada shot.
    ok_scan = 0
    for shot in range(nshots):
        for i in range(nslot):
            if _read_reg_shot(sim2, C2[i], shot) == sigma_rows[shot][i]:
                ok_scan += 1
            if _read_reg_shot(sim2, O2[i], shot) == omega_rows[shot][i]:
                ok_scan += 1
    scan_total = 2 * nslot * nshots
    phase_total = nshots
    res["scan_registers_intact"] = ok_scan
    res["scan_registers_total"] = scan_total
    # Conservamos la clave anterior como el primer caso y añadimos la
    # secuencia completa para que los informes sean auditables.
    res["scan_expected_phase_parity"] = (
        expected_phases[0] if expected_phases else None)
    res["scan_expected_phase_parities"] = expected_phases
    res["scan_actual_phase_parities"] = actual_phases
    res["scan_phase_correct"] = phase_correct
    res["scan_phase_total"] = phase_total
    res["scan_phase_errors"] = phase_total - phase_correct
    res["scan_qubits"] = circ2.num_qubits
    res["scan_toffoli"] = circ2.operation_statistics().num_toffoli_like
    res["scan_note"] = (
        "fase comparada por shot con read_phase_flipped_across_shots; "
        "la referencia se calcula desde los errores de entrada. "
        "Esta prueba pequeña no sustituye al verificador DQI completo."
    )
    res["valid"] = (
        res["bm_sigma_correct"] == res["bm_sigma_total"]
        and res["scan_registers_intact"] == res["scan_registers_total"]
        and res["scan_phase_correct"] == res["scan_phase_total"]
    )
    return res


def diagnose_phase_positions(n=10, m=15, batch=4, seed=12345, nshots=4,
                             toom3=False):
    """Diagnóstico por shot de la fase DQI (no es certificación).

    Ejecuta el mismo camino que ``verify_small`` y devuelve, por shot,
    la paridad esperada, la medida y si coinciden. Útil para aislar si
    el rechazo por fase es sistemático o depende de la semilla.

    No altera el veredicto de ``verify_small`` ni sustituye el
    verificador oficial de 102,400 shots.
    """
    res = verify_small(n=n, m=m, batch=batch, seed=seed, nshots=nshots,
                       toom3=toom3)
    expected = list(res.get("scan_expected_phase_parities") or [])
    actual = list(res.get("scan_actual_phase_parities") or [])
    rows = []
    for i, (e, a) in enumerate(zip(expected, actual)):
        rows.append({
            "shot": i,
            "expected": int(bool(e)),
            "actual": int(bool(a)),
            "match": bool(e) == bool(a),
        })
    return {
        "n": n, "m": m, "batch": batch, "seed": seed, "nshots": nshots,
        "valid": bool(res.get("valid", False)),
        "phase_correct": res.get("scan_phase_correct"),
        "phase_total": res.get("scan_phase_total"),
        "phase_errors": res.get("scan_phase_errors"),
        "bm_sigma_ok": res.get("bm_sigma_correct") == res.get("bm_sigma_total"),
        "registers_ok": (
            res.get("scan_registers_intact") == res.get("scan_registers_total")
        ),
        "shots": rows,
        "note": (
            "Diagnóstico de fase por shot. Un match=False con sigma y "
            "registros correctos apunta al camino HMR/Forney/phase_kick, "
            "no al BM. Qwen Code 1.5 no interviene aquí."
        ),
    }


def diagnose_phase_ablation(n=10, m=15, seed=12345, nshots=8, toom3=False,
                            batches=(1, 4, 8)):
    """Ablación de fase: compara batch=1 (solo _single_position) vs lotes.

    HISTÓRICO: antes de v2.17.9, ``batch=1`` forzaba el camino
    ``_single_position`` en cada j (sin Montgomery) y ``batch>=2``
    usaba ``montgomery_batch`` (y cola single si aplica). La ablación
    localizó el defecto en el lote Montgomery (batch=1 limpio,
    batch>=2 con 2-5 errores de fase de 8). Desde v2.17.9 el scan
    usa siempre inversos directos (`hybrid_scan` ignora `batch`),
    así que esta ablación es ahora una comprobación de regresión:
    todos los lotes deben salir limpios. Si algún lote falla, el
    defecto volvió.

    - ``batch=1`` fuerza el camino ``_single_position`` en cada j
      (sin Montgomery).
    - ``batch>=2`` usaba ``montgomery_batch`` (y cola single si aplica).

    Si batch=1 falla igual que batch>1, el defecto no es exclusivo del
    lote Montgomery. Si solo fallan los lotes, el sospechoso es
    Montgomery / emparejamiento de inversiones.

    Devuelve un dict con una fila por batch y el resumen de fase.
    No es certificación estadística ni el verificador oficial.
    """
    rows = []
    for batch in batches:
        b = int(batch)
        if b < 1:
            continue
        # batch > m se recorta al comportamiento real del scan
        b_eff = min(b, m)
        try:
            res = verify_small(n=n, m=m, batch=b_eff, seed=seed,
                               nshots=nshots, toom3=toom3)
            # v2.17.9: el scan usa siempre inversos directos; la
            # etiqueta "montgomery_batch" es histórica (el camino
            # Montgomery está desactivado por fase).
            path = ("directo_single" if b_eff == 1
                    else "directo_lote_historico_montgomery")
            rows.append({
                "batch": b_eff,
                "path": path,
                "valid": bool(res.get("valid", False)),
                "phase_correct": res.get("scan_phase_correct"),
                "phase_total": res.get("scan_phase_total"),
                "phase_errors": res.get("scan_phase_errors"),
                "sigma_ok": res.get("bm_sigma_correct") == res.get("bm_sigma_total"),
                "registers_ok": (
                    res.get("scan_registers_intact")
                    == res.get("scan_registers_total")
                ),
                "error": None,
            })
        except Exception as exc:  # pragma: no cover - entorno sin kickmix
            rows.append({
                "batch": b_eff,
                "path": ("directo_single" if b_eff == 1
                         else "directo_lote_historico_montgomery"),
                "valid": None,
                "phase_correct": None,
                "phase_total": None,
                "phase_errors": None,
                "sigma_ok": None,
                "registers_ok": None,
                "error": f"{type(exc).__name__}: {exc}",
            })
    phase_errors = [r["phase_errors"] for r in rows if r["phase_errors"] is not None]
    return {
        "n": n, "m": m, "seed": seed, "nshots": nshots, "toom3": bool(toom3),
        "rows": rows,
        "all_paths_phase_clean": bool(phase_errors) and all(e == 0 for e in phase_errors),
        "note": (
            "Ablación batch=1 vs lotes (v2.17.9: todos directos, "
            "Montgomery desactivado por fase). Interpretación: errores "
            "solo con batch>1 → sospecha Montgomery; errores también "
            "con batch=1 → sospecha phase_kick/HMR/Forney por posición. "
            "Qwen Code 1.5 no interviene."
        ),
    }



def _bits_matrix(vals, nbits):
    """Matriz de bits para write_across_shots: forma (nbits, nshots).

    Igual que ``to_bits`` del verificador: las filas son los bits
    (bit k del valor) y las columnas los shots.
    """
    import numpy as np
    arr = np.zeros((nbits, len(vals)), dtype=bool)
    for s, v in enumerate(vals):
        for k in range(nbits):
            arr[k, s] = bool((v >> k) & 1)
    return arr


def _read_reg_shot(sim, reg, shot):
    """Lee un registro de 12 qubits como entero, en un shot dado."""
    bits = sim.read_across_shots(km.array(reg))
    return sum(int(bits[k, shot]) << k for k in range(DEGREE))


def main():
    ap = argparse.ArgumentParser(
        description="Generador híbrido DQI: BM + Forney con descomposición "
                    "híbrida (medición + descomputación clásica).")
    ap.add_argument("--n", type=int, default=70)
    ap.add_argument("--degree", type=int, default=12)
    ap.add_argument("--m", type=int, default=4095)
    ap.add_argument("--batch", type=int, default=17)
    ap.add_argument("--nslot", type=int, default=36)
    ap.add_argument("--toom3", action="store_true",
                    help="multiplicador Toom-3 (45 T/mult) en vez del "
                         "nativo (63 T/mult)")
    ap.add_argument("--format", default="kmb", choices=["kmb", "kmx"])
    ap.add_argument("--out", default="dqi_hybrid.kmb")
    ap.add_argument("--verify", action="store_true",
                    help="verifica a escala chica contra la referencia clásica")
    ap.add_argument("--shots", type=int, default=8)
    ap.add_argument("--seed", type=int, default=12345)
    args = ap.parse_args()

    if args.verify:
        t0 = time.time()
        res = verify_small(n=10, m=15, batch=4, seed=args.seed,
                           nshots=args.shots, toom3=args.toom3)
        res["verify_seconds"] = round(time.time() - t0, 1)
        print(json.dumps(res, indent=2))
        ok = bool(res["valid"])
        print("VERIFICACIÓN:", "PASS" if ok else "FAIL")
        return 0 if ok else 1

    t0 = time.time()
    circ, info = build_hybrid_bm_circuit(n=args.n, degree=args.degree,
                                         m=args.m, batch=args.batch,
                                         nslot=args.nslot,
                                         toom3=args.toom3)
    info["build_seconds"] = round(time.time() - t0, 1)
    circ.to_file(args.out, format=args.format)
    import os
    info["out"] = args.out
    info["bytes"] = os.path.getsize(args.out)
    print(json.dumps(info, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

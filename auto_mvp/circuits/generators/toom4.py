"""DQI Ajuste 1 (extra) — multiplicador GF(2^12) Toom-4 de 42 Toffolis.

GF(2^12) como extension de grado 4 de GF(2^3), Toom-4 = 7
sub-multiplicaciones GF(2^3) x 6 Toffolis = 42.
GF(2^3) = GF(2)[y]/(y^3+y+1) = 0xB (igual que kickmix GF2Field(3)).
GF(2^12) = GF(2^3)[t]/(t^4+2t^3+3t^2+t+2) sobre GF(2^3); puntos de
evaluacion {0,1,w,w^2,w^3,w^4,inf}, w = 0x2 en GF(2^3).
Verificado en Python clasico (check_toom4_classical.py): 510/510.

El sub-multiplicador GF(2^3) usa los 6 ANDs Karatsuba de PolyMul(3)
(verificacion simbolica 64/64 en el analisis): cada AND se calcula en
un temp de 1 qubit, se acumula en la salida con CNOTs y se borra con
del_and (MBUC, 0T, mismo patron que kickmix ccx_test.py). Sin del_and
serian 7T (libreria) o 12T (PolyMul(3) + re-aplicar para borrar el temp
de 5 bits). Con del_and: 6T por sub-multiplicacion, 42T en total.
Estructura del circuito (todo con CNOTs salvo las 7x6 sub-mult):
  - EA_i, EB_i (3 bits): evaluaciones lineales de a,b en el punto p_i.
  - P_i = EA_i * EB_i en GF(2^3) con el wrapper de 6 ANDs + del_and.
  - out ^= M_i * P_i (interpolacion + reduccion, lineal).
  - Deshacer por i: del_gf2_mul de la libreria (MBUC, 0T) para P_i,
    re-aplicar los CNOTs de evaluacion para EA_i, EB_i.
  - Secuencial por i: ancillas maximas 12 (EA+EB+P+temps AND). Q total 48, T 42.
  - ixor sin control: directo (out solo es target de CNOTs, nunca se mezcla).
  - ixor con control: temp + 12 CCX + del_gf2_mul (T=54, Q=61).
"""
from __future__ import annotations

import kickmix as km

from auto_mvp.circuits.generators.mult51 import (
    gf_mul as gf12_mul, gf_pow as gf12_pow, invert_cols)

MOD3 = 0xB
FIELD12 = km.GF2Field(12)
FIELD3 = km.GF2Field(3)
assert FIELD3.modulus == MOD3


# ---------------------------------------------------------------- GF(2^3)
def gf3_mul(a: int, b: int) -> int:
    p = 0
    for i in range(3):
        if (a >> i) & 1:
            p ^= b << i
    for k in range(4, 2, -1):
        if (p >> k) & 1:
            p ^= MOD3 << (k - 3)
    return p & 0x7


def gf3_pow(a: int, e: int) -> int:
    r = 1
    while e:
        if e & 1:
            r = gf3_mul(r, a)
        a = gf3_mul(a, a)
        e >>= 1
    return r


def gf3_inv(a: int) -> int:
    return gf3_pow(a, 6)


# ---------------------------------------------------------------- torre GF(2^3)[t]/(t^4+2t^3+3t^2+t+2)
def _find_root(fn):
    for x in range(1 << 12):
        if fn(x) == 0:
            return x
    raise ValueError("sin raiz")


BETA = _find_root(lambda y: gf12_mul(gf12_mul(y, y), y) ^ y ^ 1)
THETA = 0x2  # alpha primitivo; theta^64 != theta -> minpoly grado 4 sobre GF(8)
MINPOLY = [0x2, 0x1, 0x3, 0x2, 0x1]  # t^4 = 2 + t + 3t^2 + 2t^3
_BASIS = [gf12_mul(gf12_pow(BETA, i), gf12_pow(THETA, j))
          for j in range(4) for i in range(3)]
_BINV = invert_cols(_BASIS)  # columnas: coords torre de cada vector base polinomico


def to_tower(v: int) -> int:
    out = 0
    for i in range(12):
        if (v >> i) & 1:
            out ^= _BINV[i]
    return out


def from_tower(c: int) -> int:
    out = 0
    for k in range(12):
        if (c >> k) & 1:
            out ^= _BASIS[k]
    return out


def split_tower(c: int):
    return [(c >> (3 * j)) & 0x7 for j in range(4)]


W8 = 0x2  # generador de GF(2^3) mod 0xB, como entero de 3 bits
PTS = [0, 1, W8, gf3_pow(W8, 2), gf3_pow(W8, 3), gf3_pow(W8, 4)]


def _eval_at(limbs, p):
    r = 0
    for j in range(3, -1, -1):
        r = gf3_mul(r, p) ^ limbs[j]
    return r


def _interp(P):
    """P = [P0..P5, Pinf] (GF(2^3)) -> elemento GF(2^12) (entero 12 bits).
    Interpola C(x) con C(p_i)=P_i, c6=Pinf, y reduce mod minpoly."""
    n = 6
    rows = []
    for i, p in enumerate(PTS):
        row = [1]
        for _ in range(1, n):
            row.append(gf3_mul(row[-1], p))
        rhs = P[i] ^ gf3_mul(P[6], gf3_pow(p, 6))
        rows.append(row + [rhs])
    for col in range(n):
        piv = next(r for r in range(col, n) if rows[r][col] != 0)
        rows[col], rows[piv] = rows[piv], rows[col]
        inv = gf3_inv(rows[col][col])
        rows[col] = [gf3_mul(x, inv) for x in rows[col]]
        for r in range(n):
            if r != col and rows[r][col] != 0:
                f = rows[r][col]
                rows[r] = [x ^ gf3_mul(f, y) for x, y in zip(rows[r], rows[col])]
    c = [rows[i][n] for i in range(n)] + [P[6]]
    co = list(c) + [0] * (7 - len(c))
    for d in range(6, 3, -1):
        if co[d]:
            f = co[d]
            for j in range(4):
                co[d - 4 + j] ^= gf3_mul(f, MINPOLY[j])
            co[d] = 0
    tower = 0
    for j in range(4):
        tower |= co[j] << (3 * j)
    return from_tower(tower)


# Matrices de evaluacion: EA_i = EVAL[i] . a (3 mascaras de 12 bits sobre a).
def _eval_masks():
    masks = []
    for p in PTS:
        m = [0, 0, 0]
        for i in range(12):  # vector base polinomico e_i -> coords torre
            ct = _BINV[i]
            A = [(ct >> (3 * j)) & 0x7 for j in range(4)]
            v = _eval_at(A, p)
            for j in range(3):
                if (v >> j) & 1:
                    m[j] |= 1 << i
        masks.append(m)
    return masks


EVAL_MASKS = _eval_masks()

# Matrices de interpolacion: M_i[k] = contribucion de 12 bits a out si P_i = 1<<k.
INTERP_COLS = []
for i in range(7):
    cols = []
    for k in range(3):
        P = [0, 0, 0, 0, 0, 0, 0]
        P[i] = 1 << k
        cols.append(_interp(P))
    INTERP_COLS.append(cols)


# ---------------------------------------------------------------- GF(2^3) a 6 Toffolis (Karatsuba + del_and)
# ANDs de PolyMul(3) (analisis simbolico, 64/64): (forma_a, forma_b, outs).
# out0 = T2^T3^T5^T6 ; out1 = T2^T4^T5^T6 ; out2 = T1^T3^T4^T5.
GF3_ANDS = [
    ([0, 1, 2], [0, 1, 2], [2]),        # T1
    ([0], [0], [0, 1]),                  # T2
    ([2], [2], [0, 2]),                  # T3
    ([0, 1], [0, 1], [1, 2]),            # T4
    ([1, 2], [1, 2], [0, 1, 2]),         # T5
    ([1], [1], [0]),                     # T6
]


def emit_gf3_mul_zero(builder, f, g, h):
    """h <- f*g en GF(2^3) mod 0xB. Exige h=|0>. f,g intactos. T=6, Q=9+3 temp."""
    for fa, fb, outs in GF3_ANDS:
        la = builder.alloc_qubits(1)
        lb = builder.alloc_qubits(1)
        t = builder.alloc_qubits(1)
        for i in fa:
            builder.cx(f[i], la[0])
        for j in fb:
            builder.cx(g[j], lb[0])
        builder.ccx(la[0], lb[0], t[0])
        for bit in outs:
            builder.cx(t[0], h[bit])
        builder.del_and(la[0], lb[0], t[0])
        for i in fa:
            builder.cx(f[i], la[0])
        for j in fb:
            builder.cx(g[j], lb[0])
        builder.free(la + lb + t)


# ---------------------------------------------------------------- Toom-4 GF(2^12), 42 Toffolis
def _emit_eval(builder, src, dst, masks):
    """dst (3 bits, |0>) ^= EVAL . src (12 bits)."""
    for j in range(3):
        m = masks[j]
        for i in range(12):
            if (m >> i) & 1:
                builder.cx(src[i], dst[j])


def emit_toom4_zero(builder, f, g, h):
    """h <- f*g mod 0x1053. Exige h=|0>. f,g intactos. T=42, Q=48."""
    for i in range(7):
        ea = builder.alloc_qubits(3)
        eb = builder.alloc_qubits(3)
        p = builder.alloc_qubits(3)
        if i < 6:
            _emit_eval(builder, f, ea, EVAL_MASKS[i])
            _emit_eval(builder, g, eb, EVAL_MASKS[i])
        else:
            # punto infinito: EA = A3, EB = B3 (bits 9..11 de to_tower(.))
            for j in range(3):
                for q in range(12):
                    if (_BINV[q] >> (9 + j)) & 1:
                        builder.cx(f[q], ea[j])
                    if (_BINV[q] >> (9 + j)) & 1:
                        builder.cx(g[q], eb[j])
        emit_gf3_mul_zero(builder, ea, eb, p)
        for k in range(3):
            col = INTERP_COLS[i][k]
            for j in range(12):
                if (col >> j) & 1:
                    builder.cx(p[k], h[j])
        builder.del_gf2_mul(ea, eb, target=p, field=FIELD3)
        if i < 6:
            _emit_eval(builder, f, ea, EVAL_MASKS[i])
            _emit_eval(builder, g, eb, EVAL_MASKS[i])
        else:
            for j in range(3):
                for q in range(12):
                    if (_BINV[q] >> (9 + j)) & 1:
                        builder.cx(f[q], ea[j])
                    if (_BINV[q] >> (9 + j)) & 1:
                        builder.cx(g[q], eb[j])
        builder.free(ea + eb + p)


def emit_ixor_toom4(builder, f, g, target, control=None):
    """target ^= f*g (si control, solo cuando control=1). Sin control: T=42,
    Q=48. Con control: T=54, Q=61."""
    if control is None or control is True:
        emit_toom4_zero(builder, f, g, target)
    else:
        tmp = builder.alloc_qubits(12)
        emit_toom4_zero(builder, f, g, tmp)
        for i in range(12):
            builder.ccx(control, tmp[i], target[i])
        builder.del_gf2_mul(f, g, target=tmp, field=FIELD12)
        builder.free(tmp)

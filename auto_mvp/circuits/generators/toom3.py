"""DQI Ajuste 1 (extra) — multiplicador GF(2^12) Toom-3 de 45 Toffolis.

Mejora el 51 de [9]: GF(2^12) como extension de grado 3 de GF(2^4),
Toom-3 = 5 multiplicaciones GF(2^4) x 9 Toffolis = 45.
GF(2^4) = GF(2)[y]/(y^4+y+1) = 0x13 (igual que kickmix GF2Field(4)).
GF(2^12) = GF(2^4)[t]/(t^3+t+1); puntos de evaluacion {0,1,w,w^2,inf},
w = beta (raiz de y^4+y+1 en GF(2^12), orden 15).
Verificado en Python clasico (sim_toom3.py): 500/500 + bordes.

Estructura del circuito (todo con CNOTs salvo las 5 sub-mult):
  - EA_i, EB_i (4 bits): evaluaciones lineales de a,b en el punto p_i.
  - P_i = EA_i * EB_i en GF(2^4) con el wrapper Karatsuba (n=4,k=2, PolyMul(2)).
  - out ^= M_i * P_i (interpolacion + reduccion cubica, lineal).
  - Deshacer por i: del_gf2_mul de la libreria (MBUC, 0T) para P_i,
    re-aplicar los CNOTs de evaluacion para EA_i, EB_i.
  - Secuencial por i: ancillas maximas 12 (EA+EB+P). Q total 48, T 45.
  - ixor sin control: directo (out solo es target de CNOTs, nunca se mezcla).
  - ixor con control: temp + 12 CCX + del_gf2_mul (T=57, Q=61).
"""
from __future__ import annotations

import kickmix as km

from auto_mvp.circuits.generators.mult51 import (
    MOD, M, gf_mul as gf12_mul, gf_pow as gf12_pow,
    load_polymul, emit_polymul, synth_cnots, mat_cols,
    invert_cols, zeros_cnots, poly_mul)

MOD4 = 0x13
FIELD12 = km.GF2Field(12)
FIELD4 = km.GF2Field(4)
assert FIELD4.modulus == MOD4


# ---------------------------------------------------------------- GF(2^4)
def gf4_mul(a: int, b: int) -> int:
    p = poly_mul(a, b)
    for k in range(6, 3, -1):
        if (p >> k) & 1:
            p ^= MOD4 << (k - 4)
    return p & 0xF


def gf4_pow(a: int, e: int) -> int:
    r = 1
    while e:
        if e & 1:
            r = gf4_mul(r, a)
        a = gf4_mul(a, a)
        e >>= 1
    return r


def gf4_inv(a: int) -> int:
    return gf4_pow(a, 14)


# ---------------------------------------------------------------- torre GF(2^4)[t]/(t^3+t+1)
def _find_root(fn):
    for x in range(1 << 12):
        if fn(x) == 0:
            return x
    raise ValueError("sin raiz")


BETA = _find_root(lambda y: gf12_mul(gf12_mul(gf12_mul(y, y), y), y) ^ y ^ 1)
THETA = _find_root(lambda t: gf12_mul(gf12_mul(t, t), t) ^ t ^ 1)
_BASIS = [gf12_mul(gf12_pow(BETA, i), gf12_pow(THETA, j))
          for j in range(3) for i in range(4)]
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
    return [(c >> (4 * j)) & 0xF for j in range(3)]


W = 0x2  # beta como elemento de GF(2^4)
PTS = [0, 1, W, gf4_mul(W, W)]  # puntos finitos; el 5o es infinito


def _interp(P):
    """P = [P0..P3, Pinf] (GF(2^4)) -> elemento GF(2^12) (entero 12 bits).
    Interpola C(x) con C(p_i)=P_i, c4=Pinf, y reduce mod (t^3+t+1)."""
    rows = []
    for i, p in enumerate(PTS):
        row = [1, p, gf4_mul(p, p), gf4_mul(p, gf4_mul(p, p))]
        rhs = P[i] ^ gf4_mul(P[4], gf4_mul(p, gf4_mul(p, gf4_mul(p, p))))
        rows.append(row + [rhs])
    n = 4
    for col in range(n):
        piv = next(r for r in range(col, n) if rows[r][col] != 0)
        rows[col], rows[piv] = rows[piv], rows[col]
        inv = gf4_inv(rows[col][col])
        rows[col] = [gf4_mul(x, inv) for x in rows[col]]
        for r in range(n):
            if r != col and rows[r][col] != 0:
                f = rows[r][col]
                rows[r] = [x ^ gf4_mul(f, y) for x, y in zip(rows[r], rows[col])]
    c = [rows[i][n] for i in range(n)] + [P[4]]
    r0 = c[0] ^ c[3]
    r1 = c[1] ^ c[3] ^ c[4]
    r2 = c[2] ^ c[4]
    return from_tower(r0 | (r1 << 4) | (r2 << 8))


# Matrices de evaluacion: EA_i = EVAL[i] . a  (4 mascaras de 12 bits sobre a).
def _eval_masks():
    masks = []
    for p in PTS:
        # EA = A0 ^ p*A1 ^ p^2*A2 ; Aj = coords torre (4 bits) de a.
        # bit j de EA = XOR de bits de a: para cada bit de a, su contribucion es
        # (coord torre del vector base) -> A_j, luego *p^j en GF(2^4).
        m = [0, 0, 0, 0]
        for i in range(12):  # vector base polinomico e_i -> coords torre
            ct = _BINV[i]
            A = [(ct >> (4 * j)) & 0xF for j in range(3)]
            v = A[0] ^ gf4_mul(A[1], p) ^ gf4_mul(A[2], gf4_mul(p, p))
            for j in range(4):
                if (v >> j) & 1:
                    m[j] |= 1 << i
        masks.append(m)
    return masks


EVAL_MASKS = _eval_masks()

# Matrices de interpolacion: M_i[k] = contribucion de 12 bits a out si P_i = 1<<k.
INTERP_COLS = []
for i in range(5):
    cols = []
    for k in range(4):
        P = [0, 0, 0, 0, 0]
        P[i] = 1 << k
        cols.append(_interp(P))
    INTERP_COLS.append(cols)


# ---------------------------------------------------------------- wrapper GF(2^4) (n=4, k=2, mod 0x13)
def _gf4_mat(fn):
    return [fn(1 << i) for i in range(4)]


_MAP4_X2 = _gf4_mat(lambda a: gf4_mul(0x4, a))
_MAP4_X2_INV = invert_cols(_MAP4_X2, n=4)
_MAP4_1PX2 = _gf4_mat(lambda a: gf4_mul(0x5, a))
_MAP4_1PX2_INV = invert_cols(_MAP4_1PX2, n=4)
_C4_X2 = synth_cnots(_MAP4_X2, n=4)
_C4_X2_INV = synth_cnots(_MAP4_X2_INV, n=4)
_C4_1PX2 = synth_cnots(_MAP4_1PX2, n=4)
_C4_1PX2_INV = synth_cnots(_MAP4_1PX2_INV, n=4)
PM2 = load_polymul(2)


def _emit_cnots4(builder, cnots, reg):
    for c, t in cnots:
        builder.cx(reg[c], reg[t])


def emit_gf4_mul_zero(builder, f, g, h):
    """h <- f*g en GF(2^4) mod 0x13. Exige h=|0>. f,g intactos. T=9, Q=12."""
    k = 2
    for i in range(2):
        builder.cx(f[k + i], f[i])
        builder.cx(g[k + i], g[i])
    emit_polymul(builder, PM2, k, f[:k], g[:k], h[:2 * k - 1])
    for i in range(2):
        builder.cx(g[k + i], g[i])
        builder.cx(f[k + i], f[i])
    _emit_cnots4(builder, _C4_1PX2_INV, h)
    emit_polymul(builder, PM2, k, f[k:], g[k:], h[:2 * k - 1])
    _emit_cnots4(builder, _C4_X2, h)
    emit_polymul(builder, PM2, k, f[:k], g[:k], h[:2 * k - 1])
    _emit_cnots4(builder, _C4_1PX2, h)


# ---------------------------------------------------------------- Toom-3 GF(2^12), 45 Toffolis
def _emit_eval(builder, src, dst, masks):
    """dst (4 bits, |0>) ^= EVAL . src (12 bits)."""
    for j in range(4):
        m = masks[j]
        for i in range(12):
            if (m >> i) & 1:
                builder.cx(src[i], dst[j])


def emit_toom3_zero(builder, f, g, h):
    """h <- f*g mod 0x1053. Exige h=|0>. f,g intactos. T=45, Q=48."""
    for i in range(5):
        ea = builder.alloc_qubits(4)
        eb = builder.alloc_qubits(4)
        p = builder.alloc_qubits(4)
        if i < 4:
            _emit_eval(builder, f, ea, EVAL_MASKS[i])
            _emit_eval(builder, g, eb, EVAL_MASKS[i])
        else:
            # punto infinito: EA = A2, EB = B2 (bits 8..11 de to_tower(.))
            for j in range(4):
                for q in range(12):
                    if (_BINV[q] >> (8 + j)) & 1:
                        builder.cx(f[q], ea[j])
                    if (_BINV[q] >> (8 + j)) & 1:
                        builder.cx(g[q], eb[j])
        emit_gf4_mul_zero(builder, ea, eb, p)
        for k in range(4):
            col = INTERP_COLS[i][k]
            for j in range(12):
                if (col >> j) & 1:
                    builder.cx(p[k], h[j])
        builder.del_gf2_mul(ea, eb, target=p, field=FIELD4)
        if i < 4:
            _emit_eval(builder, f, ea, EVAL_MASKS[i])
            _emit_eval(builder, g, eb, EVAL_MASKS[i])
        else:
            for j in range(4):
                for q in range(12):
                    if (_BINV[q] >> (8 + j)) & 1:
                        builder.cx(f[q], ea[j])
                    if (_BINV[q] >> (8 + j)) & 1:
                        builder.cx(g[q], eb[j])
        builder.free(ea + eb + p)


def emit_ixor_toom3(builder, f, g, target, control=None):
    """target ^= f*g (si control, solo cuando control=1). Sin control: T=45,
    Q=48. Con control: T=57, Q=61."""
    if control is None or control is True:
        emit_toom3_zero(builder, f, g, target)
    else:
        tmp = builder.alloc_qubits(12)
        emit_toom3_zero(builder, f, g, tmp)
        for i in range(12):
            builder.ccx(control, tmp[i], target[i])
        builder.del_gf2_mul(f, g, target=tmp, field=FIELD12)
        builder.free(tmp)

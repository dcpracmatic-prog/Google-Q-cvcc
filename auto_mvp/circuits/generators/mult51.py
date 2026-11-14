"""DQI Ajustes 1 y 3 — multiplicador GF(2^12) de 51 Toffolis e inversion Itoh-Tsujii.

Fuente del 51: paper 2510.10967 Tabla VII + Apendice C, implementacion [9]
(Maslov, Yosri, Gavinsky) en el Zenodo del paper:
  - circuitos PolyMul(n) para n<=6 en dqi_zenodo/.../gf_arithmetic/circuits/poly_mul_{n}.txt
    (PolyMul(6) = 17 Toffolis; 3 x 17 = 51)
  - wrapper Karatsuba de Qualtran (_GF2MulViaKaratsubaImpl / _GF2MulViaOptimizedPolyMul):
    h <- P2; h *= (1+x^6)^-1; h ^= P1; h *= x^6; h ^= P0; h *= (1+x^6)
    donde P2=(f0+f1)(g0+g1), P1=f1*g1, P0=f0*g0, todo mod 0x1053.
    Verificado en Python clasico (sim_polymul.py): 500/500 + bordes.

El campo es el de la competencia: GF(2^12), modulo 0x1053
(x^12 + x^6 + x^4 + x + 1), base polinomica little-endian.

Interfaz (compatible con kickmix para poder sustituirla en el decodificador):
  - emit_mul51_zero(builder, f, g, h): h <- f*g, exige h = |0>. f,g intactos. T=51, Q=36.
  - emit_ixor_mul51(builder, f, g, target, control=None, field): target ^= f*g
    (control=True/None = sin control; control=qubit = controlado).
    Sin control: pre-mapa lineal x^-6 sobre target + wrapper (T=51, Q=36).
      (El wrapper cumple W(h) = P ^ x^6*h, probado en check_w_and_cnot.py 300/300,
       asi que pre-aplicar x^-6 deja target ^= P.)
    Con control: producto en temp (51T) + 12 CCX + del_gf2_mul de la libreria
      (MBUC, 0T) para deshacer el temp (T=63, Q=49). Igual patron que la libreria.
  - emit_inverse51_init / emit_inverse51_del: inversion Itoh-Tsujii, cadena
    a^3, a^15, a^31, a^1023, a^2047, cuadrado -> a^4094. 5 multiplicaciones.
    init T=255, del T=0 (via del_gf2_mul de la libreria por mult). Scaffold 48 + temp 12.
  - emit_div51_init / emit_div51_del: division a/b = a * b^-1. init T=306, scaffold 60.

Todo verificado contra kickmix Simulator en verify_mult51.py.
"""
from __future__ import annotations

import os
from pathlib import Path

import kickmix as km

MOD = 0x1053
M = 12
K = 6

# Las tablas PolyMul(n) viven junto a este modulo en el repo
# (auto_mvp/circuits/generators/poly_mul_{n}.txt), no en el sandbox.
CIRC_DIR = str(Path(__file__).resolve().parent)

# ------------------------------------------------------------------ aritmetica GF(2^12) con enteros
def poly_mul(a: int, b: int) -> int:
    p = 0
    for i in range(32):
        if (a >> i) & 1:
            p ^= b << i
    return p


def gf_mul(a: int, b: int, mod: int = MOD) -> int:
    p = poly_mul(a, b)
    for k in range(2 * M - 2, M - 1, -1):
        if (p >> k) & 1:
            p ^= mod << (k - M)
    return p & ((1 << M) - 1)


def gf_pow(a: int, e: int) -> int:
    r = 1
    while e:
        if e & 1:
            r = gf_mul(r, a)
        a = gf_mul(a, a)
        e >>= 1
    return r


# ------------------------------------------------------------------ matrices binarias 12x12
def mat_cols(fn, n: int = M):
    """Columnas de la matriz del mapa lineal fn: cols[i] = fn(1<<i)."""
    return [fn(1 << i) for i in range(n)]


def apply_mat(cols, v: int) -> int:
    out = 0
    for i in range(M):
        if (v >> i) & 1:
            out ^= cols[i]
    return out


def invert_cols(cols, n: int = M):
    rows = [[((cols[i] >> j) & 1) for i in range(n)] + [1 if j == k else 0 for k in range(n)]
            for j in range(n)]
    for col in range(n):
        piv = next(r for r in range(col, n) if rows[r][col])
        rows[col], rows[piv] = rows[piv], rows[col]
        for r in range(n):
            if r != col and rows[r][col]:
                rows[r] = [a ^ b for a, b in zip(rows[r], rows[col])]
    return [sum(rows[j][n + i] << j for j in range(n)) for i in range(n)]


def synth_cnots(cols, n: int = M):
    """CNOTs (control, target) que aplican h <- M*h in-place.

    Eliminacion gaussiana solo con sumas de filas (sin swaps); las operaciones
    registradas llevan M a I por la izquierda, asi que el circuito es la lista
    en orden inverso. Verificado en check_w_and_cnot.py.
    """
    rows = [sum((((cols[i] >> j) & 1) << i) for i in range(n)) for j in range(n)]
    ops = []
    for col in range(n):
        if not (rows[col] >> col) & 1:
            piv = next(r for r in range(col + 1, n) if (rows[r] >> col) & 1)
            rows[col] ^= rows[piv]
            ops.append((piv, col))
        for r in range(n):
            if r != col and ((rows[r] >> col) & 1):
                rows[r] ^= rows[col]
                ops.append((col, r))
    assert all(rows[j] == (1 << j) for j in range(n))
    return list(reversed(ops))


def zeros_cnots(cols, n: int = M):
    """CNOTs (control=bit de entrada i, target=bit de salida j) que calculan
    dst ^= M*src con dst empezando en |0>. Reaplicar la misma lista (cualquier
    orden) deshace dst porque los controles nunca son targets."""
    ops = []
    for j in range(n):
        for i in range(n):
            if (cols[i] >> j) & 1:
                ops.append((i, j))
    return ops


# Mapas lineales que usa el multiplicador (precalculados una vez).
MAP_X6 = mat_cols(lambda a: gf_mul(1 << K, a))
MAP_X6_INV = invert_cols(MAP_X6)
MAP_1PX6 = mat_cols(lambda a: gf_mul((1 << K) | 1, a))
MAP_1PX6_INV = invert_cols(MAP_1PX6)
MAP_SQ = mat_cols(lambda a: gf_mul(a, a))
MAP_SQ2 = mat_cols(lambda a: gf_pow(a, 4))    # a -> a^4
MAP_SQ5 = mat_cols(lambda a: gf_pow(a, 32))   # a -> a^32

CNOTS_X6 = synth_cnots(MAP_X6)
CNOTS_X6_INV = synth_cnots(MAP_X6_INV)
CNOTS_1PX6 = synth_cnots(MAP_1PX6)
CNOTS_1PX6_INV = synth_cnots(MAP_1PX6_INV)
CNOTS_SQ_INPLACE = synth_cnots(MAP_SQ)


def _check_field(field):
    if field is None:
        return
    if getattr(field, 'degree', M) != M or getattr(field, 'modulus', MOD) != MOD:
        raise ValueError(f"este modulo solo sirve para GF(2^12) mod 0x1053, "
                         f"recibido grado={getattr(field, 'degree', '?')} "
                         f"modulo={getattr(field, 'modulus', '?'):#x}")


# ------------------------------------------------------------------ circuitos PolyMul(n) de [9]
def _qidx(name: str, n: int) -> int:
    name = name.replace('_', '')
    return int(name[1:]) + (ord(name[0].lower()) - ord('a')) * n


def load_polymul(n: int):
    """Devuelve la lista de ops del txt como (kind, a, b, c) con indices
    absolutos en el layout [a(0..n-1), b(n..2n-1), c(2n..4n-2)].
    kind 'cx': (ctrl, tgt); kind 'ccx': (c1, c2, tgt)."""
    ops = []
    with open(os.path.join(CIRC_DIR, f'poly_mul_{n}.txt')) as fh:
        for line in fh:
            p = line.split()
            if not p:
                continue
            idx = [_qidx(x, n) for x in p[1:]]
            if p[0] == 'cnot':
                ops.append(('cx', idx[0], idx[1]))
            elif p[0] == 'toffoli':
                ops.append(('ccx', idx[0], idx[1], idx[2]))
            else:
                raise ValueError(f"op desconocida {p[0]} en poly_mul_{n}.txt")
    return ops


PM6 = load_polymul(6)
PM6_TOFFOLI = sum(1 for o in PM6 if o[0] == 'ccx')
PM6_CNOT = sum(1 for o in PM6 if o[0] == 'cx')


def emit_polymul(builder, ops, n: int, f_bits, g_bits, h_bits):
    """Emite un circuito PolyMul(n): f,g intactos, h ^= f*g (polinomio, 2n-1 bits)."""
    wires = list(f_bits) + list(g_bits) + list(h_bits)
    for op in ops:
        if op[0] == 'cx':
            builder.cx(wires[op[1]], wires[op[2]])
        else:
            builder.ccx(wires[op[1]], wires[op[2]], wires[op[3]])


def emit_cnots(builder, cnots, reg):
    for c, t in cnots:
        builder.cx(reg[c], reg[t])


# ------------------------------------------------------------------ multiplicador 51
def emit_mul51_zero(builder, f, g, h, field=None):
    """h <- f*g mod 0x1053. Exige h = |0> a la entrada. f,g intactos.
    T = 51 (3 x PolyMul(6) de 17). Q = 36, sin ancillas."""
    _check_field(field)
    for i in range(M - K):
        builder.cx(f[K + i], f[i])
        builder.cx(g[K + i], g[i])
    emit_polymul(builder, PM6, K, f[:K], g[:K], h[:2 * K - 1])
    for i in range(M - K):
        builder.cx(g[K + i], g[i])
        builder.cx(f[K + i], f[i])
    emit_cnots(builder, CNOTS_1PX6_INV, h)
    emit_polymul(builder, PM6, K, f[K:], g[K:], h[:2 * K - 1])
    emit_cnots(builder, CNOTS_X6, h)
    emit_polymul(builder, PM6, K, f[:K], g[:K], h[:2 * K - 1])
    emit_cnots(builder, CNOTS_1PX6, h)


def emit_ixor_mul51(builder, f, g, target, field=None, control=None):
    """target ^= f*g (si control, solo cuando control=1). Semantica identica a
    kickmix ixor_gf2_mul. Sin control: T=51, Q=36. Con control: T=63, Q=49."""
    _check_field(field)
    if control is None or control is True:
        # W(h) = P ^ x^6*h  =>  pre-aplicar x^-6 deja target ^= P.
        emit_cnots(builder, CNOTS_X6_INV, target)
        emit_mul51_zero(builder, f, g, target, field=field)
    else:
        tmp = builder.alloc_qubits(M)
        emit_mul51_zero(builder, f, g, tmp, field=field)
        for i in range(M):
            builder.ccx(control, tmp[i], target[i])
        builder.del_gf2_mul(f, g, target=tmp, field=field)
        builder.free(tmp)


# ------------------------------------------------------------------ inversion Itoh-Tsujii (5 mults)
def _square_into(builder, src, dst, cols):
    """dst ^= src^{2^e} (dst debe estar en |0>); cols = columnas del mapa."""
    for i, j in zeros_cnots(cols):
        builder.cx(src[i], dst[j])


def _square_into_undo(builder, src, dst, cols):
    _square_into(builder, src, dst, cols)  # mismos CNOTs: controles intactos => deshace


def emit_inverse51_init(builder, x, target, field=None):
    """target <- x^-1 (target debe empezar en |0>). x intacto.
    Cadena: a^3, a^15, a^31, a^1023, a^2047, cuadrado -> a^4094.
    Devuelve el scaffold (4 registros de 12 = 48 qubits) para el del.
    T(init) = 5*51 = 255."""
    _check_field(field)
    R = [builder.alloc_qubits(M) for _ in range(4)]
    T = builder.alloc_qubits(M)
    # R0 = a^3 = a^2 * a
    _square_into(builder, x, T, MAP_SQ)
    emit_mul51_zero(builder, T, x, R[0], field=field)
    _square_into_undo(builder, x, T, MAP_SQ)
    # R1 = a^15 = (a^3)^4 * a^3
    _square_into(builder, R[0], T, MAP_SQ2)
    emit_mul51_zero(builder, T, R[0], R[1], field=field)
    _square_into_undo(builder, R[0], T, MAP_SQ2)
    # R2 = a^31 = (a^15)^2 * a
    _square_into(builder, R[1], T, MAP_SQ)
    emit_mul51_zero(builder, T, x, R[2], field=field)
    _square_into_undo(builder, R[1], T, MAP_SQ)
    # R3 = a^1023 = (a^31)^32 * a^31
    _square_into(builder, R[2], T, MAP_SQ5)
    emit_mul51_zero(builder, T, R[2], R[3], field=field)
    _square_into_undo(builder, R[2], T, MAP_SQ5)
    # target = a^2047 = (a^1023)^2 * a
    _square_into(builder, R[3], T, MAP_SQ)
    emit_mul51_zero(builder, T, x, target, field=field)
    _square_into_undo(builder, R[3], T, MAP_SQ)
    # target = (a^2047)^2 = a^4094 (cuadrado in-place)
    emit_cnots(builder, CNOTS_SQ_INPLACE, target)
    builder.free(T)
    return km.array([q for r in R for q in r])


def _split_scaffold(scaffold):
    """Scaffold plano de 48 qubits -> 4 registros de 12 (o lista de 4 si ya lo es)."""
    flat = list(scaffold)
    if len(flat) == 48:
        return [km.array(flat[12 * i:12 * (i + 1)]) for i in range(4)]
    return [km.array(list(r)) for r in scaffold]


def emit_inverse51_del(builder, x, target, field=None, scaffold=None):
    """Deshace emit_inverse51_init: target y scaffold vuelven a |0>. T(del) = 0
    (cada mult se deshace con del_gf2_mul de la libreria, MBUC)."""
    _check_field(field)
    R = _split_scaffold(scaffold)
    T = builder.alloc_qubits(M)
    # deshacer el cuadrado final in-place (mismos CNOTs en orden inverso)
    for c, t in reversed(CNOTS_SQ_INPLACE):
        builder.cx(target[c], target[t])
    # deshacer la mult a^2047: recomponer T=(a^1023)^2, del, deshacer T
    _square_into(builder, R[3], T, MAP_SQ)
    builder.del_gf2_mul(T, x, target=target, field=field)
    _square_into_undo(builder, R[3], T, MAP_SQ)
    # R3 = (a^31)^32 * a^31
    _square_into(builder, R[2], T, MAP_SQ5)
    builder.del_gf2_mul(T, R[2], target=R[3], field=field)
    _square_into_undo(builder, R[2], T, MAP_SQ5)
    # R2 = (a^15)^2 * a
    _square_into(builder, R[1], T, MAP_SQ)
    builder.del_gf2_mul(T, x, target=R[2], field=field)
    _square_into_undo(builder, R[1], T, MAP_SQ)
    # R1 = (a^3)^4 * a^3
    _square_into(builder, R[0], T, MAP_SQ2)
    builder.del_gf2_mul(T, R[0], target=R[1], field=field)
    _square_into_undo(builder, R[0], T, MAP_SQ2)
    # R0 = a^2 * a
    _square_into(builder, x, T, MAP_SQ)
    builder.del_gf2_mul(T, x, target=R[0], field=field)
    _square_into_undo(builder, x, T, MAP_SQ)
    builder.free(T)


# ------------------------------------------------------------------ division (a/b = a * b^-1)
def emit_div51_init(builder, num, den, field=None, target=None):
    """ratio <- num/den (ratio nuevo en |0>, o `target` si se pasa).
    Devuelve (ratio, scaffold). T(init) = 255 (inv) + 51 (mult) = 306. Scaffold 60."""
    _check_field(field)
    inv_b = builder.alloc_qubits(M)
    scaf_inv = emit_inverse51_init(builder, den, inv_b, field=field)
    ratio = target if target is not None else builder.alloc_qubits(M)
    emit_mul51_zero(builder, num, inv_b, ratio, field=field)
    scaffold = km.array(list(scaf_inv) + list(inv_b))
    return ratio, scaffold


def emit_div51_del(builder, num, den, target=None, scaffold=None, field=None):
    """Deshace emit_div51_init. target=ratio, scaffold el devuelto por init."""
    _check_field(field)
    flat = list(scaffold)
    scaf_inv = km.array(flat[:48])
    inv_b = km.array(flat[48:60])
    builder.del_gf2_mul(num, inv_b, target=target, field=field)
    emit_inverse51_del(builder, den, inv_b, field=field, scaffold=scaf_inv)

"""Aceleración nativa opcional (familias B/F/G): SpMM SIMD, Dijkstra FIELD,
fricción SWAR.

Solo stdlib. Cada función tiene una implementación en Python puro con la
misma semántica; cuando el .so nativo se puede compilar (cc/c++ -O2 -shared
-fPIC, con un wrapper C++ mínimo para FIELD, cuya función es C++ con
mangling) y cargar por ctypes, se usa. Ante cualquier fallo, fallback
silencioso y el motivo queda en available().

Fuentes vendidas en el repo (``auto_mvp/native/``, materia prima de
Arturo, desde v1.5.0; antes se leían de ~/workspace/user/files/, fuera
del repo): simd_engine_36_b682.c (spmm_hbag_simd),
field_engine_native_v2_20_mg4n.cpp (dijkstra -> {cost, ok}),
swar_fleet_22_qpwm.c (evaluate_agent_friction).
"""

from __future__ import annotations

import ctypes
import hashlib
import heapq
import math
import platform
import shutil
import subprocess
from pathlib import Path

__all__ = ["available", "spmm_csr_dense", "swar_friction", "dijkstra"]

_MASK64 = (1 << 64) - 1
_PATTERN = 0x5555555555555555
_SRC_DIR = Path(__file__).resolve().parent / "native"
_CACHE = Path.home() / ".cache" / "auto_mvp" / "accel"

_SOURCES = {
    "spmm": "simd_engine_36_b682.c",
    "field": "field_engine_native_v2_20_mg4n.cpp",
    "swar": "swar_fleet_22_qpwm.c",
}

# Wrapper mínimo: FIELD no exporta en C (dijkstra es C++ con mangling).
_FIELD_WRAPPER = """\
#include "@@SRC@@"
#include <limits>
extern "C" int field_dijkstra_all(int n, const int* eu, const int* ev,
                                  const double* ew, int m, int src,
                                  double* out) {
    Graph g; g.n = n; g.adj.assign(n, {});
    for (int i = 0; i < m; i++) g.adj[eu[i]][ev[i]] = ew[i];
    for (int t = 0; t < n; t++) {
        DijkResult r = dijkstra(g, src, t);
        out[t] = r.ok ? r.cost : std::numeric_limits<double>::infinity();
    }
    return 0;
}
"""

_state = {k: {"loaded": False, "reason": "no intentado", "lib": None} for k in _SOURCES}
_tried = set()


class _CSR(ctypes.Structure):
    _fields_ = [("row_ptr", ctypes.POINTER(ctypes.c_int)), ("col_idx", ctypes.POINTER(ctypes.c_int)),
                ("values", ctypes.POINTER(ctypes.c_float)), ("nnz", ctypes.c_int)]


def _key() -> str:
    h = hashlib.sha256(platform.machine().encode())
    for kind in ("spmm", "field", "swar"):
        p = _SRC_DIR / _SOURCES[kind]
        h.update(p.read_bytes() if p.exists() else b"")
    h.update(_FIELD_WRAPPER.encode())
    return h.hexdigest()[:16]


def _run(cmd) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception as e:  # noqa: BLE001 - cualquier fallo -> fallback
        return False, f"{type(e).__name__}: {e}"[:200]
    if r.returncode == 0:
        return True, ""
    err = (r.stderr or r.stdout or f"exit {r.returncode}").strip().splitlines()
    return False, (err[-1] if err else f"exit {r.returncode}")[:200]


def _build(kind: str, src: Path, so: Path, key: str) -> tuple[bool, str]:
    if kind == "field":
        cxx = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        if not cxx:
            return False, "sin compilador C++ (c++/g++/clang++)"
        wrapper = _CACHE / f"field-wrapper-{key}.cpp"
        wrapper.write_text(_FIELD_WRAPPER.replace("@@SRC@@", str(src)))
        cmd = [cxx, "-O2", "-shared", "-fPIC", str(wrapper), "-o", str(so)]
    else:
        cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
        if not cc:
            return False, "sin compilador C (cc/gcc/clang)"
        cmd = [cc, "-O2", "-shared", "-fPIC"]
        if kind == "spmm":
            cmd += ["-march=native"]  # AVX2/FMA de spmm_hbag_simd
        cmd += [str(src), "-o", str(so)]
        if kind == "spmm":
            cmd += ["-lm"]
    return _run(cmd)


def _setup(kind: str, lib) -> None:
    if kind == "spmm":
        lib.spmm_hbag_simd.argtypes = [ctypes.POINTER(_CSR),
                                       ctypes.POINTER(ctypes.c_float),
                                       ctypes.POINTER(ctypes.c_float),
                                       ctypes.c_int, ctypes.c_int, ctypes.c_int]
        lib.spmm_hbag_simd.restype = None
    elif kind == "swar":
        lib.evaluate_agent_friction.argtypes = [ctypes.c_uint64, ctypes.c_uint64]
        lib.evaluate_agent_friction.restype = ctypes.c_uint64
    else:
        lib.field_dijkstra_all.argtypes = [ctypes.c_int,
                                           ctypes.POINTER(ctypes.c_int),
                                           ctypes.POINTER(ctypes.c_int),
                                           ctypes.POINTER(ctypes.c_double),
                                           ctypes.c_int, ctypes.c_int,
                                           ctypes.POINTER(ctypes.c_double)]
        lib.field_dijkstra_all.restype = ctypes.c_int


def _ensure(kind: str) -> dict:
    st = _state[kind]
    if kind in _tried:
        return st
    _tried.add(kind)
    try:
        _CACHE.mkdir(parents=True, exist_ok=True)
        src = _SRC_DIR / _SOURCES[kind]
        if not src.exists():
            st["reason"] = f"fuente no encontrada: {src.name}"
            return st
        so = _CACHE / f"{kind}-{_key()}.so"
        if not so.exists():
            ok, err = _build(kind, src, so, _key())
            if not ok:
                st["reason"] = f"no compiló: {err}"
                return st
        lib = ctypes.CDLL(str(so))
        _setup(kind, lib)
        st["lib"] = lib
        st["loaded"] = True
        st["reason"] = f"nativo cargado: {so.name}"
    except Exception as e:  # noqa: BLE001 - cualquier fallo -> fallback
        st["reason"] = f"{type(e).__name__}: {e}"[:200]
    return st


def available() -> dict:
    return {k: {"loaded": _ensure(k)["loaded"], "reason": _ensure(k)["reason"]}
            for k in ("spmm", "field", "swar")}


# Python puro (misma semántica que el nativo; también es el fallback)

def _spmm_py(row_ptr, col_idx, values, rows, n, k_cols):
    C = [[0.0] * k_cols for _ in range(n)]
    for i in range(n):
        crow = C[i]
        for j in range(row_ptr[i], row_ptr[i + 1]):
            v = values[j]
            brow = rows[col_idx[j]]
            for c in range(k_cols):
                crow[c] += v * brow[c]
    return C


def _swar_py(agent_mask: int, payload_hash: int) -> int:
    return bin(((agent_mask ^ payload_hash) & _MASK64) & _PATTERN).count("1")


def _dijkstra_py(n, edges, src):
    adj = [[] for _ in range(n)]
    for u, v, w in edges:
        adj[u].append((v, w))
    dist = [math.inf] * n
    dist[src] = 0.0
    pq = [(0.0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if d != dist[u]:
            continue
        for v, w in adj[u]:
            nd = d + w
            if nd < dist[v]:
                dist[v] = nd
                heapq.heappush(pq, (nd, v))
    return dist


# API pública (nativo si está, si no Python puro)

def _as_rows(B, k_cols):
    if not B:
        return []
    if isinstance(B[0], (list, tuple)):
        rows = [list(r) for r in B]
        if any(len(r) < k_cols for r in rows):
            raise ValueError("cada fila de B debe tener al menos k_cols")
        return [r[:k_cols] for r in rows]
    flat = list(B)
    if len(flat) % k_cols:
        raise ValueError("B plana: longitud no múltiplo de k_cols")
    return [flat[i:i + k_cols] for i in range(0, len(flat), k_cols)]


def _spmm_native(lib, row_ptr, col_idx, values, rows, n, k_cols):
    # El nativo procesa de 8 en 8 (AVX2): stride = k_cols redondeado a múltiplo de 8.
    k_stride = ((k_cols + 7) // 8) * 8
    m = len(rows)
    B = (ctypes.c_float * (m * k_stride))()
    for i, r in enumerate(rows):
        for c, v in enumerate(r):
            B[i * k_stride + c] = v
    C = (ctypes.c_float * (n * k_stride))()
    A = _CSR((ctypes.c_int * len(row_ptr))(*row_ptr),
             (ctypes.c_int * len(col_idx))(*col_idx),
             (ctypes.c_float * len(values))(*values), len(values))
    lib.spmm_hbag_simd(ctypes.byref(A), B, C, n, k_cols, k_stride)
    return [[C[i * k_stride + c] for c in range(k_cols)] for i in range(n)]


def spmm_csr_dense(row_ptr, col_idx, values, B, n, k_cols):
    """CSR dispersa (n x m) por densa (m x k_cols, row-major) -> n x k_cols (B plana o por filas)."""
    row_ptr, col_idx, values = list(row_ptr), list(col_idx), list(values)
    n, k_cols = int(n), int(k_cols)
    if n < 0 or k_cols < 0:
        raise ValueError("n y k_cols >= 0")
    if len(row_ptr) != n + 1 or row_ptr[0] != 0:
        raise ValueError("row_ptr debe tener n+1 entradas y empezar en 0")
    if any(row_ptr[i] > row_ptr[i + 1] for i in range(n)):
        raise ValueError("row_ptr no monótono")
    if len(col_idx) != len(values) or row_ptr[-1] != len(col_idx):
        raise ValueError("col_idx/values no cuadran con row_ptr")
    if k_cols == 0:
        return [[] for _ in range(n)]
    rows = _as_rows(B, k_cols)
    if any(c < 0 or c >= len(rows) for c in col_idx):
        raise ValueError("col_idx fuera de rango")
    st = _ensure("spmm")
    if st["loaded"]:
        try:
            return _spmm_native(st["lib"], row_ptr, col_idx, values,
                                rows, n, k_cols)
        except Exception:  # noqa: BLE001 - cae al fallback
            pass
    return _spmm_py(row_ptr, col_idx, values, rows, n, k_cols)


def swar_friction(agent_mask: int, payload_hash: int) -> int:
    """popcount((mask ^ hash) & 0x5555...) — fricción SWAR, máx. 32."""
    a = int(agent_mask) & _MASK64
    h = int(payload_hash) & _MASK64
    st = _ensure("swar")
    if st["loaded"]:
        try:
            return int(st["lib"].evaluate_agent_friction(a, h))
        except Exception:  # noqa: BLE001 - cae al fallback
            pass
    return _swar_py(a, h)


def _dijkstra_native(lib, n, edges, src):
    m = len(edges)
    eu = (ctypes.c_int * m)(*[u for u, _, _ in edges]) if m else None
    ev = (ctypes.c_int * m)(*[v for _, v, _ in edges]) if m else None
    ew = (ctypes.c_double * m)(*[w for _, _, w in edges]) if m else None
    out = (ctypes.c_double * n)()
    lib.field_dijkstra_all(n, eu, ev, ew, m, src, out)
    return list(out)


def dijkstra(n: int, edges: list, src: int) -> list:
    """Distancias mínimas desde src (aristas dirigidas); inf si inalcanzable."""
    n, src = int(n), int(src)
    if n < 0:
        raise ValueError("n >= 0")
    if n == 0:
        return []
    if not 0 <= src < n:
        raise ValueError("src fuera de rango")
    edges = [(int(u), int(v), float(w)) for u, v, w in edges]
    for u, v, w in edges:
        if not (0 <= u < n and 0 <= v < n) or not math.isfinite(w):
            raise ValueError("arista inválida")
    st = _ensure("field")
    if st["loaded"]:
        try:
            return _dijkstra_native(st["lib"], n, edges, src)
        except Exception:  # noqa: BLE001 - cae al fallback
            pass
    return _dijkstra_py(n, edges, src)

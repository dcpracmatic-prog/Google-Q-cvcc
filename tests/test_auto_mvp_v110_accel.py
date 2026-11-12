"""Aceleración nativa opcional (v1.1.0): fallback correcto y nativo == fallback."""
import math

import pytest

from auto_mvp import accel
from auto_mvp.accel import _dijkstra_py, _spmm_py, _swar_py

# Caso SpMM conocido: A = [[1, 0, 2], [0, 3, 0]], B = [[1, 2], [3, 4], [5, 6]]
ROW_PTR = [0, 2, 3]
COL_IDX = [0, 2, 1]
VALUES = [1.0, 2.0, 3.0]
B_ROWS = [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]
C_EXPECTED = [[11.0, 14.0], [9.0, 12.0]]

# Grafo conocido: 0->1 (1), 0->2 (4), 1->2 (2), 1->3 (6), 2->3 (3); 4 aislado.
EDGES = [(0, 1, 1.0), (0, 2, 4.0), (1, 2, 2.0), (1, 3, 6.0), (2, 3, 3.0)]
DIST_EXPECTED = [0.0, 1.0, 3.0, 6.0, math.inf]


def _naive_spmm(row_ptr, col_idx, values, rows, n, k_cols):
    """Referencia ingenua independiente: reconstruye la densa y multiplica."""
    A = [[0.0] * len(rows) for _ in range(n)]
    for i in range(n):
        for j in range(row_ptr[i], row_ptr[i + 1]):
            A[i][col_idx[j]] = values[j]
    return [[sum(A[i][k] * rows[k][c] for k in range(len(rows)))
             for c in range(k_cols)] for i in range(n)]


def test_fallback_spmm_correcto():
    got = _spmm_py(ROW_PTR, COL_IDX, VALUES, B_ROWS, 2, 2)
    assert got == C_EXPECTED
    assert got == _naive_spmm(ROW_PTR, COL_IDX, VALUES, B_ROWS, 2, 2)
    # B plana (row-major) da lo mismo, y k_cols no múltiplo de 8 también.
    assert accel.spmm_csr_dense(ROW_PTR, COL_IDX, VALUES,
                                [1.0, 2.0, 3.0, 4.0, 5.0, 6.0], 2, 2) == C_EXPECTED
    assert accel.spmm_csr_dense(ROW_PTR, COL_IDX, VALUES, B_ROWS, 2, 2) == C_EXPECTED


def test_fallback_dijkstra_correcto():
    assert _dijkstra_py(5, EDGES, 0) == DIST_EXPECTED
    assert accel.dijkstra(5, EDGES, 0) == DIST_EXPECTED
    assert _dijkstra_py(3, [(0, 1, 2.5)], 2) == [math.inf, math.inf, 0.0]


def test_fallback_swar_correcto():
    cases = [(0, 0), (0xFFFFFFFFFFFFFFFF, 0), (0, 0xFFFFFFFFFFFFFFFF),
             (0xAAAAAAAAAAAAAAAA, 0x5555555555555555), (123456789, 987654321)]
    for a, h in cases:
        expected = bin(((a ^ h) & 0xFFFFFFFFFFFFFFFF) & 0x5555555555555555).count("1")
        assert _swar_py(a, h) == expected
        assert accel.swar_friction(a, h) == expected
    assert accel.swar_friction(0xFFFFFFFFFFFFFFFF, 0) == 32
    assert accel.swar_friction(0, 0) == 0


def test_nativo_spmm_igual_fallback():
    if not accel.available()["spmm"]["loaded"]:
        pytest.skip("spmm nativo no disponible")
    # k_cols=5 (no múltiplo de 8) ejercita el padding del stride AVX2.
    rows5 = [[float(i + c) for c in range(5)] for i in range(3)]
    assert accel.spmm_csr_dense(ROW_PTR, COL_IDX, VALUES, rows5, 2, 5) == \
        _spmm_py(ROW_PTR, COL_IDX, VALUES, rows5, 2, 5)
    assert accel.spmm_csr_dense(ROW_PTR, COL_IDX, VALUES, B_ROWS, 2, 2) == \
        _spmm_py(ROW_PTR, COL_IDX, VALUES, B_ROWS, 2, 2)


def test_nativo_dijkstra_igual_fallback():
    if not accel.available()["field"]["loaded"]:
        pytest.skip("field nativo no disponible")
    assert accel.dijkstra(5, EDGES, 0) == _dijkstra_py(5, EDGES, 0)
    assert accel.dijkstra(5, EDGES, 3) == _dijkstra_py(5, EDGES, 3)


def test_nativo_swar_igual_fallback():
    if not accel.available()["swar"]["loaded"]:
        pytest.skip("swar nativo no disponible")
    for a, h in [(0, 0), (0xFFFFFFFFFFFFFFFF, 0), (123456789, 987654321),
                 (0xDEADBEEFCAFEBABE, 0x0123456789ABCDEF)]:
        assert accel.swar_friction(a, h) == _swar_py(a, h)


def test_available_forma():
    av = accel.available()
    assert set(av) == {"spmm", "field", "swar"}
    for v in av.values():
        assert isinstance(v["loaded"], bool)
        assert isinstance(v["reason"], str) and v["reason"]

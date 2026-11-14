"""AUTO_MVP v2.10 — innovar, probar, auditar; cuarta vuelta (4/5).

- PEEPHOLE CON CONMUTACIÓN
  (`auto_mvp/circuits/operators/commuting.py`): cancela pares
  idénticos de compuertas autoinversas que NO son adyacentes, si
  todo lo que hay entre medias actúa sobre qubits disjuntos (y
  por tanto conmuta con ellas). Búsqueda hacia atrás acotada
  (MAX_GAP, 256 por defecto desde v2.11); índice (opcode,
  operandos) -> pila para que sea O(1) buscar el par. En streaming,
  una sola pasada.
- En la semilla, el peephole con pila (v2.7) ya quita todo lo
  adyacente; el de conmutación busca lo que queda entre medias.
  (Con GAP 256, v2.11: 76 más tras el peephole, 38 pares.)
"""
from __future__ import annotations

from auto_mvp.circuit import SEED_INVSQRT
from auto_mvp.circuits.operators.commuting import (
    clean_commuting_file, commuting_clean)
from auto_mvp.circuits.operators.peephole import clean_file

TOY_CONMUTA = [
    'REGISTER r0 "x"',
    'X q1',
    'CX q2 q3',          # no toca q1: conmuta con X q1
    'CX q4 q5',          # tampoco
    'X q1',              # se cancela con la primera X
]
TOY_NO_CONMUTA = [
    'REGISTER r0 "x"',
    'X q1',
    'CX q1 q2',          # toca q1: NO conmuta, no se cancela
    'X q1',
]
TOY_ADYACENTE = [
    'REGISTER r0 "x"',
    'CX q1 q2',
    'CX q1 q2',
]


def test_commuting_cancela_par_separado():
    """Dos X separadas por CX en otros qubits se cancelan."""
    out, stats = commuting_clean(TOY_CONMUTA)
    assert stats["pairs_cancelled"] == 1
    assert stats["pairs_commuting"] == 1
    assert stats["removed"] == 2
    assert "X q1" not in out


def test_commuting_no_cancela_si_toca():
    """Si lo de en medio toca el qubit, no se cancela."""
    out, stats = commuting_clean(TOY_NO_CONMUTA)
    assert stats["pairs_cancelled"] == 0
    assert stats["removed"] == 0
    assert out.count("X q1") == 2


def test_commuting_tambien_lo_adyacente():
    """Un par adyacente también se cancela (gap 0, no es conmutación)."""
    out, stats = commuting_clean(TOY_ADYACENTE)
    assert stats["pairs_cancelled"] == 1
    assert stats["pairs_commuting"] == 0


def test_commuting_semilla(tmp_path):
    """En la semilla, tras el peephole con pila: 76 más (38 pares).

    v2.11: el GAP por defecto es 256 (antes 16, que daba 42/21).
    En la semilla el resultado satura en 256.
    """
    # Primero el peephole con pila (v2.7), luego la conmutación.
    p_out = tmp_path / "peephole.kmx"
    p_stats = clean_file(SEED_INVSQRT, p_out)
    assert p_stats["removed"] == 122
    c_out = tmp_path / "commuting.kmx"
    c_stats = clean_commuting_file(p_out, c_out)
    assert c_stats["removed"] == 76
    assert c_stats["pairs_cancelled"] == 38
    assert c_stats["pairs_commuting"] == 38  # todos por conmutación
    # Y la 2ª pasada no quita nada (idempotente).
    c2_out = tmp_path / "commuting2.kmx"
    c2_stats = clean_commuting_file(c_out, c2_out)
    assert c2_stats["removed"] == 0

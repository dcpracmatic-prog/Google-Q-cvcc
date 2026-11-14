"""AUTO_MVP v2.4 — la herramienta, con lo que sirve de lo revisado.

- PEEPHOLE (la ruta Fast de GUOQ, bien hecha): sobre el .kmx REAL
  de kickmix, con reescrituras exactas. En la semilla invsqrt quita
  122 compuertas Clifford (56 pares CX + 5 X) en una sola pasada
  con pila (v2.7: la pasada con una sola pendiente solo quitaba 44)
  y el S medido NO cambia (las Clifford no cuentan en C); la
  validez la confirma el verificador oficial. Integrado como
  pre-paso determinista del operador sa_windows.
- DIALOG (el acceso implícito, bien hecho): la traza algebraica
  (cocientes del EEA) + playback reconstruyen los coeficientes de
  Bézout sin haberlos guardado. 200/200 casos aleatorios: el
  playback es idéntico al EEA explícito, y sigma·S = omega
  (mod z^2l) en la ecuación clave. Los scripts v1-v3 NO implementan
  esto: su "Dialog" es un playback de vector de estado con matrices
  2x2 que no representan las compuertas de varios qubits.
"""
from __future__ import annotations

import random
from pathlib import Path

import pytest

from auto_mvp.circuit import SEED_INVSQRT, fast_verify_invsqrt, propose_sa_windows
from auto_mvp.circuits.dialog import (
    deg, dialog_bezout, eea_explicit, pmul)
from auto_mvp.circuits.operators.peephole import clean_file, peephole_clean

TOY = ['REGISTER r0 "x"',
       'X q0', 'X q0',
       'CX q0 q1', 'CX q0 q1',
       'Z_POW q2 0.25', 'Z_POW q2 0.75',
       'Z_POW q3 1.0', 'Z_POW q3 1.0',
       'H q4', 'H q4',
       'CCX q0 q1 q2', 'CCX q0 q1 q2',
       'X q5', 'PUSH_CONDITION if b1', 'X q5', 'X q5', 'POP_CONDITION',
       'CX q0 q1', 'CX q1 q0']


def test_peephole_juguete_exactitud():
    """Fusiones y cancelaciones exactas, sin tocar lo que no debe."""
    cleaned, stats = peephole_clean(TOY)
    assert stats == {"removed": 12, "zpow_fused": 1, "zpow_removed": 2,
                     "pairs_cancelled": 5}
    assert cleaned == ['REGISTER r0 "x"',
                       'Z_POW q2 1.0',
                       'X q5',
                       'PUSH_CONDITION if b1', 'POP_CONDITION',
                       'CX q0 q1', 'CX q1 q0']
    # Idempotente: una segunda pasada no encuentra nada.
    cleaned2, stats2 = peephole_clean(cleaned)
    assert stats2 == {"removed": 0, "zpow_fused": 0, "zpow_removed": 0,
                      "pairs_cancelled": 0}
    assert cleaned2 == cleaned


def test_peephole_semilla_real_122_clifford_s_igual(tmp_path: Path):
    """La semilla invsqrt: 122 Clifford menos (56 CX + 5 X), S idéntico."""
    out = tmp_path / "clean.kmx"
    stats = clean_file(SEED_INVSQRT, out)
    assert stats["removed"] == 122
    assert stats["pairs_cancelled"] == 61
    assert stats["zpow_fused"] == 0
    m_clean = fast_verify_invsqrt(str(out), max_x=1024)
    m_orig = fast_verify_invsqrt(str(SEED_INVSQRT), max_x=1024)
    assert m_clean["valid"] and m_orig["valid"]
    assert m_clean["S"] == m_orig["S"]


def test_propose_sa_windows_con_peephole(tmp_path: Path):
    """El operador lleva el pre-paso y lo reporta; la semilla sigue óptima."""
    out = tmp_path / "cand.kmx"
    log = tmp_path / "cand.json"
    prop = propose_sa_windows(SEED_INVSQRT, out, log, K=5, budget_s=5,
                              seed=1)
    assert prop["ok"] and prop["gain"] == 0
    assert prop["peephole"]["removed"] == 122
    assert prop["peephole"]["pairs_cancelled"] == 61
    assert out.is_file()
    # El candidato es la semilla limpia: 122 líneas menos.
    n_out = len(out.read_text(encoding="utf-8").split("\n"))
    n_in = len(Path(SEED_INVSQRT).read_text(encoding="utf-8").split("\n"))
    assert n_out == n_in - 122


def test_dialog_playback_igual_al_eea_explicito():
    """200 casos aleatorios: la traza reconstruye los Bézout exactos."""
    random.seed(1234)
    for _ in range(200):
        a = random.getrandbits(random.randint(1, 12)) | 1
        b = random.getrandbits(random.randint(1, 12)) | 1
        r, s, t, steps = eea_explicit(a, b)
        r2, s2, t2, trace = dialog_bezout(a, b)
        assert (r, s, t) == (r2, s2, t2)
        assert pmul(s, a) ^ pmul(t, b) == r
        assert len(trace) == steps
        # Ecuación clave de DQI: a = z^{2l}, b = S(z), parar en deg < l.
        l = 4
        S = random.getrandbits(2 * l - 1) | 1
        rk, sk, tk, _ = eea_explicit(1 << (2 * l), S, stop_degree=l)
        rk2, sk2, tk2, _ = dialog_bezout(1 << (2 * l), S, stop_degree=l)
        assert (rk, sk, tk) == (rk2, sk2, tk2)
        assert deg(rk) < l
        # sigma es t (el coeficiente de S): t*S = omega (mod z^{2l}).
        assert pmul(tk, S) & ((1 << (2 * l)) - 1) == rk


def test_dialog_no_es_el_de_los_scripts():
    """La traza Dialog es algebraica (cocientes), no un vector de estado."""
    # Un caso donde el EEA tiene varios pasos: la traza guarda los
    # cocientes, no los coeficientes; el playback los reconstruye.
    a = 0b101101101011
    b = 0b110101101
    r, s, t, steps = eea_explicit(a, b)
    r2, s2, t2, trace = dialog_bezout(a, b)
    assert steps == len(trace) >= 2
    assert (r, s, t) == (r2, s2, t2)
    assert all(isinstance(q, int) and q > 0 for q in trace)

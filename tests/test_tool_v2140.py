"""AUTO_MVP v2.14 — los pases dejan de limpiar Clifford y apuntan a
lo que cobra el S (pedido de Arturo, 2026-11-14).

- rotation_merge: una Z_POW en los CONTROLES de un CCX pasa sin
  vaciar (la Z en el control conmuta con el Toffoli); solo el
  objetivo vacía. Igual el control de un CSWAP. Antes se vaciaban
  los tres y se perdían fusiones que bajan el T-count.
- commuting: para un par CCX, una intermedia puede quedarse si
  CONMUTA con el Toffoli aunque toque sus controles (diagonal en
  controles, CX con control en a/b, otro Toffoli compatible). Una
  diagonal o CX que toque el objetivo c sigue bloqueando. Busca la
  cancelación de Toffolis en el sumador/multiplicador del DQI.
- Modelo cobrable (cost_models/chargeable.py): la regla de cobro
  del verificador (Clifford 0, ángulo T 1, otro ángulo
  rotation_t_cost(eps); CCX/CSWAP 1 Toffoli). El benchmark reporta
  delta_t y delta_toffoli con el T-count exacto del verificador.
- SA: la aceptación es solo por baja estricta de Toffoli,
  verificada en el archivo de salida (no solo en el log); la
  reducción de instrucciones totales o Clifford no cuenta.
"""
from __future__ import annotations

from pathlib import Path

from auto_mvp.benchmark import benchmark
from auto_mvp.circuit import (SEED_INVSQRT, fast_verify_invsqrt,
                              propose_sa_windows)
from auto_mvp.circuits.cost_models.chargeable import (
    count_chargeable, rotation_t_cost, zpow_t_cost)
from auto_mvp.circuits.operators.commuting import commuting_clean
from auto_mvp.circuits.operators.rotation_merge import rotation_merge

SEED_S = 100585.37325984969
SEED_T = 1186.3632949903022  # T-count exacto del verificador (semilla).


def test_chargeable_clasifica_angulos():
    """Clifford 0, ángulo T 1, otro ángulo el coste de síntesis."""
    assert zpow_t_cost("0") == 0.0
    assert zpow_t_cost("0.5") == 0.0
    assert zpow_t_cost("1.0") == 0.0
    assert zpow_t_cost("0.25") == 1.0
    assert zpow_t_cost("0.75") == 1.0
    assert zpow_t_cost("1.75") == 1.0
    assert zpow_t_cost("-0.25") == 1.0
    assert zpow_t_cost("0.1") == rotation_t_cost(2.0 ** -24)
    assert abs(rotation_t_cost(2.0 ** -24) - 18.74) < 1e-9


def test_chargeable_cuenta_toffoli_y_t():
    """CCX/CSWAP son 1 Toffoli; Z_POW cobra según su ángulo."""
    lines = ["Z_POW q0 0.25", "Z_POW q1 0.5", "CCX q0 q1 q2",
             "CSWAP q0 q1 q2", "CX q0 q1", "X q0", "Z_POW q2 0.1"]
    c = count_chargeable(lines)
    assert c["toffoli"] == 2
    assert c["t"] == 1.0 + rotation_t_cost(2.0 ** -24)
    assert c["clifford"] == 2
    assert c["total"] == 7


def test_rotation_merge_ccx_control_fusiona_y_objetivo_no():
    """Z_POW en control de CCX pasa y fusiona (ahorra 2 T); en el
    objetivo no (X y Z no conmutan)."""
    out, st = rotation_merge(["Z_POW q0 0.25", "CCX q0 q1 q2",
                              "Z_POW q0 0.25", "X q3"])
    assert st["merged"] == 1
    assert out == ["CCX q0 q1 q2", "X q3", "Z_POW q0 0.5"]
    assert count_chargeable(out)["t"] == 0.0
    out2, st2 = rotation_merge(["Z_POW q2 0.25", "CCX q0 q1 q2",
                                "Z_POW q2 0.25", "X q3"])
    assert st2["merged"] == 0
    assert out2[0] == "Z_POW q2 0.25"


def test_rotation_merge_cswap_control_fusiona_y_intercambio_no():
    """Z_POW en el control de CSWAP pasa y fusiona; en un qubit
    intercambiado no (la Z se mueve con el qubit)."""
    out, st = rotation_merge(["Z_POW q0 0.25", "CSWAP q0 q1 q2",
                              "Z_POW q0 0.25", "X q3"])
    assert st["merged"] == 1
    assert out[-1] == "Z_POW q0 0.5"
    out2, st2 = rotation_merge(["Z_POW q1 0.25", "CSWAP q0 q1 q2",
                                "Z_POW q1 0.25", "X q3"])
    assert st2["merged"] == 0


def test_commuting_toffoli_diagonal_en_control_cancela():
    """Un par CCX separado por una diagonal en un control cancela;
    por una diagonal en el objetivo, no."""
    out, st = commuting_clean(["CCX q0 q1 q2", "Z q0", "CCX q0 q1 q2"])
    assert st["toffoli_pairs_cancelled"] == 1
    assert out == ["Z q0"]
    out2, st2 = commuting_clean(["CCX q0 q1 q2", "Z q2", "CCX q0 q1 q2"])
    assert st2["toffoli_pairs_cancelled"] == 0
    assert len(out2) == 3


def test_commuting_toffoli_cx_compatible_cancela():
    """Un par CCX separado por una CX con control en a/b cancela;
    por una CX que escribe en un control, no."""
    out, st = commuting_clean(["CCX q0 q1 q2", "CX q0 q3",
                               "CCX q0 q1 q2"])
    assert st["toffoli_pairs_cancelled"] == 1
    assert out == ["CX q0 q3"]
    out2, st2 = commuting_clean(["CCX q0 q1 q2", "CX q3 q0",
                                 "CCX q0 q1 q2"])
    assert st2["toffoli_pairs_cancelled"] == 0


def test_commuting_toffoli_otro_toffoli_compatible_cancela():
    """Un par CCX separado por otro Toffoli compatible cancela; si
    el objetivo del otro es control del par, no."""
    out, st = commuting_clean(["CCX q0 q1 q2", "CCX q0 q1 q3",
                               "CCX q0 q1 q2"])
    assert st["toffoli_pairs_cancelled"] == 1
    assert out == ["CCX q0 q1 q3"]
    out2, st2 = commuting_clean(["CCX q0 q1 q2", "CCX q3 q4 q0",
                                 "CCX q0 q1 q2"])
    assert st2["toffoli_pairs_cancelled"] == 0


def test_benchmark_semilla_reporta_t_y_toffoli():
    """El benchmark de la semilla reporta el T-count exacto del
    verificador y delta_t/delta_toffoli = 0 (ningún operador toca
    lo cobrable en la semilla)."""
    rep = benchmark(SEED_INVSQRT, work_dir="/tmp/bench_v214_test",
                    run_sa=False, task="invsqrt")
    assert abs(rep["base_t"] - SEED_T) < 1e-6
    assert rep["base_S"] == SEED_S
    for name in ("peephole", "rotation_merge", "commuting"):
        op = rep["operators"][name]
        assert op["valid"] is True
        assert op["delta_S"] == 0.0
        assert op["delta_toffoli"] == 0
        assert op["delta_t"] == 0.0
    assert rep["operators"]["commuting"]["stats"]["toffoli_pairs_cancelled"] == 0


def test_sa_aceptacion_no_rechaza_falso_en_semilla(tmp_path: Path):
    """propose_sa_windows en la semilla: el SA no encuentra nada
    (gain 0) y la verificación independiente no lo rechaza como
    falso (ok=True, gain=0)."""
    out = tmp_path / "sa.kmx"
    log = tmp_path / "sa.json"
    prop = propose_sa_windows(SEED_INVSQRT, out, log, K=5,
                              budget_s=5.0, seed=1)
    assert prop["ok"] is True
    assert prop["gain"] == 0
    m = fast_verify_invsqrt(out, max_x=1024)
    assert m["valid"] is True
    assert m["S"] == SEED_S

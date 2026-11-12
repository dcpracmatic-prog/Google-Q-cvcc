"""AUTO_MVP v2.0 — circuitos válidos, medidos. DIRECTIVA v2.0 de Arturo.

Proponer un circuito real, validarlo con el protocolo oficial (si no
es válido, no cuenta), medirlo simulando, guardar el mejor CON SU
.CIRCUITO, y repetir hasta la meta o hasta que se cancele el script.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from auto_mvp.circuit import (SEED_INVSQRT, fast_verify_invsqrt,
                              propose_sa_windows, static_count)
from auto_mvp.circuit_auto import run_circuit_auto

CERTIFIED_S = 100568.5


def test_static_count_seed():
    st = static_count(SEED_INVSQRT)
    assert st["qubits"] == 62
    assert st["toffoli_like"] == 1495
    assert st["registers"] == 1


def test_fast_verify_seed_matches_certified():
    m = fast_verify_invsqrt(SEED_INVSQRT, max_x=1024, shots_per_x=1)
    assert m["valid"] is True
    assert abs(m["S"] - CERTIFIED_S) / CERTIFIED_S < 0.01
    assert abs(m["toffoli_count"] - 1325.48) / 1325.48 < 0.01
    assert m["qubits"] == 62


def test_invalid_circuit_truncated(tmp_path):
    bad = tmp_path / "bad.kmx"
    data = SEED_INVSQRT.read_bytes()
    bad.write_bytes(data[: len(data) // 2])
    m = fast_verify_invsqrt(bad, max_x=256)
    assert m["valid"] is False
    assert m["S"] is None
    assert m["reason"]


def test_invalid_circuit_gate_flip(tmp_path):
    # Cambiar el objetivo de un CCX por otro cúbit: el circuito deja
    # de calcular 1/sqrt(x) y la verificación oficial lo rechaza.
    lines = SEED_INVSQRT.read_text(encoding="utf-8").splitlines()
    idx = next(i for i, l in enumerate(lines)
               if l.strip().startswith("CCX"))
    parts = lines[idx].split()
    assert len(parts) == 4  # CCX control control objetivo
    parts[3] = "q0" if parts[3] != "q0" else "q1"
    lines[idx] = " ".join(parts)
    bad = tmp_path / "flipped.kmx"
    bad.write_text("\n".join(lines), encoding="utf-8")
    m = fast_verify_invsqrt(bad, max_x=256)
    assert m["valid"] is False
    assert m["S"] is None
    assert m["reason"]


def test_propose_sa_windows_tiny_budget(tmp_path):
    out = tmp_path / "cand.kmx"
    log = tmp_path / "cand.json"
    prop = propose_sa_windows(SEED_INVSQRT, out, log, K=5, budget_s=5,
                              seed=1)
    assert prop["ok"] is True
    assert out.is_file() and log.is_file()
    m = fast_verify_invsqrt(out, max_x=256)
    assert m["valid"] is True
    assert m["S"] is not None


def test_runner_two_proposals(tmp_path):
    res = run_circuit_auto(90000.0, runs_dir=tmp_path / "runs",
                           max_proposals=2, sa_budget_s=5, seed=7)
    assert res["reached"] is False
    assert res["proposals"] == 2
    assert abs(res["best_S"] - CERTIFIED_S) / CERTIFIED_S < 0.01
    best = Path(res["best_circuit"])
    assert best.is_file()
    m = fast_verify_invsqrt(best, max_x=256)
    assert m["valid"] is True
    led = json.loads((tmp_path / "runs" / "circuit_ledger.json")
                     .read_text(encoding="utf-8"))
    assert led["best"]["S"] == res["best_S"]
    assert led["proposals"] == 2

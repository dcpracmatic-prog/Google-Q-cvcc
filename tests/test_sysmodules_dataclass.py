"""Regresion del bug sys.modules/dataclasses (v2.17.24).

El bug: cargar verify_submission_invsqrt.py con spec_from_file_location +
module_from_spec + exec_module SIN registrar en sys.modules falla con
AttributeError: 'NoneType' object has no attribute '__dict__', porque
dataclasses._is_type (3.12) hace sys.modules.get(cls.__module__).__dict__
y la clase ProblemSpecInvSqrt tiene __module__ == nombre del spec.
Medido en kernels R14 DQI y F3 I1; reproducido en sandbox (venv 3.12).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from auto_mvp.module_loading import load_module_from_path
from auto_mvp.notebook import _MODULE_CELL

REPO = Path(__file__).resolve().parents[1]
VENDORED = (REPO / "auto_mvp" / "circuits" / "verifiers"
            / "verify_submission_invsqrt.py")
SANDBOX = Path("/home/hatch/workspace/sandbox-run/competition-verifiers"
               "/invsqrt/verify_submission_invsqrt.py")


def _verifier_path() -> Path:
    return VENDORED if VENDORED.is_file() else SANDBOX


def test_old_pattern_fails_without_sys_modules_registration(tmp_path):
    """El patron viejo (sin registrar) falla con el AttributeError exacto."""
    if not _verifier_path().is_file():
        raise SystemExit(f"sin verificador invsqrt en {_verifier_path()}")
    code = (
        "import importlib.util, sys, traceback\n"
        f"spec = importlib.util.spec_from_file_location('verify_invsqrt', {str(_verifier_path())!r})\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "try:\n"
        "    spec.loader.exec_module(mod)\n"
        "    print(json.dumps({'failed': False}))\n"
        "except AttributeError as e:\n"
        "    tb = traceback.format_exc()\n"
        "    print(json.dumps({'failed': True, 'error': str(e),\n"
        "                      'dataclasses': 'dataclasses' in tb,\n"
        "                      'none_dict': \"'NoneType' object has no attribute '__dict__'\" in tb}))\n"
    )
    r = subprocess.run([sys.executable, "-c", code],
                       capture_output=True, text=True, timeout=300)
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["failed"] is True, "el patron viejo ya no falla: el bug cambio"
    assert out["dataclasses"] is True
    assert out["none_dict"] is True


def test_load_module_from_path_loads_official_invsqrt_verifier():
    """El helper carga el verificador y ProblemSpecInvSqrt funciona."""
    mod = load_module_from_path("verify_invsqrt_test", str(_verifier_path()))
    assert sys.modules["verify_invsqrt_test"] is mod
    p = mod.ProblemSpecInvSqrt.for_n_p(10, shots_per_x=1)
    assert p.max_x == 3_133_452
    assert p.num_shots == 3_133_452


def test_notebook_module_cell_registers_before_exec():
    """La plantilla de notebook registra en sys.modules antes de exec_module."""
    assert 'sys.modules["module___TASK__"] = _MOD' in _MODULE_CELL
    reg = _MODULE_CELL.index('sys.modules["module___TASK__"] = _MOD')
    exe = _MODULE_CELL.index("_SPEC.loader.exec_module(_MOD)")
    assert reg < exe, "el registro debe ir ANTES de exec_module"

"""Regresion del bug sys.modules/dataclasses (v2.17.25).

El bug: cargar verify_submission_invsqrt.py con spec_from_file_location +
module_from_spec + exec_module SIN registrar en sys.modules falla con
AttributeError: 'NoneType' object has no attribute '__dict__', porque
dataclasses._is_type (3.12) hace sys.modules.get(cls.__module__).__dict__
y la clase ProblemSpecInvSqrt tiene __module__ == nombre del spec.
Medido en kernels R14 DQI y F3 I1; reproducido en sandbox (venv 3.12).

v2.17.25 — arreglo del HARNESS (el helper load_module_from_path no se toca):
- el snippet -c usaba json.dumps sin importar json: el NameError dejaba el
  stdout vacio y el test moria con IndexError en la linea 50 (validacion
  v2.17.24 v4: 375 passed, 1 failed). Ahora el snippet importa json.
- el subproceso recibe PYTHONPATH explicito con el directorio del kickmix
  bueno (mismo patron que F3 y que la celda 3 del notebook de validacion),
  para que el verificador importe el kickmix con GF2Field y no el de pip.
- si el subproceso no imprime JSON, el fallo muestra su stderr en vez de
  un IndexError mudo.
"""
from __future__ import annotations

import importlib.util
import json
import os
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


def _kickmix_dir() -> str | None:
    """Directorio del kickmix importable en este proceso (el bueno, con GF2Field).

    Mismo criterio que la celda 3 del notebook de validacion: si es un .so,
    su directorio; si es un paquete, el directorio padre.
    """
    try:
        spec = importlib.util.find_spec("kickmix")
    except Exception:
        return None
    if spec is None or not spec.origin:
        return None
    km_file = Path(spec.origin).resolve()
    if km_file.suffix == ".so":
        return str(km_file.parent)
    if km_file.parent.name == "kickmix":
        return str(km_file.parent.parent)
    return str(km_file.parent)


def _subprocess_env() -> dict:
    """Env para el subproceso: hereda os.environ + PYTHONPATH con el kickmix bueno."""
    env = dict(os.environ)
    km_dir = _kickmix_dir()
    if km_dir:
        pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join([km_dir, pp]) if pp else km_dir
    return env


def test_old_pattern_fails_without_sys_modules_registration(tmp_path):
    """El patron viejo (sin registrar) falla con el AttributeError exacto."""
    if not _verifier_path().is_file():
        raise SystemExit(f"sin verificador invsqrt en {_verifier_path()}")
    code = (
        "import importlib.util, sys, traceback, json\n"
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
                       capture_output=True, text=True, timeout=300,
                       env=_subprocess_env())
    lines = r.stdout.strip().splitlines()
    assert lines, (
        f"el subproceso no imprimio JSON (rc={r.returncode}):\n{r.stderr[-2000:]}"
    )
    out = json.loads(lines[-1])
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

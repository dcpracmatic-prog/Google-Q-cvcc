"""Carga de modulos .py por ruta, con registro en sys.modules.

CAUSA RAIZ (bug medido 2026-11-20/21, kernels R14 DQI y F3 I1):
cargar un modulo con spec_from_file_location + module_from_spec +
exec_module SIN registrarlo antes en sys.modules falla cuando el modulo
usa @dataclasses.dataclass con `from __future__ import annotations`
(como verify_submission_invsqrt.py): dataclasses._is_type (CPython 3.12)
hace sys.modules.get(cls.__module__).__dict__, y .get() devuelve None
porque el modulo nunca se registro -> AttributeError: 'NoneType' object
has no attribute '__dict__'. Como CLI (__main__) no falla porque
sys.modules["__main__"] si existe.

Regla: TODA carga dinamica por ruta en este repo pasa por
load_module_from_path. Nunca spec.loader.exec_module sin registrar antes.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_module_from_path(name: str, path: str | Path):
    """Carga el .py de `path` como modulo `name` y lo devuelve.

    Registra el modulo en sys.modules ANTES de exec_module (el arreglo
    del bug sys.modules/dataclasses). Sobrescribe cualquier entrada
    previa con el mismo nombre (incluida una entrada None dejada por
    una carga fallida anterior).
    """
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"no se puede cargar {path} como modulo {name!r}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # <-- EL ARREGLO: registrar antes de exec_module
    spec.loader.exec_module(mod)
    return mod

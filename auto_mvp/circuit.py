"""AUTO_MVP v2.0 — circuitos, no números.

La DIRECTIVA v2.0 de Arturo (2026-11-11 23:47 CST): el motor es fuerza
bruta sobre CIRCUITOS. Propone circuitos VÁLIDOS (que se pueda
construir algo con ellos); si no es válido, no cuenta, no es nada.
El circuito válido se produce PRIMERO y DESPUÉS se mide; de ahí se
define si pasa o no; si no pasa, se repite, hasta que se cancele el
script o se llegue a la meta. Sin límite de tiempo impuesto.

Este módulo son las primitivas de ese motor:

- Cargar un circuito (.kmx/.kmb) con kickmix.
- Contar estático (proxy rápido de ranking, no es la medida).
- Verificación RÁPIDA con el protocolo OFICIAL del verificador
  (mismo chequeo, menos shots): registro x de 22 cúbits, scratch a
  |0>, x restaurado, error de fase dentro de tolerancia, y el costo
  MEDIDO por shot (Toffolis medios + síntesis de rotaciones).
  Si algo falla, el circuito es INVÁLIDO y no cuenta.
- Proponer un candidato con sa_windows (el operador real de Arturo):
  reescribe ventanas con menos Toffolis solo si la permutación es
  idéntica sobre los 2^k estados.

Necesita kickmix + numpy en el entorno (vienen del dataset de la
competencia y del entorno; si faltan, se dice así, nunca se finge).
El resto del repo (v1.x, números) sigue siendo solo stdlib.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_CIRCUITS = _HERE / "circuits"
SEED_INVSQRT = _CIRCUITS / "seeds" / "invsqrt_pub.kmx"
SA_WINDOWS = _CIRCUITS / "operators" / "sa_windows.py"
VERIFIER_INVSQRT = (_CIRCUITS / "verifiers"
                    / "verify_submission_invsqrt.py")

# El S certificado de la semilla (verificador oficial, 200M shots).
# La verificación rápida lo reproduce dentro del ~0.1%.
SEED_INVSQRT_S = 100568.5


def _require_kickmix():
    """kickmix, o un error claro de entorno (no un candidato inválido)."""
    try:
        import kickmix as km
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "kickmix no disponible en este entorno: el motor de "
            "circuitos necesita el kickmix del dataset de la competencia"
            f" ({exc})") from exc
    return km


def _load_verifier():
    """El verificador oficial vendido en el repo, como módulo."""
    try:
        import numpy  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "numpy no disponible en este entorno: el verificador "
            f"oficial lo necesita ({exc})") from exc
    _require_kickmix()
    spec = importlib.util.spec_from_file_location(
        "verify_submission_invsqrt", str(VERIFIER_INVSQRT))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"no se puede cargar {VERIFIER_INVSQRT}")
    mod = importlib.util.module_from_spec(spec)
    # El verificador usa @dataclasses.dataclass: la clase se crea
    # buscando su módulo en sys.modules; sin registrarlo antes, el
    # decorador falla con AttributeError.
    sys.modules["verify_submission_invsqrt"] = mod
    spec.loader.exec_module(mod)
    return mod


def load_circuit(path: str | Path):
    """Carga un .kmx/.kmb con kickmix. Falla si no es un circuito."""
    km = _require_kickmix()
    return km.Circuit.from_file(str(path), format="auto")


def static_count(path: str | Path) -> dict[str, Any]:
    """Conteo estático del circuito (proxy rápido, NO es la medida).

    El conteo estático es el máximo por shot; la medida real es la
    media por shot simulado (fast_verify_invsqrt). Sirve para ordenar
    candidatos antes de medirlos, nada más.
    """
    c = load_circuit(path)
    st = c.operation_statistics()
    return {
        "qubits": int(c.num_qubits),
        "bits": int(c.num_bits),
        "registers": int(c.num_registers),
        "instructions": int(st.num_instructions),
        "toffoli_like": int(st.num_toffoli_like),
        "t_like": int(st.num_t_like),
    }


def fast_verify_invsqrt(path: str | Path, *, max_x: int = 1024,
                        shots_per_x: int = 1, seed: int = 1,
                        batch_size: int = 256) -> dict[str, Any]:
    """Verificación RÁPIDA de un circuito invsqrt, protocolo oficial.

    Misma validez y mismo costo que el verificador oficial, con menos
    shots (max_x valores de x, shots_per_x por valor). La semilla
    medida da S ≈ 100,568.5 (certificado 100,568.5, 200M shots).
    Si el circuito no es válido (registro, scratch, x restaurado,
    fase), ``valid`` es False y ``reason`` dice por qué: no cuenta.
    """
    mod = _load_verifier()
    try:
        circuit = load_circuit(path)
    except Exception as exc:  # noqa: BLE001 - no es un circuito
        return {"valid": False, "S": None, "reason": f"no carga: {exc}"[:300]}
    spec = mod.ProblemSpecInvSqrt(
        width=22, max_x=int(max_x), beta=Fraction(1), precision_bits=24,
        shots_per_x=int(shots_per_x), system_qubits=3 * 218 * 10)
    try:
        res = mod.verify(circuit, spec, seed=int(seed),
                         batch_size=int(batch_size), max_workers=1)
    except (AssertionError, ValueError) as exc:
        return {"valid": False, "S": None, "reason": str(exc)[:300]}
    return {
        "valid": True,
        "S": float(res["score"]),
        "toffoli_count": float(res["toffoli_count"]),
        "t_base": float(res["t_count"]),
        "rotation_count": float(res["rotation_count"]),
        "toffoli_equivalent": float(res["toffoli_equivalent"]),
        "qubits": int(circuit.num_qubits),
        "verified_shots": int(res["verified_shots"]),
        "worst_error_over_tolerance": float(res["worst_error_over_tolerance"]),
        "reason": "",
    }


def propose_sa_windows(seed_path: str | Path, out_path: str | Path,
                       log_path: str | Path, *, K: int = 5,
                       budget_s: float = 60.0, seed: int = 1
                       ) -> dict[str, Any]:
    """Un candidato real con sa_windows (el operador de Arturo).

    Reescribe ventanas del circuito con menos Toffolis, solo si la
    permutación es idéntica sobre los 2^k estados. Devuelve si el
    operador corrió y la ganancia que reporta su log (0 si no encontró
    nada: la semilla ya es óptima para esas ventanas, y eso también
    es un resultado medido, no un fallo).
    """
    cmd = [sys.executable, str(SA_WINDOWS), str(seed_path), str(out_path),
           str(log_path), str(int(K)), str(float(budget_s)), str(int(seed))]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=float(budget_s) + 180)
    except subprocess.TimeoutExpired:
        return {"ok": False, "gain": 0, "reason": "sa_windows excedió su tiempo"}
    if proc.returncode != 0:
        return {"ok": False, "gain": 0,
                "reason": (proc.stderr or proc.stdout or "sa_windows falló")[:300]}
    gain = 0
    try:
        gain = int(json.loads(Path(log_path).read_text(
            encoding="utf-8")).get("gain_total", 0))
    except Exception:
        gain = 0
    return {"ok": True, "gain": gain, "reason": ""}

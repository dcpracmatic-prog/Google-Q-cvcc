"""Harness VQCC de búsqueda local — v0.2.1-vqcc.

Reorientación del paquete self-healing v0.1.0: ya no vigila endpoints
HTTP, vigila la calidad y validez de los circuitos generados.

- contracts: CircuitSpec por tarea, umbrales oficiales.
- costs: S = Q*C (invsqrt), R*Q^2*T (DQI), lambda_eff*T*Q (química).
- detect: CircuitDetector — invariantes rotas + estancamiento.
- verify: LocalVerifier — verificador oficial en local (química Task 1
  completa; invsqrt/DQI .kmb solo si se pide, son caros).
- ledger: VQCCLedger — JSONL: mutación, S, PASS oficial, aceptado.
- search: SearchLoop — motor de búsqueda autónomo con rollback.
- calibrate (v0.2.1): calibración de arranque estilo DSP — la sonda
  mide el vecindario del baseline y deriva el margen de aceptación,
  la paciencia y el presupuesto de intentos. El detector usa mediana
  móvil y firma de salud; el lazo baja AUTO->PROPOSE->SHADOW por veto.
"""
from auto_mvp.healing.heal import Autonomy

from .calibrate import (
    Calibration, calibrate, calibrate_from_candidates,
    clear_calibration_cache, extract_signature,
)
from .contracts import (
    BEST_GLOBAL_SCORE, BEST_OWN_S, REFERENCE_S,
    CircuitSpec, dfthcsos_spec, dqi_spec, invsqrt_spec,
)
from .costs import (
    beats_best_global, geometric_score, ratio,
    repetition_overhead, s_chem, s_dqi, s_invsqrt,
)
from .detect import CircuitDetector
from .ledger import VQCCLedger
from .search import Mutator, SearchLoop, SearchResult
from .verify import CircuitVerifyResult, LocalVerifier, verify_candidate

__version__ = "0.2.1-vqcc"

__all__ = [
    "Autonomy",
    "Calibration", "calibrate", "calibrate_from_candidates",
    "clear_calibration_cache", "extract_signature",
    "BEST_GLOBAL_SCORE", "BEST_OWN_S", "REFERENCE_S",
    "CircuitSpec", "dfthcsos_spec", "dqi_spec", "invsqrt_spec",
    "beats_best_global", "geometric_score", "ratio",
    "repetition_overhead", "s_chem", "s_dqi", "s_invsqrt",
    "CircuitDetector", "VQCCLedger",
    "Mutator", "SearchLoop", "SearchResult",
    "CircuitVerifyResult", "LocalVerifier", "verify_candidate",
]

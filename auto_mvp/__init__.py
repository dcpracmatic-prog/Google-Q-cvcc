"""AUTO_MVP v0.3.0 — núcleo autónomo de optimización para VQCC.

Construye sobre el corrector v0.2.1-vqcc (auto_mvp.vqcc) y el paquete
genérico de auto-reparación v0.1.0 (auto_mvp.healing), y añade lo
concreto de la especificación AUTO_MVP v0.0.1 de Arturo:

- integrity: filtro de integridad obligatorio (sigma, C/B, dreg,
  alpha, temporales) + guardia que envuelve la construcción.
- cvv: bitácora con cadena de hashes (tamper-evident, no firma).
- checkpoint: checkpoint atómico inmediato de cada mejor verificado.
- goal: meta porcentual con regla de paro y presupuesto adaptativo.
- proxy: evaluación proxy en el espacio de metadatos (prefiltro
  antes de construir; el validador como filtro de entrada).
- mvp: orquestador del ciclo de 5 fases.

El mérito de aceptación es siempre el S OFICIAL. La suma ponderada
de la spec solo existe como proxy_merit (ranking, nunca aceptación).
"""
from .cache import VerificationCache, verify_with_cache
from .checkpoint import Checkpoint
from .cvv import CvvChain, CvvRecord, GENESIS_PREV
from .gf212 import DEG as GF212_DEG
from .gf212 import MOD as GF212_MOD
from .gf212 import monic as gf212_monic
from .goal import Goal, GoalState, GoalTracker
from .integrity import (CircuitConstructionGuard, IntegrityEvidence,
                        IntegrityFilter, IntegrityViolation, canonical_hash,
                        monic_sigma, sigma_scale_factor)
from .mvp import AutoMvp, MvpResult
from .proxy import (CandidateMeta, MetadataProxy, ProxyVerdict,
                    calibrate_proxy, estimate_S, proxy_merit)

__version__ = "0.3.1"

__all__ = [
    "Checkpoint",
    "CvvChain", "CvvRecord", "GENESIS_PREV",
    "VerificationCache", "verify_with_cache",
    "GF212_MOD", "GF212_DEG", "gf212_monic",
    "Goal", "GoalState", "GoalTracker",
    "CircuitConstructionGuard", "IntegrityEvidence",
    "IntegrityFilter", "IntegrityViolation", "canonical_hash",
    "monic_sigma", "sigma_scale_factor",
    "AutoMvp", "MvpResult",
    "CandidateMeta", "MetadataProxy", "ProxyVerdict",
    "calibrate_proxy", "estimate_S", "proxy_merit",
    "__version__",
]

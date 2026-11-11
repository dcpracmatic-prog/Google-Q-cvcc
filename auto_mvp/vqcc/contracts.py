"""Contratos estrictos de la competencia VQCC (reorientación de spec.py).

Antes spec.py definía el contrato de una función Python cualquiera.
Ahora define el contrato de un circuito / factorización por tarea,
con los umbrales exactos del verificador oficial. Nada de HTTP.

Fuentes (verificadas en el workspace):
- invsqrt: workspace/sandbox-run/competition-verifiers/invsqrt/verify_submission_invsqrt.py
  tol(x) = 2^-24 * beta / sqrt(x), x en [1, 3_133_452], width 22, beta=1,
  S = Q * C, C = Toffoli + T/4.
- DQI: workspace/sandbox-run/competition-verifiers/dqi/verify_submission_dqi.py
  m=4095, n=70, grado 12, r=2016, eps+ < 1/16 (Clopper-Pearson, log2_delta=-128),
  S = R(eps+) * Q^2 * T, R = ln2 / -ln(1/2 + 2*sqrt(eps)).
- Química: workspace/sandbox-run/starter-kit/starter_kit/verifier/score.py
  error_1 y error_2 <= 20 mHa, Lambda > 49.0, E_gap > 3.914898,
  cada Angles_k <= 128 qubits, S = lambda_eff * Ttot * Qtot.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# --- Umbrales oficiales (no se inventan, se copian del verificador) ---

INVSQRT_PRECISION_BITS = 24
INVSQRT_MAX_X = 3_133_452
INVSQRT_WIDTH = 22
INVSQRT_BETA = 1

DQI_M, DQI_N, DQI_DEGREE, DQI_R = 4095, 70, 12, 2016
DQI_EPS_PLUS_MAX = 1 / 16
DQI_LOG2_DELTA = -128.0

CHEM_ERROR_MAX_MHA = 20.0
CHEM_LAMBDA_FLOOR = 49.0
CHEM_E_GAP_FLOOR = 3.914898
CHEM_QUBIT_CAP = 128

# --- Costos de referencia (S_ref, puntúan 1.0) y mejor propio medido ---

# invsqrt ref: Q=260, 7,735 Toffolis, 37 rotaciones -> S=2,076,774
# propio certificado: Q=62, S=100,568.5 (ratio 20.65x)
# DQI ref: Q=1,893, T=5,725,461 -> S~2.44e13 (piso R=1.191)
# propio Toom-3+V1+E2: Q=1,899, T=4,652,027, eps+=0.000866, R=1.1912605, S=1.99836e13
# química ref = propia baseline (65,60,60): lambda_eff 49.301369, S=3,355,599,588.32
# química pública (9,143,40): S=326,800,029.87
REFERENCE_S = {
    "invsqrt": 2_076_774.0,
    "dqi": 2.44e13,
    "dfthcsos": 3_355_599_588.32,
}
BEST_OWN_S = {
    "invsqrt": 100_568.5,
    "dqi": 1.99836e13,  # Toom-3+V1+E2 medido; BM+Forney es proyección, no medido
    "dfthcsos": 3_355_599_588.32,
}
# Mejor envío global (combo-b-pack-v2, componentes públicos): 23.94667
BEST_GLOBAL_SCORE = 23.94667


@dataclass(frozen=True)
class CircuitSpec:
    """Contrato de una tarea VQCC. Es el spec.py reorientado.

    task: 'invsqrt' | 'dqi' | 'dfthcsos'
    thresholds: dict con los umbrales oficiales que el candidato debe pasar.
    baseline_S: S del mejor propio medido; una mutación solo se acepta si
        pasa el contrato Y baja de este S (o del mejor visto en la búsqueda).
    """
    task: str
    name: str
    thresholds: dict[str, Any] = field(default_factory=dict)
    baseline_S: float = float("inf")
    intent: str = ""

    def check_metrics(self, metrics: dict[str, Any]) -> list[str]:
        """Lista de fallos del contrato, vacía si pasa. Puro, sin simulación."""
        fails: list[str] = []
        if self.task == "invsqrt":
            # La fase se verifica en el simulador (verify.py); aquí solo
            # se comprueban los números de costo que trae el candidato.
            if metrics.get("Q", 0) <= 0:
                fails.append("invsqrt: Q debe ser > 0")
            if metrics.get("C", 0) <= 0:
                fails.append("invsqrt: C debe ser > 0")
        elif self.task == "dqi":
            eps = metrics.get("eps_plus")
            if eps is None:
                fails.append("dqi: falta eps_plus")
            elif not eps < DQI_EPS_PLUS_MAX:
                fails.append(f"dqi: eps+ = {eps:.6g} >= 1/16")
            if metrics.get("Q", 0) <= 0:
                fails.append("dqi: Q debe ser > 0")
        elif self.task == "dfthcsos":
            e1 = metrics.get("error_1_mHa")
            e2 = metrics.get("error_2_mHa")
            if e1 is not None and e1 > CHEM_ERROR_MAX_MHA:
                fails.append(f"química: error_1 = {e1:.4f} mHa > 20 mHa")
            if e2 is not None and e2 > CHEM_ERROR_MAX_MHA:
                fails.append(f"química: error_2 = {e2:.4f} mHa > 20 mHa")
            lam = metrics.get("Lambda")
            if lam is not None and not lam > CHEM_LAMBDA_FLOOR:
                fails.append(f"química: Lambda = {lam} debe ser > 49.0")
            gap = metrics.get("E_gap")
            if gap is not None and not gap > CHEM_E_GAP_FLOOR:
                fails.append(f"química: E_gap = {gap} debe ser > 3.914898")
            q = metrics.get("angles_qubits")
            if q is not None and q > CHEM_QUBIT_CAP:
                fails.append(f"química: Angles_k usa {q} qubits > 128")
        else:
            fails.append(f"tarea desconocida: {self.task!r}")
        return fails


def invsqrt_spec() -> CircuitSpec:
    return CircuitSpec(
        task="invsqrt",
        name="invsqrt",
        thresholds={
            "precision_bits": INVSQRT_PRECISION_BITS,
            "max_x": INVSQRT_MAX_X,
            "width": INVSQRT_WIDTH,
            "beta": INVSQRT_BETA,
            "formula": "S = Q * C, C = Toffoli + T/4",
        },
        baseline_S=BEST_OWN_S["invsqrt"],
        intent="Fase beta/sqrt(x) con tol 2^-24*beta/sqrt(x) para todo x; bajar S=Q*C.",
    )


def dqi_spec() -> CircuitSpec:
    return CircuitSpec(
        task="dqi",
        name="dqi",
        thresholds={
            "m": DQI_M, "n": DQI_N, "degree": DQI_DEGREE, "r": DQI_R,
            "eps_plus_max": DQI_EPS_PLUS_MAX,
            "log2_delta": DQI_LOG2_DELTA,
            "formula": "S = R(eps+) * Q^2 * T",
        },
        baseline_S=BEST_OWN_S["dqi"],
        intent="Decodificador DQI con eps+ < 1/16; bajar S=R*Q^2*T.",
    )


def dfthcsos_spec() -> CircuitSpec:
    return CircuitSpec(
        task="dfthcsos",
        name="dfthcsos",
        thresholds={
            "error_max_mHa": CHEM_ERROR_MAX_MHA,
            "Lambda_floor": CHEM_LAMBDA_FLOOR,
            "E_gap_floor": CHEM_E_GAP_FLOOR,
            "qubit_cap": CHEM_QUBIT_CAP,
            "formula": "S = lambda_eff * Ttot * Qtot",
        },
        baseline_S=BEST_OWN_S["dfthcsos"],
        intent="Factorización DFTHC-SOS con error_1/error_2 <= 20 mHa, "
               "Lambda > 49.0, E_gap > 3.914898; bajar S=lambda_eff*T*Q.",
    )


SPECS = {"invsqrt": invsqrt_spec, "dqi": dqi_spec, "dfthcsos": dfthcsos_spec}

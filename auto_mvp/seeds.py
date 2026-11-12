"""AUTO_MVP — semillas por defecto: la base medida de cada tarea (desde v1.2.0).

Las semillas son la base DESDE LA QUE el corredor autónomo (auto.py)
empieza a buscar. Nada aquí es inventado: cada semilla trae sus números
medidos y su procedencia.

- dqi: el circuito BM+Forney como grafo de llamadas (cost_model exacto,
  el mismo de los tests v060/v110): T=1,511,522, Q=1,414, eps+=0.001188.
  La regla chien-montgomery-b17 aplica y da el número medido
  (T=1,315,731, S=3.2331e12).
- invsqrt: el invsqrt v1 certificado (verificador oficial PASS,
  S=100,568.5). No hay reglas MORPH medidas para invsqrt: el grafo
  semilla es solo la raíz con sus métricas, el mutador no propone
  nada para esta tarea hasta que haya una regla medida.
- dfthcsos: la factorización baseline (65,60,60) medida
  (lambda_eff=49.301369, Ttot=93,237, Qtot=730, S=3,355,599,588.32).
  Igual: sin reglas MORPH medidas para química.

El mutador hereda eps_plus / rel_error / lambda_eff de la semilla y
nunca los toca; solo mueve T/Q con deltas medidos de reglas.
"""
from __future__ import annotations

from typing import Any

from .qualtran_bridge import Block, CallGraph

# DQI (medido): BM+Forney, Q=1,414, T=1,511,522, eps+=0.001188.
DQI_EPS_PLUS = 0.001188
DQI_BASE_METRICS: dict[str, Any] = {
    "Q": 1414, "T": 1_511_522, "eps_plus": DQI_EPS_PLUS,
}
DQI_PROVENANCE = (
    "BM+Forney cost_model exacto (tests v060/v110); "
    "regla chien-montgomery-b17 medida: T 1,511,522 -> 1,315,731, "
    "S=3.2331e12 (montgomery-v4)"
)

# invsqrt (medido): v1 certificado por el verificador oficial.
# Las métricas son las CERTIFICADAS (media por shot, no el máximo):
# Q=62, toffoli medio 1,325.48, C equivalente 1,622.07 (t_count =
# 4*(1622.07-1325.48) = 1,186.36, síntesis de rotaciones), S=100,568.5.
# Con el máximo (1,495) el proxy daría 92,690, mejor que el certificado:
# ese 8% es un artefacto del proxy, no una mejora real. Por eso la
# semilla usa la media certificada.
INVSQRT_BASE_METRICS: dict[str, Any] = {
    "Q": 62, "toffoli": 1325.48, "t_count": 1186.36, "rotations": 0,
    "rel_error": 3.4437759310890215e-08,
}
INVSQRT_PROVENANCE = (
    "invsqrt v1 certificado, verificador oficial PASS, S=100,568.5; "
    "sin reglas MORPH medidas para invsqrt"
)

# Química (medida): baseline (65,60,60).
CHEM_BASE_METRICS: dict[str, Any] = {
    "Qtot": 730, "Ttot": 93_237, "lambda_eff": 49.301369,
    "error_2_mHa": 18.6396, "E_gap": 3.96548,
}
CHEM_PROVENANCE = (
    "baseline (65,60,60) medida, S=3,355,599,588.32; "
    "sin reglas MORPH medidas para química"
)


def _dqi_seed_graph() -> CallGraph:
    """El circuito BM+Forney como grafo de llamadas (cost_model exacto)."""
    root = Block(name="dqi-bm-forney", kind="dqi", t_count=1_511_522,
                 qubits=1_414, children=[
                     (Block(name="bm_forward", kind="bm_forward"), 1),
                     (Block(name="omega", kind="omega"), 1),
                     (Block(name="chien", kind="chien"), 1),
                     (Block(name="bm_backward", kind="bm_backward"), 1)])
    return CallGraph(root=root, source="cost_model")


def _root_only_seed(name: str, kind: str, qubits: int) -> CallGraph:
    """Semilla sin bloques hijos: solo la raíz con sus métricas medidas.

    Sin hijos no hay reglas que apliquen: el mutador no propone nada
    para esta tarea. Eso es honesto: sin una regla medida no hay nada
    que mutar, y la tarea aporta su mejor valor conocido (el del ledger).
    """
    root = Block(name=name, kind=kind, t_count=None, qubits=qubits)
    return CallGraph(root=root, source="cost_model")


def default_seeds() -> dict[str, dict[str, Any]]:
    """Las tres semillas por defecto, frescas en cada llamada.

    Por tarea: ``seed_graph`` (dict, para el Mutator),
    ``base_metrics`` (las métricas medidas) y ``provenance``.
    """
    return {
        "dqi": {
            "seed_graph": _dqi_seed_graph().to_dict(),
            "base_metrics": dict(DQI_BASE_METRICS),
            "provenance": DQI_PROVENANCE,
        },
        "invsqrt": {
            "seed_graph": _root_only_seed(
                "invsqrt-v1-certificado", "invsqrt", 62).to_dict(),
            "base_metrics": dict(INVSQRT_BASE_METRICS),
            "provenance": INVSQRT_PROVENANCE,
        },
        "dfthcsos": {
            "seed_graph": _root_only_seed(
                "dfthcsos-baseline-65-60-60", "dfthcsos", 730).to_dict(),
            "base_metrics": dict(CHEM_BASE_METRICS),
            "provenance": CHEM_PROVENANCE,
        },
    }


# Las semillas como dato (grafos en dict, listos para el Mutator).
DEFAULT_SEEDS: dict[str, dict[str, Any]] = default_seeds()

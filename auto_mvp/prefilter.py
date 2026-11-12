"""AUTO_MVP v2.3 — el PREFILTRO: la puerta barata delante del paso caro.

Arturo (2026-11-12): compilar y simular cada mutación en crudo con
kickmix es un callejón sin salida computacional. La arquitectura real
no compila a ciegas: primero pasa por los sensores y modelos
analíticos ligeros (proxy + Lab numérico) que descartan el 99% de la
basura en segundos, y SOLO cuando una variante pasa el filtro
matemático y cruza la puerta de integridad se gasta el tiempo de
cómputo compilando el circuito real para dárselo al juez.

El proxy es la PUERTA, no el producto (la DIRECTIVA v2.0 sigue en
pie: solo un circuito válido y MEDIDO cuenta; el proxy nunca llega
a la meta, nunca pone el puntaje). v1.x falló porque el proxy ERA el
producto; aquí es el filtro delante del paso caro, y su error está
MEDIDO (calibrate_proxy: p95 del error relativo contra pares
estimado/medido, cap 0.25).

Cómo funciona, por ronda:

1. El modelo propone un LOTE de deltas (no uno solo).
2. Cada delta se ESTIMA en milisegundos (`estimate_delta`): un
   CandidateMeta con métricas estimadas (no medidas) + la fórmula
   oficial de su tarea. Las estimaciones dicen de dónde salen:
   invsqrt usa la ganancia media por K del historial medido; DQI
   usa el modelo de costos vendido (que reproduce exactos los 4
   decodificadores medidos); química exige métricas medidas de la
   factorización (sin números inventados: si el delta no las trae,
   se rechaza).
3. `MetadataProxy` (el validador como filtro de entrada: prefiltro
   numérico del Lab, topes duros, contrato oficial, y solo pasa si
   el S estimado baja del mejor por más que el margen calibrado)
   ordena el lote: primero los que pasan, por S estimado.
4. MWIS sobre los que pasan: dos deltas en CONFLICTO son los que
   tocan lo mismo (el mismo K, el mismo multiplicador). El conjunto
   independiente de máxima ganancia teórica es lo que se prueba en
   la ronda: con pocos huecos caros, no se gastan dos en el mismo
   target. Sin simular nada.
5. Solo los 1-2 primeros ganan el paso caro (construir + validar +
   medir con kickmix). El resto queda registrado como descartado
   barato, con su motivo. El puntaje que cuenta sigue siendo el
   MEDIDO.
"""
from __future__ import annotations

from typing import Any

from .circuits.cost_models.dqi_cost import estimate_variant as _dqi_variant
from .mwis import build_conflict_graph, solve_mwis
from .proxy import CandidateMeta, MetadataProxy, calibrate_proxy
from .vqcc.contracts import dfthcsos_spec, dqi_spec, invsqrt_spec

# eps+ MEDIDO de la semilla DQI V1 (102,400 shots, 0 fallos). El
# estimado lo usa como hipótesis (la variante tendrá un eps+ parecido);
# el eps+ real solo lo mide el verificador oficial.
DQI_EPS_PLUS_SEED = 0.000866

_SPECS = {"invsqrt": invsqrt_spec, "dqi": dqi_spec,
          "dfthcsos": dfthcsos_spec}


def calibrate_margin(pairs: list[tuple[float, float]]) -> float:
    """El margen del proxy, MEDIDO contra pares (estimado, medido).

    p95 del error relativo, cap 0.25. Es lo que hace honesto al
    filtro: su error no se supone, se mide cada vez que hay una
    medición nueva. Con menos de 3 pares, 0.25 conservador.
    """
    return calibrate_proxy(pairs)


def expected_gain(history: list[dict[str, Any]], K: int) -> float:
    """Ganancia media MEDIDA por K (Toffolis), del historial.

    Si un K nunca dio nada, la expectativa es 0: el proxy no inventa
    ganancia. La expectativa es solo para ordenar; el medido manda.
    """
    gains = [float(h.get("gain_reported", 0)) for h in history
             if h.get("K") == K and h.get("valid")]
    if not gains:
        return 0.0
    return sum(gains) / len(gains)


def estimate_delta(task: str, delta: dict[str, Any],
                   best_seed: dict[str, Any],
                   history: list[dict[str, Any]]) -> CandidateMeta:
    """Un delta como CandidateMeta (métricas ESTIMADAS, no medidas)."""
    if task == "invsqrt":
        K = int(delta["K"])
        best_Q = int(best_seed["Q"])
        best_T = float(best_seed["T"])
        best_S = float(best_seed["S"])
        # El C MEDIDO (S/Q) incluye el coste fijo que sa_windows no
        # toca (T/4 + síntesis de rotaciones): best_C - best_T. El
        # estimado parte del S MEDIDO y resta la ganancia esperada
        # (cada Toffoli ahorrado baja C en 1); con ganancia 0 el
        # estimado ES el mejor S, y la puerta del margen lo rechaza.
        # t_count lleva ese coste fijo x4 para que estimate_S
        # (Q * (toffoli + t_count/4)) parta del C medido.
        best_C = best_S / best_Q
        fixed = max(0.0, best_C - best_T)
        gain = expected_gain(history, K)
        toffoli = max(0.0, best_T - gain)
        return CandidateMeta(
            task="invsqrt",
            metrics={"Q": best_Q, "toffoli": toffoli,
                     "t_count": fixed * 4.0, "rotations": 0,
                     "C": best_C - gain},
            register_widths={"x": 22, "scratch": 40},
            topology={"max_qubits": best_Q})
    if task == "dqi":
        var = _dqi_variant(int(delta.get("mult", 63)),
                           v1=bool(delta.get("v1", False)),
                           e2=bool(delta.get("e2", False)))
        return CandidateMeta(
            task="dqi",
            metrics={"Q": var["Q"], "T": var["T"],
                     "eps_plus": DQI_EPS_PLUS_SEED},
            register_widths={"total": var["Q"]},
            topology={"max_qubits": var["Q"]})
    if task == "dfthcsos":
        m = delta.get("metrics")
        if not isinstance(m, dict):
            raise ValueError(
                "química: el delta necesita 'metrics' medidas de la "
                "factorización (lambda_eff, Ttot, Qtot, error_2_mHa, "
                "Lambda, E_gap, angles_qubits); sin ellas no se estima")
        return CandidateMeta(
            task="dfthcsos",
            metrics={"lambda_eff": float(m["lambda_eff"]),
                     "Ttot": float(m["Ttot"]), "Qtot": float(m["Qtot"]),
                     "error_2_mHa": float(m.get("error_2_mHa", 0.0)),
                     "Lambda": float(m.get("Lambda", 0.0)),
                     "E_gap": float(m.get("E_gap", 0.0)),
                     "angles_qubits": int(m.get("angles_qubits", 0))},
            register_widths={"total": int(m["Qtot"])},
            topology={})
    raise ValueError(f"tarea desconocida: {task!r}")


def delta_target(delta: dict[str, Any]) -> str:
    """Lo que toca el delta: dos deltas con el mismo target confligen."""
    if "K" in delta:
        return f"K={delta['K']}"
    if "mult" in delta:
        return f"mult={delta['mult']}"
    if "rank" in delta:
        return f"rank={delta['rank']}"
    return "?"


def delta_conflicts(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Dos deltas confligen si tocan lo mismo de forma distinta."""
    if delta_target(a) != delta_target(b):
        return False
    return a != b


def rank_deltas(deltas: list[dict[str, Any]], task: str, best_S: float,
                best_seed: dict[str, Any],
                history: list[dict[str, Any]],
                margin: float = 0.25, top_k: int = 2
                ) -> dict[str, Any]:
    """El lote ordenado por el proxy + MWIS. Solo los primeros ganan.

    Devuelve {"winners": [(delta, verdict)], "discarded": [(delta,
    reason)], "ranked": [(delta, verdict)]}. Los winners son el
    conjunto independiente de máxima ganancia teórica entre los que
    pasan la puerta (MWIS: un hueco caro por target, no dos en el
    mismo K), ordenados por S estimado. Todo en milisegundos:
    ningún candidato llega a kickmix aquí.
    """
    if task not in _SPECS:
        raise ValueError(f"tarea desconocida: {task!r}")
    proxy = MetadataProxy(_SPECS[task](), margin=float(margin))
    # 1. Deduplicar (el mismo delta dos veces es un solo intento).
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for d in deltas:
        key = str(sorted(d.items()))
        if key in seen:
            continue
        seen.add(key)
        unique.append(d)
    # 2. Estimar + puerta del proxy. Se guarda la pareja (delta, meta)
    # para no perderla al ordenar: dos deltas pueden estimar el mismo S
    # y no son el mismo delta.
    pairs: list[tuple[dict[str, Any], CandidateMeta]] = []
    discarded: list[tuple[dict[str, Any], str]] = []
    for d in unique:
        try:
            pairs.append((d, estimate_delta(task, d, best_seed, history)))
        except (ValueError, KeyError, TypeError) as exc:
            discarded.append((d, f"no estimable: {exc}"))
    scored: list[tuple[dict[str, Any], Any]] = [
        (d, proxy.evaluate(m, best_S)) for d, m in pairs]
    scored.sort(key=lambda dv: (not dv[1].ok,
                                dv[1].s_estimate
                                if dv[1].s_estimate is not None
                                else float("inf")))
    passing: list[tuple[dict[str, Any], Any]] = []
    for d, verdict in scored:
        if verdict.ok:
            passing.append((d, verdict))
        else:
            discarded.append(
                (d, "; ".join(verdict.reasons) or "no pasa la puerta"))
    # 3. MWIS: entre los que pasan, el conjunto sin conflictos con
    # más ganancia teórica (peso = mejor_S - S estimado).
    winners: list[tuple[dict[str, Any], Any]] = []
    if passing:
        points = [d for d, _ in passing]
        weights = [max(0.0, best_S - float(v.s_estimate or best_S))
                   for _, v in passing]
        adj = build_conflict_graph(points, delta_conflicts)
        selected = solve_mwis(adj, weights, method="greedy", seed=42)
        chosen = [passing[i] for i in sorted(selected)]
        chosen.sort(key=lambda dv: dv[1].s_estimate or float("inf"))
        winners = chosen[: int(top_k)]
        for d, v in passing:
            if (d, v) not in winners:
                discarded.append(
                    (d, "pasa la puerta pero MWIS eligió otro sin conflicto"))
    return {"winners": winners, "discarded": discarded,
            "ranked": scored}

"""Metodología de métricas VQCC: circuitos y protocolo, en código.

Cada métrica de rendimiento del repo se deriva aquí de forma
transparente y reproducible: el circuito (con su procedencia y su
verificación), la fórmula oficial (de costs.py, copiada de los
verificadores), y la traza completa (entradas, pasos intermedios,
resultado). Nada se afirma sin decir de dónde salió ni cómo se
calculó. Ver METODOLOGIA.md para la versión en prosa.

Uso:
    from auto_mvp.vqcc import metrics
    metrics.trace("dqi", "publico")      # traza completa del DQI público
    metrics.trace_all()                  # las tres tareas, mejor envío
    metrics.report()                     # informe en texto
"""
from __future__ import annotations

import math
from typing import Any

from .contracts import BEST_SUBMISSION_S, REFERENCE_S
from .costs import (
    geometric_score,
    ratio,
    repetition_overhead,
    rotation_t_count,
    s_chem,
    s_dqi,
    s_invsqrt,
)

# --- Circuitos medidos (procedencia y verificación) ---
# Cada entrada es un circuito real con su evidencia. 'medido' significa
# que el número viene de una medición (verificador oficial o kickmix),
# no de una proyección. 'proyeccion' es un diseño sin verificar.

CIRCUITS: dict[str, dict[str, dict[str, Any]]] = {
    "invsqrt": {
        "propio-v1-certificado": {
            "nombre": "invsqrt v1 (propio, certificado)",
            "archivo": "sandbox-run/invsqrt/invsqrt_final_v1.kmb",
            "sha256": "45825861…",
            "Q": 62,
            "toffoli": 1495,
            "registro_x_qubits": 22,
            "S_medido": 100_568.5,
            "ratio": 20.65,
            "medido": True,
            "verificacion": {
                "metodo": "verificador oficial (kernel Kaggle)",
                "kernel": "dcpracmatic/official-verifier-invsqrt",
                "kernel_id": 144153668,
                "shots": 200_540_928,
                "fallos": 0,
                "nota": "S es el puntaje oficial (Toffolis medios por shot), "
                        "no Q*C estático (110,931).",
            },
            "formula": "S = Q * C, C = Toffoli + T/4 (+ síntesis de rotaciones, v0.9.1)",
        },
    },
    "dqi": {
        "publico": {
            "nombre": "DQI público híbrido (jday96314/QuantumAI)",
            "archivo": "sandbox-run/public-dqi/dqi.kmb",
            "Q": 892,
            "T_media": 398_176,
            "T_estatica": 453_312,
            "eps_plus": 0.000866,
            "R": 1.19126,
            "S_medido": 3.7676e11,
            "ratio": 64.76,
            "medido": True,
            "verificacion": {
                "metodo": "mejor envío (ref 58076483), puntaje público 23.94667",
                "shots": 102_400,
                "fallos": 0,
                "nota": "Híbrido clásico-cuántico: trabaja in situ sobre S, "
                        "intermedios en 104,140 bits clásicos, 114,752 HMR, "
                        "82 inversiones. Mapa de fases medido: espejos 56.43% "
                        "de T (INFORME_MEJORA_30.md).",
            },
            "formula": "S = R(eps+) * Q^2 * T_media",
            "mapa_fases": {
                "unextract": 121_039,
                "unconvert": 76_105,
                "padded_unsynthesis": 58_645,
                "extract": 61_855,
                "convert": 59_489,
                "scan": 44_275,
                "synthesis": 31_904,
                "espejos_pct": 56.43,
                "companion_unextract_T": 50_984,
            },
        },
        "propio-toom4-v1-e2": {
            "nombre": "DQI propio Toom-4+V1+E2",
            "archivo": "vqcc-submission/modules/dqi/dqi.kmb (Toom-4)",
            "Q": 1_899,
            "T": 4_477_394,
            "S_medido": 1.923348e13,
            "ratio": 1.269,
            "medido": True,
            "verificacion": {
                "metodo": "verificador oficial (kernel Kaggle)",
                "kernel": "dcpracmatic/dqi-toom4-v1-e2-102400",
                "kernel_id": 144398281,
                "shots": 102_400,
                "fallos": 0,
            },
            "formula": "S = R(eps+) * Q^2 * T",
        },
        "bm-forney-montgomery-b17": {
            "nombre": "DQI BM+Forney Montgomery b=17 (diseño)",
            "Q": 1_414,
            "T": 1_315_731,
            "S_proyectado": 3.2331e12,
            "ratio": 7.55,
            "medido": False,
            "verificacion": {
                "metodo": "Chien completo medido en montgomery-v4 (kickmix); "
                        "el .kmb completo y el verificador oficial 102,400 "
                        "shots están pendientes",
                "nota": "S es PROYECCIÓN (cost_model exacto), no medición.",
            },
            "formula": "S = R(eps+) * Q^2 * T",
        },
    },
    "dfthcsos": {
        "publica": {
            "nombre": "Química pública (9,143,40)",
            "S_medido": 326_800_029.87,
            "lambda_eff": 47.037,
            "ratio": 10.27,
            "medido": True,
            "verificacion": {
                "metodo": "mejor envío (ref 58076483)",
                "nota": "Margen CERO (error_2 y E_gap en el límite): si el "
                        "conjunto privado la saca, todo el envío se rechaza.",
            },
            "formula": "S = lambda_eff * Ttot * Qtot",
        },
        "propia-baseline": {
            "nombre": "Química propia baseline (65,60,60)",
            "archivo": "sandbox-run/dfthc-sos/baseline/",
            "S_medido": 3_355_599_588.32,
            "lambda_eff": 49.301369,
            "error_2_mHa": 18.6396,
            "ratio": 1.0,
            "medido": True,
            "verificacion": {
                "metodo": "verificador del starter kit (sandbox y Kaggle, "
                        "mismo puntaje y mismo sha256)",
                "kernel": "dcpracmatic/dfthc-sos-baseline",
                "kernel_id": 144333524,
                "shots": 254_464,
            },
            "formula": "S = lambda_eff * Ttot * Qtot",
        },
    },
}


def _trace_invsqrt(c: dict[str, Any]) -> dict[str, Any]:
    """Traza de S invsqrt: fórmula oficial con síntesis de rotaciones."""
    pasos = [
        "S = Q * C, C = Toffoli + T/4 (verificador oficial invsqrt).",
        "Con rotaciones Z_POW finas, T incluye la síntesis: "
        "rotation_t_count(eps) = 0.56*log2(1/eps) + 5.3 por rotación (v0.9.1).",
        f"Q = {c['Q']}, Toffolis = {c['toffoli']}.",
        "El S que se reporta es el MEDIDO por el verificador oficial "
        f"({c['S_medido']}), no el Q*C estático, porque el verificador "
        "cuenta Toffolis medios por shot.",
    ]
    # C estático (sin síntesis) para referencia.
    c_estatico = c["toffoli"]  # T/4 = 0 aquí (sin dato de T); se reporta el medido.
    return {
        "tarea": "invsqrt",
        "circuito": c["nombre"],
        "formula": c["formula"],
        "entradas": {"Q": c["Q"], "toffoli": c["toffoli"],
                     "registro_x_qubits": c.get("registro_x_qubits")},
        "pasos": pasos,
        "S": c["S_medido"],
        "ratio": c["ratio"],
        "S_ref": REFERENCE_S["invsqrt"],
        "medido": c["medido"],
        "verificacion": c["verificacion"],
    }


def _trace_dqi(c: dict[str, Any]) -> dict[str, Any]:
    """Traza de S DQI: R(eps+) * Q^2 * T, con el mapa de fases si lo hay."""
    pasos = [
        "S = R(eps+) * Q^2 * T (verificador oficial DQI).",
        "R(eps) = ln2 / -ln(1/2 + 2*sqrt(eps)); eps+ es Clopper-Pearson "
        "con confianza 1-2^-128.",
    ]
    entradas: dict[str, Any] = {"Q": c["Q"]}
    if "T_media" in c:
        entradas["T_media"] = c["T_media"]
        entradas["T_estatica"] = c["T_estatica"]
        entradas["eps_plus"] = c["eps_plus"]
        entradas["R"] = c["R"]
        # Recomputa R desde eps+ para verificar.
        r_calc = repetition_overhead(c["eps_plus"])
        pasos.append(
            f"R recalculado desde eps+={c['eps_plus']}: {r_calc:.5f} "
            f"(reportado {c['R']}).")
        s_calc = s_dqi(c["Q"], c["T_media"], c["eps_plus"])
        pasos.append(
            f"S recalculado = {r_calc:.5f} * {c['Q']}^2 * {c['T_media']} "
            f"= {s_calc:.4g} (reportado {c['S_medido']:.4g}).")
        if "mapa_fases" in c:
            m = c["mapa_fases"]
            pasos.append(
                "Mapa de fases (medido del .kmb, INFORME_MEJORA_30.md): "
                f"espejos {m['espejos_pct']}% de T estática "
                f"(unextract {m['unextract']}, unconvert {m['unconvert']}, "
                f"padded_unsynthesis {m['padded_unsynthesis']}); "
                f"companion en unextract {m['companion_unextract_T']} T.")
        s_val = c["S_medido"]
        ratio_val = c["ratio"]
    else:
        entradas["T"] = c["T"]
        s_val = c.get("S_medido", c.get("S_proyectado"))
        ratio_val = c["ratio"]
        pasos.append(f"T = {c['T']}, Q = {c['Q']}.")
    return {
        "tarea": "dqi",
        "circuito": c["nombre"],
        "formula": c["formula"],
        "entradas": entradas,
        "pasos": pasos,
        "S": s_val,
        "ratio": ratio_val,
        "S_ref": REFERENCE_S["dqi"],
        "medido": c["medido"],
        "verificacion": c["verificacion"],
    }


def _trace_chem(c: dict[str, Any]) -> dict[str, Any]:
    """Traza de S química: lambda_eff * Ttot * Qtot."""
    pasos = [
        "S = lambda_eff * Ttot * Qtot (verificador DFTHC-SOS).",
        f"lambda_eff = {c['lambda_eff']}.",
        "Contrato: error_1/error_2 <= 20 mHa, Lambda > 49.0, "
        "E_gap > 3.914898 Ha, cada Angles_k <= 128 qubits.",
    ]
    if "error_2_mHa" in c:
        pasos.append(f"error_2 medido = {c['error_2_mHa']} mHa "
                     "(margen 1.36 mHa al límite de 20 mHa).")
    return {
        "tarea": "dfthcsos",
        "circuito": c["nombre"],
        "formula": c["formula"],
        "entradas": {"lambda_eff": c["lambda_eff"]},
        "pasos": pasos,
        "S": c["S_medido"],
        "ratio": c["ratio"],
        "S_ref": REFERENCE_S["dfthcsos"],
        "medido": c["medido"],
        "verificacion": c["verificacion"],
    }


_TRACE = {"invsqrt": _trace_invsqrt, "dqi": _trace_dqi,
          "dfthcsos": _trace_chem}


def trace(task: str, component: str) -> dict[str, Any]:
    """Traza completa de una métrica: circuito, fórmula, pasos, S, evidencia.

    task: 'invsqrt' | 'dqi' | 'dfthcsos'. component: clave en CIRCUITS[task].
    """
    if task not in CIRCUITS:
        raise ValueError(f"tarea desconocida: {task!r}")
    if component not in CIRCUITS[task]:
        raise ValueError(
            f"componente {component!r} desconocido para {task}; "
            f"opciones: {sorted(CIRCUITS[task])}")
    return _TRACE[task](CIRCUITS[task][component])


def trace_all() -> dict[str, dict[str, Any]]:
    """La traza de las tres tareas del mejor envío (componentes públicos)."""
    best = {"invsqrt": "propio-v1-certificado", "dqi": "publico",
            "dfthcsos": "publica"}
    out = {t: trace(t, comp) for t, comp in best.items()}
    S = {t: out[t]["S"] for t in best}
    out["_gm"] = {
        "S": S,
        "ratios": {t: ratio(t, s) for t, s in S.items()},
        "GM": geometric_score(S),
        "nota": "GM del mejor envío (ref 58076483).",
    }
    return out


def report() -> str:
    """Informe en texto: circuitos, protocolo y métricas, con procedencia."""
    lines = ["METODOLOGÍA DE MÉTRICAS VQCC — circuitos y protocolo",
             "=" * 60, ""]
    for task, comp in [("invsqrt", "propio-v1-certificado"),
                       ("dqi", "publico"), ("dfthcsos", "publica")]:
        t = trace(task, comp)
        lines.append(f"[{task}] {t['circuito']}")
        lines.append(f"  fórmula: {t['formula']}")
        lines.append(f"  S = {t['S']:.6g}  (ref {t['S_ref']:.6g}, "
                     f"ratio {t['ratio']:.2f}x)")
        lines.append(f"  medido: {t['medido']}")
        for p in t["pasos"]:
            lines.append(f"  - {p}")
        v = t["verificacion"]
        lines.append(f"  verificación: {v.get('metodo', '')}")
        if "kernel_id" in v:
            lines.append(f"    kernel {v.get('kernel')} id {v['kernel_id']}, "
                         f"{v.get('shots')} shots, {v.get('fallos')} fallos")
        if "nota" in v:
            lines.append(f"    nota: {v['nota']}")
        lines.append("")
    gm = trace_all()["_gm"]
    lines.append(f"GM mejor envío = {gm['GM']:.5f} "
                 f"(ratios: { {t: round(r, 2) for t, r in gm['ratios'].items()} })")
    return "\n".join(lines)

"""Biblioteca de motivos estables (Ley Cuantica de la Existencia v6/v6.1,
mecanismo R_delta: redundancia de registros).

Motivos = subcircuitos que pasaron el verificador oficial y se repiten
sin degradar la media geometrica. Se guardan como semillas seguras para
reutilizarlas, no para reinventarlas. Cada motivo trae su costo MEDIDO
(verificador oficial o conteo directo en .kmx), no estimado.

Fuentes medidas (2026-11-19, portfolio 28.23163):
- Multiplicador GF(2^12) 42T: 2,743 bloques de exactamente 42 CCX en
  dqi.kmx (portfolio). Primer bloque q840-q851 = 42 CCX. El DQI ya
  multiplica a 42T; Toom-4 (42T) empata, no mejora.
- Multiplicador truncado GF(2^12) 36T: bloques de 36 CCX en dqi.kmx
  (420 bloques). Solo escriben 7 de 12 bits de salida. Ya minimal
  para su operacion (no convertible a multiplicacion completa).
- kickmix nativo Karatsuba 63T: medido directo (ixor_gf2_mul /
  init_gf2_mul GF(2^12) = 63 Toffoli). Peor que 42T; solo referencia.
- Toom-4 42T: auto_mvp/circuits/generators/toom4.py, tests 13/13.
  Empata con el multiplicador 42T del DQI.
- invsqrt 44Q: maoxin123, S=74,405.67, Q=44, T=1,495, PASS.
  33 rotaciones, peor error 99.95% de tolerancia (sin holgura).
- Quimica 427Q: leotang09, S=294,642,170.57, Q=427, Tof=14,706,
  Lambda=283.14, lambda_eff=46.92, error_2=0.020 (al limite).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Motif:
    """Un subcircuito estable y reutilizable.

    Campos de impacto en la metrica (para que el LLM ataque los
    terminos mas caros, no solo el conteo de T):
    - DQI (R * Q^2 * T): qubits (Q entra al cuadrado) y eps_plus
      (debe ser < 1/16 para puntaje finito).
    - invsqrt (Q * C): rotation_t = T de sintesis de rotaciones
      (C incluye Toffolis + T/4 + sintesis de rotaciones finas).
    - dfthcsos (lambda_eff * T_total * Q_tot): lambda_impact y
      e_gap_impact (como afecta a Lambda y E_gap), t_total_impact.
    """
    name: str
    task: str  # "dqi" | "invsqrt" | "dfthcsos"
    kind: str  # "gf_mul" | "gf_mul_trunc" | "qrom" | "loader" | ...
    toffoli: int
    qubits: int
    measured: str  # donde se midio (verificador oficial / .kmx / tests)
    note: str = ""
    # Referencia al generador en el repo (ruta o None si es del portfolio).
    generator: str | None = None
    # --- Impacto en la metrica (nuevo, v6.1) ---
    # DQI: qubits que consume (Q^2) y efecto en eps+ (< 1/16).
    eps_plus_impact: str = "neutro"
    # invsqrt: T de sintesis de rotaciones que trae el motivo.
    rotation_t: float = 0.0
    # dfthcsos: como afecta a Lambda / E_gap / T_total.
    lambda_impact: str = "neutro"
    e_gap_impact: str = "neutro"
    t_total_impact: str = "neutro"
    # Peso de muestreo en el prompt (1.0 = normal; baja si el motivo
    # genera candidatos que fallan o no mejoran; sube si gana).
    weight: float = 1.0


# --- Motivos medidos (no estimados) ---
MOTIFS: list[Motif] = [
    Motif(
        name="gf12_mul_42t",
        task="dqi",
        kind="gf_mul",
        toffoli=42,
        qubits=36,  # 12+12+12 (f,g,h) sin ancillas extra en el .kmx
        measured="dqi.kmx portfolio 28.23: 2,743 bloques de 42 CCX",
        note="Multiplicacion GF(2^12) completa, 12 bits de salida. "
             "El DQI ya la usa; Toom-4 empata.",
        generator=None,
        eps_plus_impact="neutro (0 errores a 102,400 shots, eps+ 0.00087)",
    ),
    Motif(
        name="gf12_mul_trunc_36t",
        task="dqi",
        kind="gf_mul_trunc",
        toffoli=36,
        qubits=36,
        measured="dqi.kmx portfolio 28.23: 420 bloques de 36 CCX",
        note="Multiplicacion truncada: solo 7 bits de salida. "
             "Ya minimal; no convertible a multiplicacion completa.",
        generator=None,
        eps_plus_impact="neutro",
    ),
    Motif(
        name="gf12_mul_toom4_42t",
        task="dqi",
        kind="gf_mul",
        toffoli=42,
        qubits=48,
        measured="tests/test_toom4.py 13/13; kickmix clasico 510/510",
        note="Toom-4, 7 sub-mult GF(2^3) x 6T. Empata con gf12_mul_42t.",
        generator="auto_mvp.circuits.generators.toom4:emit_toom4_zero",
        eps_plus_impact="neutro (no cambia la logica, solo la aritmetica)",
    ),
    Motif(
        name="gf12_mul_karatsuba_63t",
        task="dqi",
        kind="gf_mul",
        toffoli=63,
        qubits=36,
        measured="kickmix ixor_gf2_mul / init_gf2_mul GF(2^12) = 63T",
        note="Referencia (peor). Solo para comparar; no usar.",
        generator="kickmix.CircuitBuilder.ixor_gf2_mul",
        eps_plus_impact="neutro",
        weight=0.1,  # despriorizado: es peor que 42T
    ),
    Motif(
        name="invsqrt_44q",
        task="invsqrt",
        kind="circuit",
        toffoli=1495,
        qubits=44,
        measured="verificador oficial Kaggle: S=74,405.67, PASS, 0 fallos",
        note="maoxin123. 33 rotaciones, peor error 99.95% tolerancia. "
             "Sin holgura para quitar rotaciones.",
        generator=None,
        rotation_t=954.0,  # 33 rotaciones x 28.91 T (C incluye T/4 = 239.5)
    ),
    Motif(
        name="dfthcsos_loader",
        task="dfthcsos",
        kind="loader",
        toffoli=268,  # media de los 15 loaders (263-292)
        qubits=128,
        measured="verificador oficial Kaggle: S=294,642,170.57, PASS",
        note="leotang09. 15 loaders, 4,022 Toffoli en total. "
             "Peephole/SA/temporal = 0. Lambda=283.14.",
        generator=None,
        lambda_impact="Lambda=283.14 (palanca: bajar a ~229 reentrenando)",
        e_gap_impact="E_gap=3.914898 (en el piso, sin holgura)",
        t_total_impact="T_total=14,706 (loaders 4,022 + resto)",
    ),
]


def get_motif(name: str) -> Motif:
    """Devuelve un motivo por nombre (KeyError si no existe)."""
    for m in MOTIFS:
        if m.name == name:
            return m
    raise KeyError(f"motivo no encontrado: {name}")


def motifs_for_task(task: str) -> list[Motif]:
    """Motivos de una tarea, ordenados por Toffoli ascendente."""
    return sorted((m for m in MOTIFS if m.task == task), key=lambda m: m.toffoli)


def best_gf12_mul() -> Motif:
    """El multiplicador GF(2^12) mas barato medido (42T)."""
    cands = [m for m in MOTIFS if m.kind == "gf_mul"]
    return min(cands, key=lambda m: m.toffoli)


def motif_prompt_block(task: str) -> str:
    """Bloque de texto para el prompt del LLM: los motivos estables de
    una tarea, con costos medidos Y su impacto en la metrica (Q^2 y
    eps+ en DQI, sintesis de rotaciones en invsqrt, Lambda/E_gap/T en
    dfthcsos), para que el LLM ataque los terminos mas caros y no
    proponga 'ahorros' falsos que el verificador penaliza."""
    lines = [f"Motivos estables medidos para {task} (usar como semillas, no reinventar):"]
    for m in motifs_for_task(task):
        extra = ""
        if task == "dqi":
            extra = f" Q={m.qubits} (Q entra al cuadrado), eps+: {m.eps_plus_impact}."
        elif task == "invsqrt":
            extra = f" Rotaciones: {m.rotation_t:.0f} T de sintesis (C incluye T/4)."
        elif task == "dfthcsos":
            extra = f" Lambda: {m.lambda_impact}. E_gap: {m.e_gap_impact}. T: {m.t_total_impact}."
        lines.append(
            f"- {m.name}: {m.toffoli} Toffoli, Q={m.qubits}.{extra} "
            f"Medido: {m.measured}. {m.note} (peso {m.weight})"
        )
    return "\n".join(lines)


# --- Bucle de retroalimentacion real (v6.1, punto 3) ---
# Ratios de referencia (coste referencia / coste actual), verificados.
# La tarea con el menor ratio es la mas rezagada y frena la media
# geometrica: ahi se concentra el esfuerzo.
REFERENCE_COSTS = {
    "invsqrt": 2076774.23,
    "dqi": 24439463583672.93,
    "dfthcsos": 3355599588.32,
}
CURRENT_SCORES = {
    "invsqrt": 74405.67,
    "dqi": 345256821433.9815,
    "dfthcsos": 294642170.565169,
}


def current_ratios() -> dict:
    """Ratio (referencia / actual) por tarea. Mayor = mejor."""
    return {k: REFERENCE_COSTS[k] / CURRENT_SCORES[k] for k in REFERENCE_COSTS}


def lagging_task() -> str:
    """La tarea mas rezagada (menor ratio): la que mas frena la GM.
    Hoy: dfthcsos (11.39x), frente a invsqrt (27.91x) y dqi (70.79x)."""
    return min(current_ratios(), key=current_ratios().get)


def geometric_mean() -> float:
    """GM actual a partir de los puntajes verificados."""
    r = current_ratios()
    return (r["invsqrt"] * r["dqi"] * r["dfthcsos"]) ** (1.0 / 3.0)


def promote_motif(name: str, new_toffoli: int, measured: str) -> Motif:
    """Promocion automatica: un candidato que paso el verificador oficial
    completo y bajo el costo se registra como nuevo motivo (o actualiza
    el existente) con su costo real medido. Devuelve el motivo."""
    global MOTIFS
    for i, m in enumerate(MOTIFS):
        if m.name == name:
            # Actualizar costo medido (solo si es mejor).
            if new_toffoli < m.toffoli:
                MOTIFS[i] = Motif(
                    name=m.name, task=m.task, kind=m.kind,
                    toffoli=new_toffoli, qubits=m.qubits,
                    measured=measured, note=m.note,
                    generator=m.generator,
                    eps_plus_impact=m.eps_plus_impact,
                    rotation_t=m.rotation_t,
                    lambda_impact=m.lambda_impact,
                    e_gap_impact=m.e_gap_impact,
                    t_total_impact=m.t_total_impact,
                    weight=1.0,
                )
                return MOTIFS[i]
            return m
    # Nuevo motivo (sin generador conocido; se registra con lo medido).
    m = Motif(name=name, task="dqi", kind="gf_mul", toffoli=new_toffoli,
              qubits=0, measured=measured)
    MOTIFS.append(m)
    return m


def demote_motif(name: str, factor: float = 0.5) -> float:
    """Poda por costo real: si un motivo genera repetidamente candidatos
    que fallan el verificador o no mejoran, se le baja el peso de
    muestreo en el prompt. Devuelve el nuevo peso."""
    global MOTIFS
    for i, m in enumerate(MOTIFS):
        if m.name == name:
            new_w = max(0.05, m.weight * factor)
            MOTIFS[i] = Motif(
                name=m.name, task=m.task, kind=m.kind,
                toffoli=m.toffoli, qubits=m.qubits,
                measured=m.measured, note=m.note,
                generator=m.generator,
                eps_plus_impact=m.eps_plus_impact,
                rotation_t=m.rotation_t,
                lambda_impact=m.lambda_impact,
                e_gap_impact=m.e_gap_impact,
                t_total_impact=m.t_total_impact,
                weight=new_w,
            )
            return new_w
    raise KeyError(f"motivo no encontrado: {name}")

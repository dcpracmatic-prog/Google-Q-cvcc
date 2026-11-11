"""Verificador local reorientado (antes verify.py: subproceso, timeout 5 s).

Ahora audita con el verificador OFICIAL de la competencia, en local:

- Química Task 1/2: `starter_kit.verifier.score.evaluate_submission`
  (sin kickmix, sin circuitos). Es el mismo código que usa Kaggle.
  Tarda ~30 s en el baseline FeMoCo (medido 2026-11-11).
- Química Task 3 / invsqrt / DQI con .kmb: usan kickmix y son caros
  (invsqrt completo: 200,540,928 shots; DQI: 102,400 shots).
  `verify_circuit_file` los ejecuta solo si se pide explícitamente,
  con el Python del venv que tiene kickmix
  (~/workspace/sandbox-run/venv/bin/python). Si kickmix no está,
  devuelve `verified=False` con el motivo, NUNCA un PASS inventado.

LÍMITES HONESTOS:
- El costo S solo (sin simulación) NO es una verificación: es un
  cribado rápido. Solo `verify_chemistry_factorization` y
  `verify_circuit_file` con el verificador oficial son verificación.
- La búsqueda usa el cribado barato para descartar, y el verificador
  oficial solo para el finalista. Eso es lo que hace que iterar sea
  rápido sin mentir sobre lo verificado.
"""
from __future__ import annotations

import importlib.util
import math
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .contracts import CircuitSpec
from .costs import ratio, s_chem, s_dqi, s_invsqrt

STARTER_KIT = Path.home() / "workspace/sandbox-run/starter-kit"
COMPETITION_VERIFIERS = Path.home() / "workspace/sandbox-run/competition-verifiers"
VENV_PYTHON = Path.home() / "workspace/sandbox-run/venv/bin/python"


@dataclass
class CircuitVerifyResult:
    ok: bool
    S: float = float("inf")
    failures: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    verified_by: str = ""  # 'official' | 'cost-only' | 'none'
    note: str = ""


def _cost_only(spec: CircuitSpec, metrics: dict[str, Any]) -> CircuitVerifyResult:
    """Cribado por fórmula + contrato. No es verificación oficial."""
    fails = spec.check_metrics(metrics)
    try:
        if spec.task == "invsqrt":
            S = s_invsqrt(metrics["Q"], metrics.get("toffoli", 0), metrics.get("t_count", 0))
        elif spec.task == "dqi":
            S = s_dqi(metrics["Q"], metrics["T"], metrics["eps_plus"])
        elif spec.task == "dfthcsos":
            S = s_chem(metrics["lambda_eff"], metrics["Ttot"], metrics["Qtot"])
        else:
            return CircuitVerifyResult(False, failures=[f"tarea desconocida: {spec.task}"])
    except (KeyError, TypeError, ValueError) as e:
        # Un candidato que rompe el contrato (por ejemplo eps+ >= 1/16,
        # fuera del dominio de R) no debe tumbar el lazo con una
        # excepción: se rechaza visible, con S=inf, como cualquier
        # otro candidato inválido.
        return CircuitVerifyResult(
            False, S=float("inf"), failures=fails + [f"costo no computable: {e}"],
            metrics=dict(metrics), verified_by="cost-only",
            note="Candidato inválido: el contrato ya lo rechaza; "
                 "la fórmula de costo no tiene sentido para él.",
        )
    return CircuitVerifyResult(
        ok=not fails, S=S, failures=fails, metrics=dict(metrics),
        verified_by="cost-only",
        note="Solo fórmula + contrato. No simulado con el verificador oficial.",
    )


def verify_candidate(spec: CircuitSpec, candidate: dict[str, Any]) -> CircuitVerifyResult:
    """Verifica un candidato dict.

    El candidato trae: task, S (opcional), metrics (dict con los números
    que pide su tarea) y, para química, opcionalmente
    `factorization_path` para la verificación oficial Task 1.
    """
    metrics = dict(candidate.get("metrics", {}))
    if spec.task == "dfthcsos" and candidate.get("factorization_path"):
        return verify_chemistry_factorization(
            candidate["factorization_path"],
            system=candidate.get("system", "FeMoCo76o113e"),
        )
    # Si el candidato ya trae S medido por el verificador oficial, se
    # respeta (viene con `verified_by='official'`); si no, cribado.
    if candidate.get("verified_by") == "official" and candidate.get("S"):
        fails = spec.check_metrics(metrics)
        return CircuitVerifyResult(
            ok=not fails, S=float(candidate["S"]), failures=fails,
            metrics=metrics, verified_by="official",
            note=candidate.get("note", "S medido por el verificador oficial"),
        )
    return _cost_only(spec, metrics)


def verify_chemistry_factorization(
    factorization_path: str | Path, system: str = "FeMoCo76o113e"
) -> CircuitVerifyResult:
    """Verificación OFICIAL Task 1 de una factorización .npz, en local.

    Llama a starter_kit.verifier.score.evaluate_submission, el mismo
    código que Kaggle. Devuelve error_1/error_2 en mHa, Lambda, E_gap,
    lambda_eff y S=lambda_eff (Task 1, sin circuitos).
    """
    path = Path(factorization_path)
    if not path.is_file():
        return CircuitVerifyResult(False, failures=[f"no existe: {path}"],
                                   verified_by="none")
    starter = STARTER_KIT
    if not (starter / "starter_kit/verifier/score.py").is_file():
        return CircuitVerifyResult(
            False, failures=[f"verificador oficial no encontrado en {starter}"],
            verified_by="none")
    # Se ejecuta en el venv (tiene numpy/scipy) como subproceso, para
    # aislar el verificador y no contaminar este proceso.
    code = (
        "import sys, json; "
        f"sys.path.insert(0, {str(starter)!r}); "
        "from starter_kit.verifier.score import evaluate_submission, score_from_metrics, passes_accuracy; "
        f"m = evaluate_submission({system!r}, {str(path)!r}); "
        "print(json.dumps({'error_1': m['error_1'], 'error_2': m['error_2'], "
        "'Lambda': m['Lambda'], 'E_gap': m['E_gap'], 'lambda_eff': m['lambda_eff'], "
        "'gap_in_domain': bool(m['gap_in_domain']), 'passes': bool(passes_accuracy(m)), "
        "'score': float(score_from_metrics(m))}))"
    )
    try:
        r = subprocess.run(
            [str(VENV_PYTHON), "-c", code],
            capture_output=True, text=True, timeout=600,
        )
    except subprocess.TimeoutExpired:
        return CircuitVerifyResult(False, failures=["verificador oficial: timeout > 600 s"],
                                   verified_by="none")
    if r.returncode != 0:
        return CircuitVerifyResult(
            False, failures=["verificador oficial falló: " + r.stderr.strip()[-500:]],
            verified_by="none")
    import json as _json

    try:
        m = _json.loads(r.stdout.strip().splitlines()[-1])
    except Exception as e:
        return CircuitVerifyResult(False, failures=[f"salida ilegible: {e}"],
                                   verified_by="none")
    metrics = {
        "error_1_mHa": m["error_1"] * 1000,
        "error_2_mHa": m["error_2"] * 1000,
        "Lambda": m["Lambda"],
        "E_gap": m["E_gap"],
        "lambda_eff": m["lambda_eff"],
        "gap_in_domain": m["gap_in_domain"],
    }
    spec = CircuitSpec(task="dfthcsos", name="dfthcsos")
    fails = spec.check_metrics(metrics)
    if not m["passes"]:
        fails.append("verificador oficial: passes_accuracy = False")
    return CircuitVerifyResult(
        ok=not fails, S=float(m["lambda_eff"]), failures=fails, metrics=metrics,
        verified_by="official",
        note="Task 1 oficial en local (sin circuitos). S=lambda_eff; "
             "el S completo (lambda_eff*T*Q) requiere Task 3.",
    )


def verify_circuit_file(
    circuit_path: str | Path, task: str,
    shots_per_x: int | None = None, num_shots: int | None = None,
) -> CircuitVerifyResult:
    """Verificación OFICIAL de un .kmb/.kmx con kickmix (invsqrt o DQI).

    CARO por diseño: invsqrt completo son 200,540,928 shots, DQI 102,400.
    Por defecto usa los valores del verificador oficial; para iterar
    rápido se pasa un número de shots reducido y el resultado se marca
    como parcial (verified_by='official-partial'), nunca como PASS total.
    Requiere el venv con kickmix; si no está, devuelve verified=False.
    """
    path = Path(circuit_path)
    if not path.is_file():
        return CircuitVerifyResult(False, failures=[f"no existe: {path}"],
                                   verified_by="none")
    if not VENV_PYTHON.is_file():
        return CircuitVerifyResult(False, failures=["venv con kickmix no encontrado"],
                                   verified_by="none")
    if importlib.util.find_spec("kickmix") is None and not VENV_PYTHON.is_file():
        return CircuitVerifyResult(False, failures=["kickmix no disponible"],
                                   verified_by="none")
    if task == "invsqrt":
        script = COMPETITION_VERIFIERS / "invsqrt/verify_submission_invsqrt.py"
        cmd = [str(VENV_PYTHON), str(script), str(path)]
        if shots_per_x:
            cmd += ["--shots-per-x", str(shots_per_x)]
        full = shots_per_x in (None, 64)
    elif task == "dqi":
        script = COMPETITION_VERIFIERS / "dqi/verify_submission_dqi.py"
        cmd = [str(VENV_PYTHON), str(script), str(path)]
        if num_shots:
            cmd += ["--num-shots", str(num_shots)]
        full = num_shots in (None, 102_400)
    else:
        return CircuitVerifyResult(False, failures=[f"tarea no es circuito: {task}"],
                                   verified_by="none")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    except subprocess.TimeoutExpired:
        return CircuitVerifyResult(False, failures=["verificador oficial: timeout > 3600 s"],
                                   verified_by="none")
    import json as _json

    try:
        out = _json.loads(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "{}")
    except Exception:
        out = {}
    if r.returncode != 0 or out.get("status") != "PASS":
        err = out.get("error") or r.stderr.strip()[-500:]
        return CircuitVerifyResult(False, failures=[f"verificador oficial FAIL: {err}"],
                                   verified_by="official")
    S = float(out.get("score", float("inf")))
    metrics = {"Q": out.get("num_qubits"), "score": S,
               "toffoli_count": out.get("toffoli_count"),
               "verified_shots": out.get("verified_shots")}
    if task == "dqi":
        metrics.update({"eps_plus": out.get("effective_error_rate"),
                        "R": out.get("repetition_factor"),
                        "T": out.get("toffoli_count")})
    return CircuitVerifyResult(
        ok=True, S=S, metrics=metrics,
        verified_by="official" if full else "official-partial",
        note="Verificación oficial completa" if full else
             "Verificación oficial PARCIAL (shots reducidos): no es PASS total.",
    )


class LocalVerifier:
    """Envoltorio con la misma forma que SubprocessVerifier, para el lazo."""

    def __init__(self, spec: CircuitSpec):
        self.spec = spec

    def verify(self, candidate: dict[str, Any]) -> CircuitVerifyResult:
        return verify_candidate(self.spec, candidate)

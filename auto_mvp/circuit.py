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
VERIFIER_DQI = _CIRCUITS / "verifiers" / "verify_submission_dqi.py"
VERIFIERS_DIR = _CIRCUITS / "verifiers"
DFTHCSOS_DIR = VERIFIERS_DIR / "dfthcsos"
FCIDUMP_NAME = "FeMoCo76o113e.fcidump"

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


def _load_verifier_dqi():
    """El verificador oficial DQI vendido en el repo, como módulo."""
    try:
        import numpy  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "numpy no disponible en este entorno: el verificador "
            f"oficial lo necesita ({exc})") from exc
    _require_kickmix()
    spec = importlib.util.spec_from_file_location(
        "verify_submission_dqi", str(VERIFIER_DQI))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"no se puede cargar {VERIFIER_DQI}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["verify_submission_dqi"] = mod
    spec.loader.exec_module(mod)
    return mod


def _file_sha256(path: str | Path) -> str:
    """SHA-256 de un archivo en disco, por bloques."""
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fast_verify_dqi(path: str | Path, *, num_shots: int = 2048,
                    batch_size: int = 256, seed: int | None = None,
                    salt: str = "") -> dict[str, Any]:
    """Verificación RÁPIDA de un circuito DQI, protocolo oficial.

    Mismo chequeo y mismo costo que el verificador oficial, con menos
    shots (2,048 por defecto: con 256 shots el verificador aborta
    aunque haya 0 errores, eps+ = 0.2929 > 1/16). La semilla V1
    (dqi_v1_logm7.kmb) pasa en ~37 s con eps+ = 0.0424.

    UNA DIFERENCIA HONESTA: el verificador oficial hashea el circuito
    re-serializándolo a .kmb en memoria (``to_file``), y eso FALLA en
    el venv de sandbox para circuitos tamaño DQI (86M instrucciones,
    kickmix 1.0.0; no es memoria ni disco). Aquí el hash se toma del
    ARCHIVO .kmb en disco: para un .kmb es el MISMO hash canónico
    (comprobado: sha256 de dqi_v1_logm7.kmb = a260f79a..., el hash
    oficial del v1-verify). Para un .kmx se hashea el archivo .kmx
    (el hash solo elige qué casos de prueba aleatorios se sortean;
    la validez y el costo no dependen de él). La certificación final
    de un ganador corre el verificador oficial completo (en Kaggle,
    donde el hash sí funciona).
    """
    import numpy as np

    if int(num_shots) % int(batch_size) != 0:
        raise ValueError(
            f"num_shots ({num_shots}) debe ser múltiplo de batch_size "
            f"({batch_size})")
    mod = _load_verifier_dqi()
    path = Path(path)
    try:
        circuit = load_circuit(path)
    except Exception as exc:  # noqa: BLE001 - no es un circuito
        return {"valid": False, "S": None, "reason": f"no carga: {exc}"[:300]}
    circuit_hash = _file_sha256(path)
    spec = mod.ProblemSpecDQI.benchmark_instance(num_shots=int(num_shots))
    try:
        stats = circuit.operation_statistics()
        if "Z_POW" in stats:
            raise ValueError("Z_POW gates are not allowed in Benchmark II.")
        syndrome_qubits, mbuc_bits, ancilla_qubits = mod.validate_registers(
            circuit, spec)
    except (AssertionError, ValueError) as exc:
        return {"valid": False, "S": None, "reason": str(exc)[:300]}
    try:
        weight_probs = mod.optimal_dqi_weights(
            spec.m, spec.max_errors, spec.degree, spec.r) ** 2
        km = _require_kickmix()
        tables = mod.FieldTables(km.GF2Field(spec.degree))
        base_seed = (int(seed) if seed is not None
                     else mod._initial_seed(circuit_hash, salt))
        syndrome_array = km.array(syndrome_qubits)
        mbuc_array = km.array(mbuc_bits)
        n_batches = (int(num_shots) + int(batch_size) - 1) // int(batch_size)
        seeds = np.random.SeedSequence(
            base_seed, pool_size=8).generate_state(
                8 * n_batches, dtype=np.uint64).reshape(-1, 2, 4)
        value_errors = 0
        phase_errors = 0
        toffoli_total = 0
        for i, start in enumerate(range(0, int(num_shots), int(batch_size))):
            rng = np.random.default_rng(
                int.from_bytes(seeds[i, 0], "little"))
            syndromes, mbuc, phases = mod.sample_shots(
                spec, tables, rng, int(batch_size), weight_probs)
            sim = km.Simulator(batch_size=int(batch_size), debug_print=False,
                               counting_operations=True,
                               seed=int.from_bytes(seeds[i, 1], "little"))
            sim.use_same_registers_as(circuit)
            input_syndromes = mod.to_bits(syndromes, spec.degree)
            sim.write_across_shots(syndrome_array, input_syndromes)
            sim.write_across_shots(mbuc_array, mod.to_bits(mbuc, spec.degree))
            sim.do(circuit)
            phase_flipped = sim.read_phase_flipped_across_shots()
            reg_diff = sim.read_across_shots(syndrome_array) ^ input_syndromes
            junk = (sim.read_across_shots(ancilla_qubits)
                    if len(ancilla_qubits)
                    else np.zeros((0, int(batch_size)), dtype=bool))
            val_err = reg_diff.any(axis=0) | junk.any(axis=0)
            phase_err = (phase_flipped ^ phases) & ~val_err
            value_errors += int(val_err.sum())
            phase_errors += int(phase_err.sum())
            toffoli_total += int(
                sim.operation_statistics().num_toffoli_like)
    except (AssertionError, ValueError) as exc:
        return {"valid": False, "S": None, "reason": str(exc)[:300]}
    total_errors = value_errors + phase_errors
    eps_plus = mod.clopper_pearson_upper_bound(
        total_errors, int(num_shots), log2_delta=mod.DEFAULT_LOG2_DELTA)
    if eps_plus >= 1 / 16:
        return {"valid": False, "S": None,
                "reason": (f"eps+ {eps_plus:.4f} >= 1/16 "
                           f"(errores {total_errors}/{num_shots})")[:300]}
    rep_factor = mod.repetition_overhead(eps_plus)
    toffolis = toffoli_total / int(num_shots)
    score = rep_factor * (int(circuit.num_qubits) ** 2) * toffolis
    return {
        "valid": True,
        "S": float(score),
        "toffoli_count": float(toffolis),
        "eps_plus": float(eps_plus),
        "repetition_factor": float(rep_factor),
        "value_errors": value_errors,
        "phase_errors": phase_errors,
        "qubits": int(circuit.num_qubits),
        "verified_shots": int(num_shots),
        "reason": "",
    }


def _dfthcsos_search_dirs(dataset_dir: str | Path | None = None
                          ) -> list[Path]:
    """Dónde buscar el fcidump fuera del repo (dataset de la competencia)."""
    roots: list[Path] = []
    if dataset_dir is not None:
        roots.append(Path(dataset_dir))
    roots.extend([
        Path.home() / "workspace/sandbox-run/competition-kit/verifiers/dfthcsos",
        Path("/kaggle/input"),
    ])
    return roots


def ensure_dfthcsos_reference_data(dataset_dir: str | Path | None = None
                                   ) -> Path:
    """El fcidump de referencia (128 MB) para el verificador de química.

    NO cabe en el repo: viene del dataset de la competencia. Si el
    dir vendido no lo tiene, se busca en el dataset y se enlaza
    (symlink) en runtime. El fixed_shifts.npz (61 KB) sí está vendido.
    """
    target = DFTHCSOS_DIR / FCIDUMP_NAME
    if target.is_file():
        return target
    candidates = _dfthcsos_search_dirs(dataset_dir)
    found = None
    for base in candidates:
        direct = base / "verifiers/dfthcsos" / FCIDUMP_NAME
        if direct.is_file():
            found = direct
            break
        if base.is_dir():
            hits = list(base.rglob(f"verifiers/dfthcsos/{FCIDUMP_NAME}"))
            if hits:
                found = hits[0]
                break
            direct2 = base / FCIDUMP_NAME
            if direct2.is_file():
                found = direct2
                break
    if found is None:
        raise RuntimeError(
            "FeMoCo76o113e.fcidump (128 MB) no está en el repo ni en el "
            "dataset: el verificador de química lo necesita; pasa "
            "--dataset con la ruta del kit de la competencia")
    try:
        target.symlink_to(found)
    except FileExistsError:
        pass
    return target


def fast_verify_dfthcsos(circuits: str | Path, factorization: str | Path,
                         *, shots_per_address: int = 1, seed: int = 1,
                         dataset_dir: str | Path | None = None
                         ) -> dict[str, Any]:
    """Verificación RÁPIDA de una submission de química, protocolo oficial.

    Usa el verificador oficial vendido (dfthcsos/verify.py +
    scoreinfra). El score sale de simular los circuitos ANGLE_k y de
    las métricas de la factorización (lambda_eff * T_total * Q_total).
    Con shots_per_address=1 tarda ~28 s y reproduce el S de
    referencia exacto (3,355,599,588.3) sobre el sample_submission.
    Si el verificador rechaza la submission, es INVÁLIDA: no cuenta.
    """
    ensure_dfthcsos_reference_data(dataset_dir)
    if str(VERIFIERS_DIR) not in sys.path:
        sys.path.insert(0, str(VERIFIERS_DIR))
    try:
        from dfthcsos.verify import verify as dfthcsos_verify
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "no se puede importar el verificador de química vendido "
            f"en el repo ({exc})") from exc
    try:
        res = dfthcsos_verify(str(circuits), str(factorization),
                              shots_per_address=int(shots_per_address),
                              seed=int(seed))
    except Exception as exc:  # noqa: BLE001 - el verificador la rechaza
        return {"valid": False, "S": None, "reason": str(exc)[:300]}
    return {
        "valid": True,
        "S": float(res["score"]),
        "lambda_eff": float(res["lambda_eff"]),
        "toffoli_count": float(res["toffoli_count"]),
        "num_circuits": int(res["num_circuits"]),
        "num_qubits": int(res["num_qubits"]),
        "verified_shots": int(res["verified_shots"]),
        "reason": "",
    }


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

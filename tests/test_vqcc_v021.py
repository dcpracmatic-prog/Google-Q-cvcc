"""Pruebas del harness VQCC v0.2.1-vqcc (mejoras DSP).

1. Calibración de arranque: la sonda deriva margen, paciencia y
   presupuesto; el caché devuelve la misma calibración sin re-medir;
   sonda vacía o con S inválido falla visible.
2. Detector con margen: una baja menor que el margen no cuenta como
   mejora; los S no finitos no entran al historial; la salud solo
   existe con >= 3 puntos y está en [0, 1].
3. Veto de salud / fallos seguidos: el modo baja AUTO->PROPOSE->SHADOW
   y queda en el ledger; en PROPOSE la mejora queda pendiente sin
   aplicar; en SHADOW no cambia nada; el mejor verificado oficial
   vive aparte del proyectado.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auto_mvp.healing.heal import Autonomy

from auto_mvp.vqcc import (
    Calibration, CircuitDetector, SearchLoop, VQCCLedger, __version__,
    calibrate, calibrate_from_candidates, clear_calibration_cache,
    dfthcsos_spec, dqi_spec,
)
from auto_mvp.vqcc.verify import LocalVerifier


def _chem_candidate(name, lambda_eff, Ttot, Qtot, error_2_mHa=15.0,
                    verified_by=None, S=None):
    cand = {
        "name": name,
        "metrics": {
            "lambda_eff": lambda_eff, "Ttot": Ttot, "Qtot": Qtot,
            "error_1_mHa": 0.0, "error_2_mHa": error_2_mHa,
            "Lambda": 300.0, "E_gap": 3.96, "angles_qubits": 120,
        },
    }
    if verified_by:
        cand["verified_by"] = verified_by
    if S is not None:
        cand["S"] = S
    return cand


class SequenceMutator:
    def __init__(self, candidates):
        self.candidates = list(candidates)
        self.i = 0

    def propose(self, spec, best, evidence):
        cand = self.candidates[min(self.i, len(self.candidates) - 1)]
        self.i += 1
        return cand


def test_calibracion_sonda_estable():
    clear_calibration_cache()
    spec = dqi_spec()  # baseline_S = 1.99836e13
    # Sonda: baseline + 4 vecinos de un solo nodo (como la tabla del
    # Notebook 1). |ΔS|/S: 0, 0.0241, 0.0258, 0.0494, 0.0509 ->
    # p95 lineal = 0.0494*0.2 + 0.0509*0.8 = 0.0506.
    probes = [1.99836e13, 2.05e13, 1.95e13, 2.10e13, 1.90e13]
    cal = calibrate(spec, probes)
    assert abs(cal.margin - 0.0506) < 0.001, cal.margin
    assert cal.regime == "ESTABLE", cal.regime
    assert cal.noise_factor < 0.01, cal.noise_factor
    assert cal.stagnation_limit == 5, cal.stagnation_limit
    assert cal.max_trials == 20, cal.max_trials
    assert cal.n_probes == 5
    assert set(cal.signature) == {"C", "B", "G", "A_adapt"}
    assert all(0.0 <= v <= 1.0 for v in cal.signature.values())
    print("calibración estable OK: margin=%.4f regime=%s paciencia=%d "
          "intentos=%d" % (cal.margin, cal.regime,
                           cal.stagnation_limit, cal.max_trials))


def test_calibracion_regimenes_y_cache():
    clear_calibration_cache()
    spec = dqi_spec()
    base = 1.99836e13
    # MODERADO: 19 sondas en el baseline y una cola a 3.0e13.
    probes_mod = [base] * 19 + [3.0e13]
    cal_mod = calibrate(spec, probes_mod)
    assert cal_mod.regime == "MODERADO", cal_mod
    assert cal_mod.stagnation_limit == 8, cal_mod.stagnation_limit
    assert cal_mod.max_trials == 32, cal_mod.max_trials
    # RUIDOSO: la misma sonda con la cola a 10e13.
    probes_noisy = [base] * 19 + [10.0e13]
    cal_noisy = calibrate(spec, probes_noisy)
    assert cal_noisy.regime == "RUIDOSO", cal_noisy
    assert cal_noisy.stagnation_limit == 14, cal_noisy.stagnation_limit
    assert cal_noisy.max_trials == 57, cal_noisy.max_trials
    # Caché: la misma sonda devuelve el mismo objeto sin re-medir.
    again = calibrate(spec, probes_mod)
    assert again is cal_mod
    forced = calibrate(spec, probes_mod, force=True)
    assert forced is not cal_mod
    assert forced.margin == cal_mod.margin
    print("regímenes y caché OK: MODERADO paciencia=8 intentos=32, "
          "RUIDOSO paciencia=14 intentos=57")


def test_calibracion_falla_visible():
    clear_calibration_cache()
    spec = dqi_spec()
    for bad in ([], [1.99836e13, float("inf")], [1.99836e13, -5.0],
                [1.99836e13, float("nan")]):
        try:
            calibrate(spec, bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"la sonda {bad} debió fallar visible")
    # calibrate_from_candidates: un candidato que rompe el contrato
    # no entra a la sonda, aunque su fórmula dé un S finito.
    verifier = LocalVerifier(spec)
    chem = dfthcsos_spec()
    bad_cand = _chem_candidate("mala", 40.0, 80_000, 700, error_2_mHa=25.0)
    try:
        calibrate_from_candidates(chem, [bad_cand], LocalVerifier(chem))
    except ValueError:
        pass
    else:
        raise AssertionError("la sonda con candidato inválido debió fallar")
    good = [_chem_candidate("a", 45.0, 90_000, 740),
            _chem_candidate("b", 44.0, 88_000, 730)]
    cal = calibrate_from_candidates(chem, good, LocalVerifier(chem))
    assert cal.n_probes == 2 and cal.task == "dfthcsos"
    print("calibración falla visible OK: sonda vacía/inválida y "
          "candidato que rompe el contrato rechazan")


def test_detector_margen_y_mediana():
    spec = dqi_spec()
    base = spec.baseline_S
    det = CircuitDetector(spec, stagnation_limit=5, margin=0.01)
    # 0.42% mejor: con margen 1% NO es mejora.
    obs = det.observe(base * 0.9958, [])
    assert not obs["improved"] and obs["trials_since_improvement"] == 1
    # 1.42% mejor: sí es mejora.
    obs = det.observe(base * 0.9858, [])
    assert obs["improved"] and obs["trials_since_improvement"] == 0
    # Con margen 0 (viejo comportamiento), cualquier baja cuenta.
    det0 = CircuitDetector(spec, stagnation_limit=5, margin=0.0)
    assert det0.observe(base * 0.9999, [])["improved"]
    # Mediana móvil: ignora inf/NaN/negativos.
    det2 = CircuitDetector(spec, stagnation_limit=5)
    det2.observe(float("inf"), ["dqi: eps+ = 0.07 >= 1/16"])
    det2.observe(float("nan"), [])
    det2.observe(-3.0, [])
    assert det2.median_S is None, det2.median_S
    det2.observe(4.0e9, [])
    det2.observe(6.0e9, [])
    assert det2.median_S == 5.0e9, det2.median_S
    print("detector margen/mediana OK: 0.42%% no mejora con margen 1%%, "
          "1.42%% sí; inf/nan fuera del historial")


def test_detector_salud():
    spec = dqi_spec()
    det = CircuitDetector(spec)
    assert det.health() is None  # menos de 3 puntos: no hay salud
    det.observe(2.0e13, [])
    det.observe(2.1e13, [])
    assert det.health() is None
    det.observe(1.9e13, [])
    h = det.health()
    assert h is not None and 0.0 <= h["health"] <= 1.0, h
    assert set(h["signature"]) == {"C", "B", "G", "A_adapt"}
    print("salud OK: con 3 puntos health=%.3f" % h["health"])


def test_veto_por_fallos_seguidos():
    spec = dqi_spec()
    # Candidato que siempre rompe el contrato (eps+ 0.07 >= 1/16).
    bad = {"name": "malo", "metrics": {"Q": 1899, "T": 4_652_027,
                                       "eps_plus": 0.07}}
    loop = SearchLoop(spec, SequenceMutator([bad]), ledger=VQCCLedger(),
                      max_trials=6, stagnation_limit=5)
    res = loop.run()
    assert res.autonomy == "propose", res.autonomy
    assert len(res.mode_transitions) == 1, res.mode_transitions
    assert res.mode_transitions[0]["from"] == "auto"
    assert res.mode_transitions[0]["to"] == "propose"
    assert "mode_transition" in res.ledger_events
    assert res.best_S == spec.baseline_S  # el mejor no se tocó
    print("veto por fallos OK: AUTO->PROPOSE a los 3 fallos seguidos, "
          "best_S intacto")


def test_modos_propose_y_shadow():
    spec = dfthcsos_spec()
    good = _chem_candidate("brot12-J7", 45.0, 90_000, 740)  # S=2.997e9
    for mode, want_proposed in [(Autonomy.PROPOSE, True),
                                (Autonomy.SHADOW, False)]:
        loop = SearchLoop(spec, SequenceMutator([good]),
                          ledger=VQCCLedger(), max_trials=1,
                          autonomy=mode)
        res = loop.run()
        assert res.accepted == 0, (mode, res.accepted)
        assert res.best is None and res.best_S == spec.baseline_S
        if want_proposed:
            assert res.proposed is not None
            assert res.proposed["name"] == "brot12-J7"
            assert "proposed" in res.ledger_events
        else:
            assert res.proposed is None
    print("modos OK: PROPOSE deja la mejora pendiente sin aplicar, "
          "SHADOW no cambia nada")


def test_mejor_verificado_aparte():
    spec = dfthcsos_spec()
    # Primero una mejora solo-costo, luego una oficial.
    cost_only = _chem_candidate("brot12-J7", 45.0, 90_000, 740)
    official = _chem_candidate("brot11-J8", 44.0, 88_000, 730,
                               verified_by="official", S=2_826_560_000)
    loop = SearchLoop(spec, SequenceMutator([cost_only, official]),
                      ledger=VQCCLedger(), max_trials=2)
    res = loop.run()
    assert res.accepted == 2, res
    assert abs(res.best_S - 2_826_560_000) < 1, res.best_S
    # El mejor verificado solo lo mueve lo oficial, no el cribado.
    assert abs(res.best_verified_S - 2_826_560_000) < 1, res.best_verified_S
    loop2 = SearchLoop(spec, SequenceMutator([cost_only]),
                       ledger=VQCCLedger(), max_trials=1)
    res2 = loop2.run()
    assert math.isinf(res2.best_verified_S), res2.best_verified_S
    print("mejor verificado OK: solo-costo no corona, oficial sí")


def test_calibracion_manda_en_el_lazo():
    clear_calibration_cache()
    spec = dfthcsos_spec()
    base = spec.baseline_S
    # Sonda ruidosa: 19 en baseline, una cola a 10x.
    probes = [base] * 19 + [base * 10.0]
    cal = calibrate(spec, probes)
    assert cal.regime == "RUIDOSO"
    loop = SearchLoop(spec, SequenceMutator([]), ledger=VQCCLedger(),
                      calibration=cal)
    assert loop.detector.margin == cal.margin
    assert loop.detector.stagnation_limit == cal.stagnation_limit
    assert loop.max_trials == cal.max_trials
    assert __version__ == "0.2.1-vqcc", __version__
    print("calibración manda en el lazo OK: margin=%.4f paciencia=%d "
          "intentos=%d" % (cal.margin, cal.stagnation_limit,
                           cal.max_trials))


if __name__ == "__main__":
    test_calibracion_sonda_estable()
    test_calibracion_regimenes_y_cache()
    test_calibracion_falla_visible()
    test_detector_margen_y_mediana()
    test_detector_salud()
    test_veto_por_fallos_seguidos()
    test_modos_propose_y_shadow()
    test_mejor_verificado_aparte()
    test_calibracion_manda_en_el_lazo()
    print("TODO OK: 9/9 pruebas v0.2.1 pasaron")

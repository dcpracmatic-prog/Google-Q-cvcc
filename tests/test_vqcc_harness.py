"""Pruebas del harness VQCC v0.2.0-vqcc.

1. Las fórmulas S reproducen los números medidos (DQI y química).
2. Los contratos rechazan lo que el verificador oficial rechaza.
3. El lazo acepta la mejora, descarta la que empeora y la que rompe
   invariantes, y hace rollback al mejor (sin tocar el mejor).
4. Verificación OFICIAL real en local, Task 1 química, baseline .npz:
   lambda_eff 49.254686, error_2 16.133 mHa (medido, ~30 s).
"""
import os
from pathlib import Path

import pytest
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auto_mvp.vqcc import (
    CircuitDetector, SearchLoop, VQCCLedger, __version__,
    dfthcsos_spec, dqi_spec, invsqrt_spec,
    s_chem, s_dqi, s_invsqrt,
)
from auto_mvp.vqcc.verify import LocalVerifier, verify_chemistry_factorization

BASELINE_NPZ = (
    "/home/hatch/workspace/sandbox-run/starter-kit/"
    "starter_kit/starter/task1_factorization/FeMoco76_65_60_60.npz"
)


def test_costs_reproducen_medidos():
    # DQI Toom-3+V1+E2 medido: Q=1,899, T=4,652,027, eps+=0.000866,
    # R=1.1912605, S=1.99836e13
    s = s_dqi(1899, 4_652_027, 0.0008660587301657926)
    assert abs(s / 1.99836e13 - 1) < 0.001, s
    # Química baseline (65,60,60): lambda 49.301369, Ttot 93,237, Qtot 730
    s = s_chem(49.301369, 93_237, 730)
    assert abs(s / 3_355_599_588.32 - 1) < 0.001, s
    # invsqrt: fórmula simple, Q*C con C=Toffoli+T/4
    assert s_invsqrt(62, 1500, 488) == 62 * (1500 + 488 / 4)
    print("costs OK: DQI S=%.4g chem S=%.4g" % (
        s_dqi(1899, 4_652_027, 0.0008660587301657926),
        s_chem(49.301369, 93_237, 730)))


def test_contracts():
    dqi = dqi_spec()
    assert dqi.check_metrics({"eps_plus": 0.000866, "Q": 1899}) == []
    assert dqi.check_metrics({"eps_plus": 0.07, "Q": 1899}) != []
    chem = dfthcsos_spec()
    ok = {"error_1_mHa": 0.0, "error_2_mHa": 18.6, "Lambda": 308.4,
          "E_gap": 3.96, "angles_qubits": 120}
    assert chem.check_metrics(ok) == []
    bad = dict(ok, error_2_mHa=25.0)
    assert any("error_2" in f for f in chem.check_metrics(bad))
    bad2 = dict(ok, Lambda=48.0)
    assert any("Lambda" in f for f in chem.check_metrics(bad2))
    bad3 = dict(ok, angles_qubits=130)
    assert any("128" in f for f in chem.check_metrics(bad3))
    inv = invsqrt_spec()
    assert inv.check_metrics({"Q": 62, "C": 1622}) == []
    print("contracts OK: DQI eps+>=1/16, química error>20mHa / Lambda<=49 / Q>128 rechazan")


def _chem_candidate(name, lambda_eff, Ttot, Qtot, error_2_mHa=15.0):
    return {
        "name": name, "mutation": name,
        "metrics": {
            "lambda_eff": lambda_eff, "Ttot": Ttot, "Qtot": Qtot,
            "error_1_mHa": 0.0, "error_2_mHa": error_2_mHa,
            "Lambda": 300.0, "E_gap": 4.0, "angles_qubits": 120,
        },
        "params": {"lambda_eff": lambda_eff, "Ttot": Ttot, "Qtot": Qtot},
    }


class SequenceMutator:
    def __init__(self, candidates):
        self.candidates = candidates
        self.i = 0

    def propose(self, spec, best, evidence):
        c = self.candidates[self.i % len(self.candidates)]
        self.i += 1
        return c


def test_search_acepta_mejora_descarta_resto():
    spec = dfthcsos_spec()  # baseline_S = 3,355,599,588.32
    candidates = [
        # Mejora: S = 45 * 90,000 * 740 = 2,997,000,000
        _chem_candidate("brot12-J7", 45.0, 90_000, 740),
        # Empeora: S = 50 * 95,000 * 730 = 3,467,500,000
        _chem_candidate("brot14-J9", 50.0, 95_000, 730),
        # Rompe invariante: error_2 25 mHa
        _chem_candidate("mala-factorizacion", 40.0, 80_000, 700, error_2_mHa=25.0),
        # Mejora más: S = 44 * 88,000 * 730 = 2,826,560,000
        _chem_candidate("brot11-J8", 44.0, 88_000, 730),
    ]
    loop = SearchLoop(spec, SequenceMutator(candidates),
                      ledger=VQCCLedger(), max_trials=4)
    res = loop.run()
    assert res.accepted == 2, res
    assert res.rejected == 2, res
    assert abs(res.best_S - 2_826_560_000) < 1, res.best_S
    assert res.best["name"] == "brot11-J8"
    assert "rolled_back" in res.ledger_events
    assert res.ledger_events.count("trial") == 4
    print("search OK: accepted=2 rejected=2 best_S=%.4g (%s)" % (
        res.best_S, res.best["name"]))


def test_detector_estancamiento():
    spec = dfthcsos_spec()
    det = CircuitDetector(spec, stagnation_limit=3)
    for _ in range(2):
        obs = det.observe(4e9, [])  # pasa contrato pero no mejora
        assert not obs["stagnated"]
    obs = det.observe(4e9, [])
    assert obs["stagnated"] and obs["trials_since_improvement"] == 3
    print("detector OK: estancamiento a los 3 intentos sin mejorar")


def _baseline_npz():
    # v2.17.11: el .npz baseline vive en el sandbox; en Kaggle se busca
    # en la entrada de la competencia. Si no está en ningún lado, el test
    # se salta (es una verificación oficial LOCAL, no un fallo del repo).
    cands = [Path(BASELINE_NPZ)]
    kaggle_in = Path("/kaggle/input")
    if kaggle_in.exists():
        cands += sorted(kaggle_in.rglob("FeMoco76_65_60_60.npz"))
    for c in cands:
        if c.is_file():
            return c
    return None


def test_verificacion_oficial_quimica_baseline():
    npz = _baseline_npz()
    if npz is None:
        pytest.skip("sin el .npz baseline de FeMoCo (solo en local)")
    from auto_mvp.vqcc.verify import STARTER_KIT
    if not (STARTER_KIT / "starter_kit/verifier/score.py").is_file():
        pytest.skip("sin el verificador oficial del starter kit (solo en local)")
    r = verify_chemistry_factorization(npz)
    assert r.verified_by == "official", r
    assert r.ok, r.failures
    assert abs(r.metrics["lambda_eff"] - 49.254686) < 0.001, r.metrics
    assert abs(r.metrics["error_2_mHa"] - 16.1332) < 0.01, r.metrics
    assert abs(r.metrics["error_1_mHa"]) < 0.01, r.metrics
    print("oficial química OK: lambda_eff=%.6f error_2=%.4f mHa "
          "Lambda=%.3f E_gap=%.4f" % (
              r.metrics["lambda_eff"], r.metrics["error_2_mHa"],
              r.metrics["Lambda"], r.metrics["E_gap"]))


if __name__ == "__main__":
    test_costs_reproducen_medidos()
    test_contracts()
    test_search_acepta_mejora_descarta_resto()
    test_detector_estancamiento()
    test_verificacion_oficial_quimica_baseline()
    print("TODO OK: 5/5 pruebas VQCC pasaron (v%s)" % __version__)

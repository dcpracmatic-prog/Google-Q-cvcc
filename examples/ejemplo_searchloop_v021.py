"""Ejemplo: probar el corrector v0.2.1-vqcc con datos reales del Notebook 1.

La sonda son los 13 nodos de un solo cambio de la tabla del Notebook 1
(MORPH SearchLoop, INFORME.md), con su Q/T medidos o modelados y
eps+ = 0.001188 (R = 1.22901, Gate 0). El baseline del lazo es la base
BM+Forney, S = 3.714e12 (Q=1,414, T=1,511,522).

El ejemplo muestra, en orden:
1. La calibración con la sonda ANCHA (13 nodos, mezcla nodos buenos y
   desastres como A_mult_school y E_overflow_sto): el margen sale
   capado en 25% y la mejora real del 13.9% NO cuenta. Lección: la
   sonda debe parecerse a la carga, como el micro-benchmark del DSP.
2. La calibración con la sonda del VECINDARIO (9 nodos a menos de 15%
   del baseline): margen 11.5%. La combinación ganadora del MIS
   (L+D+G_b17, S=3.197e12) SÍ se acepta; una micro-mejora de 0.28%
   después NO cuenta, por el margen.
3. El veto: 3 candidatos que rompen el contrato seguidos bajan el modo
   AUTO -> PROPOSE, y el mejor queda intacto.
4. La sonda rechaza visible un candidato que rompe el contrato
   (b=36 sin arreglo de cero, eps+ 0.107): calibrate_from_candidates
   levanta ValueError en vez de calibrar con basura.

Todo es cribado de costo (proyección), no verificación oficial.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auto_mvp.healing.heal import Autonomy

from auto_mvp.vqcc import (
    Calibration, SearchLoop, VQCCLedger, calibrate,
    calibrate_from_candidates, clear_calibration_cache,
)
from auto_mvp.vqcc.contracts import CircuitSpec
from auto_mvp.vqcc.costs import s_dqi
from auto_mvp.vqcc.verify import LocalVerifier

EPS = 0.001188  # R = 1.22901 (Gate 0, 20,000 shots)
BASE_S = 3.714e12  # base BM+Forney: Q=1,414, T=1,511,522


def spec_bm():
    return CircuitSpec(task="dqi", name="dqi-bm-base",
                       baseline_S=BASE_S,
                       intent="Ejemplo: base BM+Forney como punto de partida.")


def cand(name, Q, T, eps=EPS):
    return {"name": name, "metrics": {"Q": Q, "T": T, "eps_plus": eps}}


# Tabla de un solo nodo del Notebook 1 (Q, T de INFORME.md).
NODOS = [
    ("A_mult_school", 1414, 2_327_579),
    ("B_inv_315", 1414, 1_520_972),
    ("C_ptr_8", 1419, 1_511_522),
    ("D_nab_6", 1412, 1_511_522),
    ("E_overflow_sto", 1822, 1_458_827),
    ("F_chien_unpack", 1499, 1_511_522),
    ("G_b17", 1414, 1_315_731),
    ("H_b4", 1414, 1_377_588),
    ("I_b36", 1448, 1_305_698),
    ("J_flip36", 1414, 1_368_966),
    ("L_mbuc_clear", 1414, 1_500_497),
    ("M_lupdate", 1414, 1_511_137),
]


class SequenceMutator:
    def __init__(self, candidates):
        self.candidates = list(candidates)
        self.i = 0

    def propose(self, spec, best, evidence):
        c = self.candidates[min(self.i, len(self.candidates) - 1)]
        self.i += 1
        return c


def main():
    clear_calibration_cache()
    spec = spec_bm()
    verifier = LocalVerifier(spec)
    print("Baseline BM+Forney: S=%.4g (Q=1,414, T=1,511,522, R=1.22901)" % BASE_S)

    # 1. Sonda ancha: los 12 nodos válidos (K_b36_nofix se excluye: rompe
    # el contrato, eps+ 0.107, y la sonda lo rechazaría; se prueba en 4).
    ancha = [cand(n, q, t) for n, q, t in NODOS]
    cal_ancha = calibrate_from_candidates(spec, ancha, verifier)
    print("\n[1] Sonda ANCHA (%d nodos): margin=%.4f (tope 0.25), "
          "régimen=%s, paciencia=%d, intentos=%d"
          % (cal_ancha.n_probes, cal_ancha.margin, cal_ancha.regime,
             cal_ancha.stagnation_limit, cal_ancha.max_trials))
    print("    La mejora del MIS (13.9%%) es MENOR que el margen: "
          "con esta sonda no contaría como mejora.")

    # 2. Sonda del vecindario: nodos a menos de 15% del baseline.
    vecinos = [c for c in ancha
               if abs(verifier.verify(c).S - BASE_S) / BASE_S < 0.15]
    cal_vec = calibrate_from_candidates(spec, vecinos, verifier, force=True)
    print("\n[2] Sonda VECINDARIO (%d nodos): margin=%.4f, régimen=%s, "
          "paciencia=%d, intentos=%d"
          % (cal_vec.n_probes, cal_vec.margin, cal_vec.regime,
             cal_vec.stagnation_limit, cal_vec.max_trials))

    mis = cand("L_mbuc_clear+D_nab_6+G_b17", 1412, 1_304_706)
    micro = cand("micro-mejora-0.28pct", 1412, 1_301_500)
    print("    MIS S=%.4g (%.1f%% mejor que base)"
          % (s_dqi(1412, 1_304_706, EPS),
             100 * (1 - s_dqi(1412, 1_304_706, EPS) / BASE_S)))
    print("    micro S=%.4g (%.2f%% mejor que el MIS)"
          % (s_dqi(1412, 1_301_500, EPS),
             100 * (1 - s_dqi(1412, 1_301_500, EPS)
                    / s_dqi(1412, 1_304_706, EPS))))
    # max_trials=2 explícito: solo importan los dos intentos del ejemplo
    # (la calibración ya fijó margen y paciencia, que sí se usan).
    loop = SearchLoop(spec, SequenceMutator([mis, micro]),
                      ledger=VQCCLedger(), calibration=cal_vec,
                      max_trials=2)
    res = loop.run()
    print("    Lazo: intentos=%d aceptados=%d rechazados=%d "
          "best_S=%.4g estancado=%s"
          % (res.trials, res.accepted, res.rejected, res.best_S,
             res.stagnated))
    assert res.accepted == 1 and res.rejected == 1, res
    assert abs(res.best_S - s_dqi(1412, 1_304_706, EPS)) < 1, res.best_S

    # 3. Veto: 3 candidatos que rompen el contrato seguidos.
    malo = cand("b36-sin-arreglo", 1448, 1_294_673, eps=0.107)
    loop2 = SearchLoop(spec, SequenceMutator([malo]),
                       ledger=VQCCLedger(), max_trials=6)
    res2 = loop2.run()
    print("\n[3] Veto por 3 fallos seguidos: modo final=%s, "
          "transiciones=%d, best_S intacto=%.4g"
          % (res2.autonomy, len(res2.mode_transitions), res2.best_S))
    assert res2.autonomy == "propose", res2.autonomy
    assert res2.best_S == BASE_S

    # 4. La sonda rechaza visible el candidato que rompe el contrato.
    try:
        calibrate_from_candidates(spec, [malo], verifier, force=True)
    except ValueError as e:
        print("\n[4] Sonda con b36-sin-arreglo: ValueError (falla visible):")
        print("    %s" % str(e)[:160])
    else:
        raise AssertionError("la sonda debió rechazar el candidato inválido")

    print("\nTODO OK: ejemplo v0.2.1 completo con datos del Notebook 1")


if __name__ == "__main__":
    main()

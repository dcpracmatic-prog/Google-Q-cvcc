"""Ejemplo AUTO_MVP v0.3.0: el ciclo completo con un caso real.

Usa los números del Notebook 1 (BM+Forney DQI): base S=3.714e12,
mejora MIS S=3.197e12, y una regresión con forma de paso 51 (mejor S
proyectado, sigma roto) que el filtro de integridad debe vetar.

Todo es cribado por costo + integridad: ningún S aquí es medido por
el verificador oficial. Corre con: python3 examples/ejemplo_auto_mvp_v030.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auto_mvp import AutoMvp, Goal, MetadataProxy, canonical_hash
from auto_mvp.vqcc import dqi_spec
from auto_mvp.vqcc.costs import s_dqi

EPS = 0.001188
BASE_S = 3.714e12


def evidence_ok():
    sigma = [2314, 1897, 1246, 3162]
    return {
        "kind": "circuit", "sigma": sigma,
        "sigma_ref_hash": canonical_hash(sigma),
        "c_restored": 180, "b_restored": 180, "total_coef": 180,
        "dreg_zero": True, "alpha_zero": True,
        "temporaries_zero": 0, "temporaries_total": 0,
        "allowed_dirty": {}, "shots": 5, "verified_by": "gu_trace",
    }


class Guion:
    """Proponente guionado: MIS, regresión paso 51, variante enorme."""

    def __init__(self):
        self.n = 0

    def propose(self, spec, best, evidence):
        self.n += 1
        if self.n == 1:
            return {"mutation": "L+D+G_b17",
                    "metrics": {"Q": 1412, "T": 1_304_706, "eps_plus": EPS},
                    "params": {"combo": "L+D+G_b17"},
                    "integrity": evidence_ok()}
        if self.n == 2:
            ev = evidence_ok()
            ev["sigma"] = [9999, 1897, 1246, 3162]  # sigma roto
            return {"mutation": "paso51-roto",
                    "metrics": {"Q": 1400, "T": 1_200_000, "eps_plus": EPS},
                    "params": {"combo": "roto"}, "integrity": ev}
        if self.n == 3:
            return {"mutation": "demasiado-grande",
                    "metrics": {"Q": 1412, "T": 1_304_706, "eps_plus": EPS},
                    "params": {},
                    "meta": {"task": "dqi",
                             "metrics": {"Q": 1412, "T": 1_304_706, "eps_plus": EPS},
                             "register_widths": {"S": 840, "C": 432, "B": 432,
                                                 "extra": 500}}}
        return {"mutation": "peor",
                "metrics": {"Q": 5000, "T": 5_000_000, "eps_plus": EPS},
                "params": {}}


def main():
    from dataclasses import replace as _replace
    spec = _replace(dqi_spec(), baseline_S=BASE_S)
    goal = Goal(baseline_S=BASE_S, improvement_pct=50.0, base_trials=10,
                max_trials=10, patience=5)
    proxy = MetadataProxy(spec, hard_caps={"max_qubits": 2000}, margin=0.10)
    with tempfile.TemporaryDirectory() as d:
        mvp = AutoMvp(spec, Guion(), goal, proxy=proxy, workdir=d)
        res = mvp.run()
        print(f"Mejor S: {res.best_S:.6g} (base {BASE_S:.6g})")
        print(f"Intentos: {res.trials}, aceptados: {res.accepted}, "
              f"rechazados: {res.rejected}")
        print(f"Vetos de integridad: {res.integrity_vetoes}, "
              f"rechazos de proxy: {res.proxy_rejected}")
        print(f"Paro: {res.stop_reason} (meta alcanzada: {res.goal_reached})")
        print(f"Récords CVV: {res.cvv_records}, cadena válida: "
              f"{mvp.cvv.verify()[0]}")
        for r in mvp.cvv.records:
            print(f"  ciclo {r.cycle}: {r.phase} S={r.score:.6g} "
                  f"status={r.status} veto={r.veto_reason or '-'}")
        assert res.integrity_vetoes == 1, "el veto del paso 51 debió dispararse"
        assert res.proxy_rejected == 1, "el proxy debió rechazar la enorme"
        assert abs(res.best_S - s_dqi(1412, 1_304_706, EPS)) < 1.0
        print("Ejemplo OK: la mejora real se aceptó, la regresión se vetó, "
              "la enorme ni se construyó.")


if __name__ == "__main__":
    main()

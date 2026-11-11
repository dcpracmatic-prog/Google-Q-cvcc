"""Tests de AUTO_MVP v0.3.1: GF(2^12) y sigma consciente de escala,
caché de verificación, rotación del ledger, CVV guardado en disco.

La escala k=2314 es la real del paso 51 v3 (shot 0); k=1967 es la del
shot 4. El campo es GF(2^12) mod 0x1053, el mismo que kickmix y que
bm_sim.py; el test lo contrasta con bm_sim.py cuando el venv con
kickmix está disponible, y si no, con las propiedades internas del
campo (que son igual de estrictas).
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
import tempfile
from dataclasses import replace as _replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auto_mvp import (AutoMvp, Goal, IntegrityFilter, VerificationCache,
                      canonical_hash, monic_sigma, sigma_scale_factor)
from auto_mvp.cache import candidate_key, verify_with_cache
from auto_mvp.gf212 import (ANTILOG, LOG, gf_inv, gf_mul, gf_mul_t, monic)
from auto_mvp.healing.ledger import Ledger
from auto_mvp.vqcc import dqi_spec
from auto_mvp.vqcc.costs import s_dqi
from auto_mvp.vqcc.verify import LocalVerifier

VENV = Path.home() / "workspace/sandbox-run/venv/bin/python"
BM_SIM = Path.home() / "workspace/sandbox-run/dqi-ajustes/bm-forney"
EPS = 0.001188
BASE_S = 3.714e12


def test_gf212_matches_bm_sim():
    pairs = [(2314, 2), (1967, 3), (1, 4095), (1234, 567), (4095, 4095),
             (100, 200), (0, 1234), (2314, 1967)]
    expected = [(a, b, gf_mul(a, b), gf_inv(a) if a else 0) for a, b in pairs]
    # Contraste con bm_sim.py (el campo real) si el venv existe.
    if VENV.exists() and BM_SIM.exists():
        script = (
            "import sys, json; "
            "sys.path.insert(0, %r); "
            "import bm_sim; "
            "pairs = %r; "
            "print(json.dumps([[a, b, bm_sim.gf_mul(a, b), "
            "bm_sim.gf_inv(a) if a else 0] for a, b in pairs]))"
            % (str(BM_SIM), pairs)
        )
        out = subprocess.run([str(VENV), "-c", script], capture_output=True,
                             text=True, timeout=120)
        assert out.returncode == 0, out.stderr[-500:]
        got = [tuple(x) for x in json.loads(out.stdout)]
        assert got == expected, "gf212 difiere de bm_sim.py"
    # Propiedades internas del campo (siempre se comprueban).
    rng = random.Random(20261111)
    for _ in range(200):
        a, b = rng.randrange(1, 4096), rng.randrange(1, 4096)
        assert gf_mul(a, b) == gf_mul_t(a, b)
        assert gf_mul(a, gf_inv(a)) == 1
        assert gf_mul(a, 1) == a and gf_mul(a, 0) == 0
    assert len(ANTILOG) == 4095 and len(set(ANTILOG)) == 4095  # 2 primitivo
    assert all(ANTILOG[LOG[v]] == v for v in range(1, 4096))
    # Mónico: dividir por sigma[0] deja el primero en 1.
    sigma = [2314, 1897, 1246, 3162, 0, 4095]
    m = monic(sigma)
    assert m[0] == 1
    assert monic(m) == m
    try:
        monic([0, 1, 2])
    except ValueError:
        pass
    else:
        raise AssertionError("sigma[0]==0 debió fallar")


def test_integrity_scale_aware():
    f = IntegrityFilter()
    # Sigma mónico de referencia y el del circuito (k=2314, shot 0 real).
    ref = [1, 1897, 1246, 3162, 0, 4095, 777, 42]
    k = 2314
    circ = [gf_mul(c, k) for c in ref]
    assert sigma_scale_factor(circ, ref) == k
    ev = {
        "kind": "circuit", "sigma": circ, "sigma_ref": ref,
        "c_restored": 180, "b_restored": 180, "total_coef": 180,
        "dreg_zero": True, "alpha_zero": True,
        "temporaries_zero": 0, "temporaries_total": 0,
        "allowed_dirty": {}, "shots": 5, "verified_by": "gu_trace",
    }
    ok, reasons = f.check(ev)
    assert ok, reasons
    # La vía ingenua (hash directo) FALLARÍA con este sigma: por eso
    # existe la vía consciente de escala.
    assert canonical_hash(circ) != canonical_hash(ref)
    # Otra escala también pasa (k=1967, shot 4 real).
    circ2 = [gf_mul(c, 1967) for c in ref]
    ev["sigma"] = circ2
    ok, _ = f.check(ev)
    assert ok
    # Un sigma con otra raíz (no un múltiplo escalar) falla.
    bad = list(ref)
    bad[3] = gf_mul(bad[3], 2)
    ev["sigma"] = [gf_mul(c, k) for c in bad]
    ok, reasons = f.check(ev)
    assert not ok and any("SIGMA_DIVERGENCE" in r for r in reasons)
    # La vía antigua (solo hash) sigue funcionando sin sigma_ref.
    ev2 = dict(ev)
    ev2.pop("sigma_ref")
    ev2["sigma"] = ref
    ev2["sigma_ref_hash"] = canonical_hash(ref)
    ok, _ = f.check(ev2)
    assert ok


def test_verification_cache():
    spec = dqi_spec()
    verifier = LocalVerifier(spec)
    cache = VerificationCache(max_entries=2)
    cand = {"mutation": "a", "metrics": {"Q": 1412, "T": 1_304_706, "eps_plus": EPS},
            "params": {"x": 1}}
    r1, hit1 = verify_with_cache(cache, verifier, cand)
    assert not hit1 and cache.misses == 1
    r2, hit2 = verify_with_cache(cache, verifier, cand)
    assert hit2 and cache.hits == 1 and r2.S == r1.S
    # Otro candidato: miss; la caché no confunde parámetros.
    cand2 = dict(cand, params={"x": 2})
    _, hit3 = verify_with_cache(cache, verifier, cand2)
    assert not hit3 and len(cache) == 2
    cand3 = dict(cand, params={"x": 3})
    verify_with_cache(cache, verifier, cand3)
    assert len(cache) == 2  # techo: el más antiguo salió
    assert candidate_key(cand) != candidate_key(cand2)


def test_ledger_rotation():
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "ledger.jsonl")
        led = Ledger(path=path, max_bytes=200)
        for i in range(20):
            led.log("trial", task="dqi", mutation=f"m{i}", S=1.0e12 + i)
        main = Path(path)
        rotated = Path(path + ".1")
        assert rotated.exists(), "debió rotar a .1"
        assert main.stat().st_size <= 200 + 300  # una fila más, como mucho
        rows = [json.loads(l) for l in main.read_text().splitlines()]
        assert all(r["event"] == "trial" for r in rows)
        assert len(led.rows) == 20  # en memoria sigue todo


class RepeatMutator:
    def __init__(self):
        self.n = 0

    def propose(self, spec, best, evidence):
        self.n += 1
        if self.n <= 2:
            return {"mutation": "mismo",
                    "metrics": {"Q": 1412, "T": 1_304_706, "eps_plus": EPS},
                    "params": {"combo": "L+D+G_b17"}}
        return {"mutation": "peor",
                "metrics": {"Q": 5000, "T": 5_000_000, "eps_plus": EPS},
                "params": {}}


class CountingVerifier(LocalVerifier):
    def __init__(self, spec):
        super().__init__(spec)
        self.calls = 0

    def verify(self, candidate):
        self.calls += 1
        return super().verify(candidate)


def test_orchestrator_with_cache_and_files():
    spec = _replace(dqi_spec(), baseline_S=BASE_S)
    goal = Goal(baseline_S=BASE_S, improvement_pct=50.0, base_trials=6,
                max_trials=6, patience=3)
    verifier = CountingVerifier(spec)
    cache = VerificationCache()
    with tempfile.TemporaryDirectory() as d:
        mvp = AutoMvp(spec, RepeatMutator(), goal, verifier=verifier,
                      cache=cache, workdir=d)
        res = mvp.run()
        # El candidato repetido se verificó una sola vez (caché): 2
        # verificaciones reales (un "mismo" y un "peor"), resto aciertos.
        assert verifier.calls == 2, verifier.calls
        assert res.cache_hits == 2 and res.cache_misses == 2
        assert res.accepted == 1
        assert abs(res.best_S - s_dqi(1412, 1_304_706, EPS)) < 1.0
        # Archivos del run: CVV, ledger y (sin mejor oficial) sin checkpoint.
        assert res.cvv_path is not None and Path(res.cvv_path).exists()
        chain_rows = [json.loads(l) for l in
                      Path(res.cvv_path).read_text().splitlines() if l.strip()]
        assert chain_rows[0]["phase"] == "INGEST_BASELINE"
        assert chain_rows[-1]["phase"] == "MVP_CONVERGENCE"
        assert (Path(d) / "ledger.jsonl").exists()
        assert res.checkpoint_path is None


if __name__ == "__main__":
    test_gf212_matches_bm_sim()
    print("gf212 ok")
    test_integrity_scale_aware()
    print("integrity scale ok")
    test_verification_cache()
    print("cache ok")
    test_ledger_rotation()
    print("ledger rotation ok")
    test_orchestrator_with_cache_and_files()
    print("orchestrator cache ok")
    print("ALL v0.3.1 TESTS PASSED")

"""Tests de AUTO_MVP v0.3.2: pipeline por fases (6h/24h), puerta de
promoción GM>=30, artefactos i<iter>-<score>, reanudación, y el init
de Kaggle (separación inmutable / código / trabajo).

La meta 30.00: con invsqrt certificado (20.65x) y química propia
(1.0x), exige DQI ~1307x. Q=400/T=95,000 da GM 29.99 (NO promueve:
la puerta es afilada); Q=400/T=90,000 da GM ~30.53 (promueve).
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auto_mvp import (AutoMvp, Goal, MetadataProxy, PromotionGate,
                      artifact_name, promotion_gm, required_dqi_ratio)
from auto_mvp.kaggle_init import detect_environment, init
from auto_mvp.pipeline import ArtifactStore, Pipeline
from auto_mvp.vqcc import dqi_spec
from auto_mvp.vqcc.costs import s_dqi

EPS = 0.001188
BASE_S = 3.714e12


def meta_dqi(Q, T, widths=None):
    return {"task": "dqi", "metrics": {"Q": Q, "T": T, "eps_plus": EPS},
            "register_widths": widths or {"S": 840, "C": 432, "B": 432}}


def test_gate_math():
    # La meta 30.00 exige DQI ~1307x con química propia.
    req = required_dqi_ratio(30.0)
    assert 1300 < req < 1315, req
    # Q=400/T=95,000 -> GM 29.99: NO promueve (puerta afilada).
    gm = promotion_gm({"dqi": s_dqi(400, 95_000, EPS)})
    assert 29.9 < gm < 30.0, gm
    assert not PromotionGate(30.0).evaluate({"dqi": s_dqi(400, 95_000, EPS)}).promote
    # Q=400/T=90,000 -> GM ~30.5: promueve.
    v = PromotionGate(30.0).evaluate({"dqi": s_dqi(400, 90_000, EPS)})
    assert v.promote and v.gm > 30.0
    # Con química pública (10.27x) basta DQI ~127x: Q=892/T=195,000.
    pub = {"dfthcsos": 326_800_029.87}
    req_pub = required_dqi_ratio(30.0, {"invsqrt": 100_568.5, "dqi": 1.99836e13,
                                        "dfthcsos": 326_800_029.87})
    assert 120 < req_pub < 135, req_pub
    v2 = PromotionGate(30.0, {"invsqrt": 100_568.5, "dqi": 1.99836e13,
                              "dfthcsos": 326_800_029.87}).evaluate(
        {"dqi": s_dqi(892, 195_000, EPS)})
    assert v2.promote and v2.gm > 30.0
    # El filo: Q=892/T=196,000 da GM 29.9977 y NO promueve.
    v3 = PromotionGate(30.0, {"invsqrt": 100_568.5, "dqi": 1.99836e13,
                              "dfthcsos": 326_800_029.87}).evaluate(
        {"dqi": s_dqi(892, 196_000, EPS)})
    assert not v3.promote and abs(v3.gm - 30.0) < 0.01


def test_artifact_naming_and_compiled():
    assert artifact_name(120549, 34.16) == "i120549-34.16"
    assert artifact_name(3, 5.4) == "i3-5.40"
    with tempfile.TemporaryDirectory() as d:
        store = ArtifactStore(Path(d) / "runs")
        dest = store.save(120549, 34.16, {"task": "dqi", "kind": "target",
                                          "S": {"dqi": 1.0e10}, "ratios": {},
                                          "source_commit": "abc123"})
        assert dest.name == "i120549-34.16"
        man = json.loads((dest / "manifest.json").read_text())
        assert man["phase"] == "PROMOTED" and man["compiled"] is False
        assert man["source_commit"] == "abc123"
        assert (dest / "candidate.json").exists()
        store.mark_compiled(dest, {"official_pass": True, "S_measured": 1.0e10})
        man2 = json.loads((dest / "manifest.json").read_text())
        assert man2["phase"] == "PASS" and man2["compiled"] is True


def test_pipeline_phases_and_resume():
    spec = dqi_spec()
    proxy = MetadataProxy(spec, hard_caps={"max_qubits": 2000}, margin=0.10)
    gate = PromotionGate(30.0)
    stream = [
        {"meta": meta_dqi(1412, 1_304_706, {"S": 840, "C": 432, "B": 432, "extra": 500}),
         "metrics": {"Q": 1412, "T": 1_304_706, "eps_plus": EPS}},  # proxy rechaza
        {"meta": meta_dqi(1412, 1_304_706),
         "metrics": {"Q": 1412, "T": 1_304_706, "eps_plus": EPS}},  # puerta rechaza (~5.4)
        {"meta": meta_dqi(400, 90_000, {"S": 400}),
         "metrics": {"Q": 400, "T": 90_000, "eps_plus": EPS},
         "kind": "target"},  # promueve
    ]
    with tempfile.TemporaryDirectory() as d:
        runs = Path(d) / "runs"
        pipe = Pipeline(proxy, gate, runs_dir=runs, source_commit="test-sha")
        res = pipe.run(iter(stream))
        assert res.screened == 3, res
        assert res.proxy_rejected == 1, res
        assert res.gate_rejected == 1, res
        assert res.promoted == 1, res
        assert res.best_gm > 30.0
        assert len(res.artifacts) == 1
        assert Path(res.artifacts[0]).name.startswith("i3-")
        assert (Path(d) / "runs" / "state.json").exists()
        # Reanudar: la segunda corrida sigue contando iteraciones.
        pipe2 = Pipeline(proxy, gate, runs_dir=runs, source_commit="test-sha")
        assert pipe2.iteration == 3, pipe2.iteration
        res2 = pipe2.run(iter([stream[1]]))
        assert res2.iterations == 4, res2
        assert res2.screened == 1 and res2.promoted == 0
        # Presupuesto de tiempo 0: para sin cribar.
        pipe3 = Pipeline(proxy, gate, runs_dir=runs, time_budget_seconds=0)
        res3 = pipe3.run(iter(stream))
        assert res3.screened == 0 and "tiempo" in res3.stopped


def test_kaggle_init_local():
    assert detect_environment() == "local"
    with tempfile.TemporaryDirectory() as d:
        env = init(working_dir=d, input_dir=str(Path.home() / "workspace/sandbox-run"),
                   vendored_path=Path(__file__).resolve().parents[1] / "auto_mvp",
                   commit_sha="test-sha-123")
        assert env.kind == "local"
        assert env.code_source in ("vendored", "cloned")
        assert env.commit_sha
        assert (env.code_path / "__init__.py").exists()
        assert (Path(d) / "runs").exists()
        man = json.loads((Path(d) / "init_manifest.json").read_text())
        assert man["input_readonly"] is True and man["code_readonly"] is True
        assert man["code_source"] == env.code_source


if __name__ == "__main__":
    test_gate_math()
    print("gate ok")
    test_artifact_naming_and_compiled()
    print("artifact ok")
    test_pipeline_phases_and_resume()
    print("pipeline ok")
    test_kaggle_init_local()
    print("kaggle_init ok")
    print("ALL v0.3.2 TESTS PASSED")

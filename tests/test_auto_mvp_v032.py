"""Tests de AUTO_MVP v0.3.2: pipeline por fases (6h/24h), puerta de
promoción (bate el mejor envío 23.94667), artefactos i<iter>-<score>,
reanudación, y el init de Kaggle (separación inmutable / código /
trabajo).

La puerta mide contra el mejor envío (23.94667): batirlo exige DQI
~64.76x (batir el DQI público, S=3.7676e11). La meta 30.00 NO es
alcanzable con el enfoque actual: el producto debe ser 27,000 contra
13,732 actual (x1.966); solo por DQI habría que bajar T un 49.1%.
"""
from __future__ import annotations

import json
import shutil
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
    # La puerta mide contra el mejor envío (23.94667): batirlo exige
    # DQI ~64.76x, es decir, batir el DQI público (S=3.7676e11).
    req = required_dqi_ratio()
    assert 64 < req < 66, req
    # Un DQI a S=3.5e11 (ratio 69.8x) bate el público: GM ~24.5, promueve.
    v = PromotionGate().evaluate({"dqi": 3.5e11})
    assert v.promote and 24.0 < v.gm < 25.0, v.gm
    # Un DQI a S=4.0e11 (ratio 61.0x) no lo bate: GM ~23.5, no promueve.
    v2 = PromotionGate().evaluate({"dqi": 4.0e11})
    assert not v2.promote and 23.0 < v2.gm < 23.94667, v2.gm
    # El DQI público mismo (S=3.7676e11) da GM 23.9468: el filo.
    v3 = PromotionGate().evaluate({"dqi": 3.7676e11})
    assert abs(v3.gm - 23.94667) < 0.01, v3.gm
    # 30.00 no es alcanzable con el enfoque actual (veredicto
    # 2026-11-11): el producto debe ser 27,000 contra 13,732 actual.
    from auto_mvp.pipeline import CURRENT_BEST_S
    from auto_mvp.vqcc.contracts import REFERENCE_S
    prod = 1.0
    for t, s in CURRENT_BEST_S.items():
        prod *= REFERENCE_S[t] / s
    assert 13_700 < prod < 13_800, prod
    assert 27_000 / prod > 1.96
    # Solo por DQI, 30 exigiría 127.3x (T -49.1% a Q y R fijos).
    assert 127 < required_dqi_ratio(30.0) < 128, required_dqi_ratio(30.0)


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
         "metrics": {"Q": 1412, "T": 1_304_706, "eps_plus": EPS}},  # proxy rechaza (tope)
        {"meta": meta_dqi(1412, 1_304_706),
         "metrics": {"Q": 1412, "T": 1_304_706, "eps_plus": EPS}},  # proxy rechaza:
        # el MIS (S=3.197e12) no bate el DQI público (3.7676e11), así que
        # el proxy lo para antes de la puerta (antes, con el ensamble
        # como base, llegaba a la puerta y daba GM ~5.4).
        {"meta": meta_dqi(400, 90_000, {"S": 400}),
         "metrics": {"Q": 400, "T": 90_000, "eps_plus": EPS},
         "kind": "target"},  # promueve (GM 66.37 con el mejor envío)
    ]
    with tempfile.TemporaryDirectory() as d:
        runs = Path(d) / "runs"
        pipe = Pipeline(proxy, gate, runs_dir=runs, source_commit="test-sha")
        res = pipe.run(iter(stream))
        assert res.screened == 3, res
        assert res.proxy_rejected == 2, res
        assert res.gate_rejected == 0, res
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
        # La copia vendida como la lleva el notebook: un directorio que
        # CONTIENE el paquete (auto-mvp-vendored/auto_mvp/), no el
        # paquete mismo.
        vendored_parent = Path(d) / "auto-mvp-vendored"
        shutil.copytree(Path(__file__).resolve().parents[1] / "auto_mvp",
                        vendored_parent / "auto_mvp")
        env = init(working_dir=d, input_dir=str(Path.home() / "workspace/sandbox-run"),
                   vendored_path=vendored_parent,
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

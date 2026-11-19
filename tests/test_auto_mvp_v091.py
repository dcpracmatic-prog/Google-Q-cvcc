"""AUTO_MVP v0.9.1 — la síntesis de rotaciones en el costo invsqrt.

Verifica, contra el verificador OFICIAL (importado de su archivo),
que el proxy ya no ignora el costo de síntesis de rotaciones:
- rotation_t_count es idéntico al del verificador oficial.
- Con 37 rotaciones y el e1 del mejor prefiltro (grado 7/1
  segmento, 3.444e-08), la referencia da S 2,077,168.5, a 0.019%
  del S oficial 2,076,774 (sin la síntesis daría 2,011,100, un
  3.2% por debajo: ese era el hueco).
- Sin rotaciones, la fórmula es la de siempre (62,000).
- Fail-closed: rotaciones sin rel_error, o rel_error >= 2^-24,
  se rechazan con su motivo (el proxy no inventa el margen).
- El e1 sale de la tabla del Lab cuando el candidato trae
  grado/segmentos (grado 7/1 segmento).
- El module.py exportado usa la misma fórmula (el dataset no
  discrepa del repo).
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from auto_mvp.dataset import export_candidate
from auto_mvp.numeric_lab import rel_error_for
from auto_mvp.proxy import CandidateMeta, MetadataProxy, estimate_S
from auto_mvp.vqcc import invsqrt_spec
from auto_mvp.vqcc.costs import (rotation_margin_turns, rotation_t_count,
                                 s_invsqrt)

E1_BEST = 3.4437759310890215e-08  # grado 7 / 1 segmento (tabla del Lab)


def _official_rotation_t_count():
    # v2.17.11: la copia vendida en el repo es idéntica a la oficial
    # (mismo rotation_t_count); la ruta del sandbox no existe en Kaggle.
    repo = Path(__file__).resolve().parents[1]
    vendored = (repo / "auto_mvp" / "circuits" / "verifiers"
                / "verify_submission_invsqrt.py")
    sandbox = Path("/home/hatch/workspace/sandbox-run/competition-verifiers"
                   "/invsqrt/verify_submission_invsqrt.py")
    path = vendored if vendored.is_file() else sandbox
    spec = importlib.util.spec_from_file_location("verif_invsqrt", str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["verif_invsqrt"] = mod
    spec.loader.exec_module(mod)
    return mod.rotation_t_count


def test_rotation_t_count_matches_official_verifier():
    official = _official_rotation_t_count()
    for eps in (2.0 ** -24, 1e-12, 1e-6, 1e-3):
        assert abs(rotation_t_count(eps) - official(eps)) < 1e-12
    assert abs(rotation_t_count(2.0 ** -24) - 18.74) < 1e-9


def test_reference_S_with_rotation_synthesis():
    # La referencia (Q=260, 7,735 Toffolis, 37 rotaciones) con el e1
    # del mejor prefiltro: a 0.019% del S oficial 2,076,774.
    S = s_invsqrt(260, 7735, 0, rotations=37, rel_error=E1_BEST)
    assert abs(S - 2_076_774) / 2_076_774 < 1e-3
    # Sin la síntesis, la referencia quedaría un 3.2% por debajo:
    # ese era el hueco que el proxy ignoraba.
    assert abs(s_invsqrt(260, 7735, 0) - 2_011_100) < 1.0
    # El margen es la cota inferior que deja el e1.
    assert rotation_margin_turns(E1_BEST) > 0
    assert abs(rotation_margin_turns(E1_BEST) - 1.42161e-11) / 1.42161e-11 < 1e-3


def test_s_invsqrt_backward_compatible_without_rotations():
    assert s_invsqrt(62, 1000, 0) == 62_000.0
    assert s_invsqrt(62, 1000, 0, rotations=0) == 62_000.0
    # Con rotaciones, el costo sube (37 rot, e1 del prefiltro).
    S = s_invsqrt(62, 1000, 0, rotations=37, rel_error=E1_BEST)
    assert abs(S - 77_754.80) < 0.5
    assert S > 62_000.0


def test_s_invsqrt_fail_closed():
    with pytest.raises(ValueError, match="sin rel_error"):
        s_invsqrt(62, 1000, 0, rotations=37)
    with pytest.raises(ValueError, match="sin tolerancia"):
        s_invsqrt(62, 1000, 0, rotations=37, rel_error=2.0 ** -24)
    with pytest.raises(ValueError, match="sin tolerancia"):
        s_invsqrt(62, 1000, 0, rotations=37, rel_error=0.01)
    with pytest.raises(ValueError):
        s_invsqrt(62, 1000, 0, rotations=-1)
    with pytest.raises(ValueError):
        rotation_t_count(0.0)


def test_rel_error_for_from_lab_table():
    assert abs(rel_error_for(7, 1) - E1_BEST) < 1e-15
    assert rel_error_for(2, 1) > 2.0 ** -24  # no pasa el prefiltro
    assert rel_error_for(99, 99) is None


def test_proxy_charges_rotation_synthesis():
    proxy = MetadataProxy(invsqrt_spec(), margin=0.10,
                          numeric_prefilter=True)
    best_S = 100_568.5
    # Con rotaciones y rel_error, el S incluye la síntesis.
    cand = CandidateMeta(
        task="invsqrt",
        metrics={"Q": 62, "C": 1000, "toffoli": 1000, "t_count": 0, "rotations": 37,
                 "rel_error": E1_BEST, "degree": 7, "segments": 1},
        register_widths={"x": 22})
    v = proxy.evaluate(cand, best_S)
    assert v.s_estimate is not None
    assert abs(v.s_estimate - 77_754.80) < 0.5
    # Sin rel_error y sin grado/segmentos: el proxy lo rechaza
    # (fail-closed: no inventa el margen).
    bad = CandidateMeta(
        task="invsqrt",
        metrics={"Q": 62, "C": 1000, "toffoli": 1000, "t_count": 0, "rotations": 37},
        register_widths={"x": 22})
    v2 = proxy.evaluate(bad, best_S)
    assert not v2.ok and any("sin rel_error" in r for r in v2.reasons)
    # Con grado/segmentos (sin rel_error explícito), el e1 sale de
    # la tabla del Lab y el S es el mismo.
    via_table = CandidateMeta(
        task="invsqrt",
        metrics={"Q": 62, "C": 1000, "toffoli": 1000, "t_count": 0, "rotations": 37,
                 "degree": 7, "segments": 1},
        register_widths={"x": 22})
    v3 = proxy.evaluate(via_table, best_S)
    assert v3.s_estimate is not None
    assert abs(v3.s_estimate - 77_754.80) < 0.5
    # Sin rotaciones, el de siempre (el test v0.5.0 sigue pasando).
    plain = CandidateMeta(
        task="invsqrt",
        metrics={"Q": 62, "C": 1000, "toffoli": 1000, "t_count": 0,
                 "degree": 7, "segments": 1},
        register_widths={"x": 22, "scratch": 40})
    v4 = proxy.evaluate(plain, best_S)
    assert v4.ok and abs(v4.s_estimate - 62_000) < 1.0


def test_exported_module_uses_same_formula(tmp_path):
    rec = {"iteration": 1, "gm": 26.091058835990413,
           "S": {"invsqrt": 77_754.80},
           "ratios": {"invsqrt": 26.70927068168139, "dqi": 64.7627136638709,
                      "dfthcsos": 10.268051657323431},
           "task": "invsqrt", "kind": "candidate",
           "meta": {"task": "invsqrt",
                    "metrics": {"Q": 62, "toffoli": 1000, "t_count": 0,
                                "rotations": 37, "rel_error": E1_BEST}},
           "metrics": {"Q": 62, "toffoli": 1000, "t_count": 0,
                       "rotations": 37, "rel_error": E1_BEST},
           "source_commit": "test"}
    art = tmp_path / "runs" / "i1-26.09"
    art.mkdir(parents=True)
    (art / "manifest.json").write_text("{}", encoding="utf-8")
    out = export_candidate(rec, art, tmp_path / "runs" / "dataset")
    mod = Path(out["dataset_dir"]) / "module.py"
    r = subprocess.run([sys.executable, str(mod)], capture_output=True,
                       text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    res = json.loads(r.stdout)
    assert res["ok"] is True, res
    assert abs(res["S"] - 77_754.80) < 0.5

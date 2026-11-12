"""AUTO_MVP v2.3 — el prefilter: la puerta barata delante del paso caro.

El proxy es la PUERTA, no el producto: ordena y descarta en
milisegundos, y solo los ganadores llegan a kickmix. El S que cuenta
sigue siendo el MEDIDO.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from auto_mvp.circuits.cost_models.dqi_cost import (
    MEASURED_DECODERS, estimate_variant, explicit_corrected, sweep)
from auto_mvp.llm_auto import _parse_deltas, run_llm_auto
from auto_mvp.prefilter import (
    calibrate_margin, delta_conflicts, estimate_delta, expected_gain,
    rank_deltas)
from auto_mvp.proxy import estimate_S

BEST_INVSQRT = {"Q": 62, "T": 1495, "S": 100568.5}


def test_dqi_cost_reproduce_los_4_decodificadores_medidos():
    """El modelo vendido reproduce EXACTOS los 4 decodificadores."""
    for mult, m in MEASURED_DECODERS.items():
        e = explicit_corrected(mult)
        assert e["T"] == m["T"], f"mult {mult}: T {e['T']} != {m['T']}"
        assert e["Q"] == m["Q"], f"mult {mult}: Q {e['Q']} != {m['Q']}"


def test_dqi_cost_toom4_v1_e2_reproduce_el_medido_en_kaggle():
    """Toom-4+V1+E2: Q=1,899 T=4,477,394 S=1.923348e13 (kernel 144398281)."""
    v = estimate_variant(42, v1=True, e2=True)
    assert v["Q"] == 1_899
    assert v["T"] == 4_477_394
    assert abs(v["S"] - 1.923348e13) / 1.923348e13 < 0.001


def test_dqi_sweep_16_variantes_en_milisegundos_y_ordenado():
    t0 = time.monotonic()
    rows = sweep()
    dt = time.monotonic() - t0
    assert len(rows) == 16
    assert dt < 1.0, f"el barrido tardó {dt:.2f}s, debe ser milisegundos"
    ss = [r["S"] for r in rows]
    assert ss == sorted(ss), "el barrido debe salir ordenado por S"
    best = rows[0]
    assert best["mult"] == 42 and best["v1"] and best["e2"]
    assert rows[-1]["mult"] == 63 and not rows[-1]["v1"]


def test_prefilter_invsqrt_ganancia_cero_no_pasa_la_puerta():
    """Un delta sin ganancia esperada estima el mejor S: lo rechaza."""
    hist = [{"K": 5, "gain_reported": 0, "valid": True}] * 3
    hist.append({"K": 6, "gain_reported": 500, "valid": True})
    out = rank_deltas(
        [{"K": 5, "seed": 1, "reason": "K5"},
         {"K": 6, "seed": 2, "reason": "K6"},
         {"K": 6, "seed": 2, "reason": "K6 duplicado"}],
        "invsqrt", float(BEST_INVSQRT["S"]), BEST_INVSQRT, hist,
        margin=0.25, top_k=2)
    winners = [d for d, _ in out["winners"]]
    assert winners == [{"K": 6, "seed": 2, "reason": "K6"}]
    # El estimado del ganador parte del S medido menos la ganancia.
    est = out["winners"][0][1].s_estimate
    assert abs(est - (100568.5 - 62 * 500)) < 1.0
    # El K=5 (ganancia 0) queda descartado con su motivo.
    discarded = {d["K"]: r for d, r in out["discarded"]}
    assert 5 in discarded
    assert "margen" in discarded[5]


def test_prefilter_dqi_toom4_pasa_y_baseline_no():
    """DQI: Toom-4 pasa la puerta (con margen calibrado chico), 63T no."""
    best_S = 1.99836e13  # ensamble medido
    out = rank_deltas(
        [{"mult": 63, "v1": False, "e2": False},
         {"mult": 42, "v1": True, "e2": True}],
        "dqi", best_S, {}, [], margin=0.01, top_k=2)
    winners = [d for d, _ in out["winners"]]
    assert winners == [{"mult": 42, "v1": True, "e2": True}]
    assert any(d.get("mult") == 63 for d, _ in out["discarded"])


def test_prefilter_quimica_sin_metricas_rechaza_sin_inventar():
    """Química sin métricas medidas: se rechaza, no se estima nada."""
    out = rank_deltas(
        [{"rank": 8}], "dfthcsos", 326_800_029.87, {}, [], top_k=2)
    assert out["winners"] == []
    assert len(out["discarded"]) == 1
    assert "no estimable" in out["discarded"][0][1]


def test_mwis_un_hueco_caro_por_target():
    """Dos deltas con el mismo K confligen: solo uno gana el hueco."""
    hist = [{"K": 6, "gain_reported": 500, "valid": True},
            {"K": 7, "gain_reported": 400, "valid": True}]
    assert delta_conflicts({"K": 6, "seed": 1}, {"K": 6, "seed": 2})
    assert not delta_conflicts({"K": 6, "seed": 1}, {"K": 7, "seed": 1})
    out = rank_deltas(
        [{"K": 6, "seed": 1}, {"K": 6, "seed": 2}, {"K": 7, "seed": 3}],
        "invsqrt", float(BEST_INVSQRT["S"]), BEST_INVSQRT, hist,
        margin=0.20, top_k=2)
    ks = sorted(d["K"] for d, _ in out["winners"])
    assert ks == [6, 7], f"un K=6 y un K=7, no dos K=6: {ks}"


def test_estimate_delta_invsqrt_parte_del_s_medido():
    """Con ganancia 0 el estimado ES el S medido (no lo subestima)."""
    meta = estimate_delta("invsqrt", {"K": 5, "seed": 1}, BEST_INVSQRT, [])
    assert abs(estimate_S(meta) - 100568.5) < 1.0
    meta6 = estimate_delta(
        "invsqrt", {"K": 6, "seed": 1}, BEST_INVSQRT,
        [{"K": 6, "gain_reported": 100, "valid": True}])
    assert abs(estimate_S(meta6) - (100568.5 - 62 * 100)) < 1.0
    assert expected_gain([], 6) == 0.0


def test_calibrate_margin_mide_el_error_del_proxy():
    m = calibrate_margin([(110.0, 100.0)] * 5)
    assert abs(m - 0.10) < 1e-9
    assert calibrate_margin([]) == 0.25
    assert calibrate_margin([(100.0, 100.0)] * 5) == 0.0


def test_llm_auto_lote_solo_el_ganador_llega_a_kickmix(tmp_path: Path):
    """El modelo propone 3 deltas; el prefilter deja pasar 1 y los
    otros 2 se descartan baratos. Solo sale la semilla, nunca un .kmx."""
    import json

    from auto_mvp.seed import new_seed, save_seed

    # Historial con señal: K=6 ya dio 500 Toffolis; K=5 y K=7, cero.
    base = new_seed("invsqrt", 100568.5, 62, 1495, {"base": "invsqrt_pub"},
                    notes="semilla vendida, medida")
    save_seed(base, tmp_path)
    (tmp_path / "seed_ledger.json").write_text(json.dumps({
        "task": "invsqrt", "best_seed": base, "proposals": 0,
        "valid": 0, "invalid": 0, "llm_calls": 0, "llm_fallbacks": 0,
        "rejected": [{"K": 5, "gain_reported": 0, "valid": True},
                     {"K": 7, "gain_reported": 0, "valid": True}],
        "measured": [{"K": 6, "gain_reported": 500, "valid": True}],
        "prefilter_ranked": 0, "prefilter_discarded": 0,
        "prefilter_winners": 0}, ensure_ascii=False), encoding="utf-8")
    calls = {"n": 0}

    def fake_llm(prompt: str):
        calls["n"] += 1
        return {"deltas": [
            {"K": 5, "seed": 11, "reason": "K5"},
            {"K": 6, "seed": 22, "reason": "K6"},
            {"K": 7, "seed": 33, "reason": "K7"}]}

    res = run_llm_auto(
        90000, runs_dir=tmp_path, max_proposals=1, sa_budget_s=5,
        llm_client=fake_llm, batch_size=3, expensive_per_round=1,
        prefilter_margin=0.25)
    assert calls["n"] == 1
    assert res["proposals"] == 1
    assert res["prefilter_ranked"] == 3
    assert res["prefilter_winners"] == 1
    assert res["prefilter_discarded"] == 2
    assert list(tmp_path.rglob("*.kmx")) == []
    assert (tmp_path / "seeds" / "invsqrt").exists()
    assert res["best_S"] == 100568.5  # la semilla ya es óptima: no mejora


def test_parse_deltas_acepta_lote_unico_y_lista():
    assert _parse_deltas({"deltas": [{"K": 5, "seed": 1}]})[0]["K"] == 5
    assert _parse_deltas({"K": 6, "seed": 2})[0]["seed"] == 2
    assert len(_parse_deltas([{"K": 5, "seed": 1}, {"K": 7, "seed": 2}])) == 2
    with pytest.raises(ValueError):
        _parse_deltas({"K": 9, "seed": 1})
    with pytest.raises(ValueError):
        _parse_deltas({"deltas": []})

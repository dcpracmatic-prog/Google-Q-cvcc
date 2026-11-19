"""Tests para motifs.py, search/adaptive.py y vqcc/package_audit.py
(Ley Cuantica v6/v6.1)."""
import sys
sys.path.insert(0, "/home/hatch/workspace/auto-mvp-v2")

from auto_mvp.circuits.motifs import (
    MOTIFS, get_motif, motifs_for_task, best_gf12_mul, motif_prompt_block,
    current_ratios, lagging_task, geometric_mean,
    promote_motif, demote_motif,
)
from auto_mvp.search.adaptive import AdaptiveSearch, select_task, effort_share
from auto_mvp.vqcc.package_audit import audit_zip, audit_submission_dir


def test_motifs():
    # El mejor multiplicador GF(2^12) medido es 42T (no 63T).
    best = best_gf12_mul()
    assert best.toffoli == 42, f"mejor GF12 debe ser 42T, es {best.toffoli}T"
    # El Karatsuba nativo (63T) esta como referencia y es peor.
    kara = get_motif("gf12_mul_karatsuba_63t")
    assert kara.toffoli == 63
    assert best.toffoli < kara.toffoli
    # El truncado de 36T es mas barato pero es otra operacion (7 bits).
    trunc = get_motif("gf12_mul_trunc_36t")
    assert trunc.toffoli == 36
    assert trunc.kind == "gf_mul_trunc"
    # Motivos por tarea.
    dqi = motifs_for_task("dqi")
    assert len(dqi) >= 4
    assert all(m.task == "dqi" for m in dqi)
    assert dqi[0].toffoli <= dqi[-1].toffoli  # ordenados por Toffoli
    # El bloque de prompt menciona los motivos y sus costos medidos.
    block = motif_prompt_block("dqi")
    assert "42" in block and "gf12_mul_42t" in block
    assert "36" in block and "gf12_mul_trunc_36t" in block
    # Todos los motivos tienen costo medido (no vacio).
    for m in MOTIFS:
        assert m.toffoli > 0 and m.qubits > 0 and m.measured
    print("motifs: OK")


def test_motifs_metric_impact():
    # DQI: el motivo trae Q y eps+ (Q entra al cuadrado, eps+ < 1/16).
    m = get_motif("gf12_mul_42t")
    assert m.qubits == 36 and "eps" in m.eps_plus_impact.lower()
    # invsqrt: el motivo trae la sintesis de rotaciones (T).
    inv = get_motif("invsqrt_44q")
    assert inv.rotation_t > 0  # 33 rotaciones x 28.91 T
    # dfthcsos: el motivo trae Lambda / E_gap / T_total.
    chem = get_motif("dfthcsos_loader")
    assert "283" in chem.lambda_impact and "3.91" in chem.e_gap_impact
    # El prompt de quimica menciona Lambda (la palanca).
    block = motif_prompt_block("dfthcsos")
    assert "Lambda" in block
    print("motifs metric impact: OK")


def test_motifs_gm_gap():
    r = current_ratios()
    assert abs(r["invsqrt"] - 27.911505) < 0.001
    assert abs(r["dqi"] - 70.786331) < 0.001
    assert abs(r["dfthcsos"] - 11.388728) < 0.001
    # La tarea mas rezagada es quimica (dfthcsos).
    assert lagging_task() == "dfthcsos"
    assert abs(geometric_mean() - 28.23163) < 0.001
    # Promocion: un motivo que mejora baja su Toffoli.
    before = get_motif("gf12_mul_toom4_42t").toffoli
    promote_motif("gf12_mul_toom4_42t", 40, "verificador oficial, prueba")
    assert get_motif("gf12_mul_toom4_42t").toffoli == 40
    # Restaurar el valor original (promote solo baja, asi que se
    # reescribe directo el registro para no dejar el test modificado).
    import auto_mvp.circuits.motifs as _mm
    for i, m in enumerate(_mm.MOTIFS):
        if m.name == "gf12_mul_toom4_42t":
            _mm.MOTIFS[i] = _mm.Motif(
                name=m.name, task=m.task, kind=m.kind, toffoli=42,
                qubits=m.qubits, measured="tests/test_toom4.py 13/13; kickmix clasico 510/510",
                note=m.note, generator=m.generator,
                eps_plus_impact=m.eps_plus_impact, rotation_t=m.rotation_t,
                lambda_impact=m.lambda_impact, e_gap_impact=m.e_gap_impact,
                t_total_impact=m.t_total_impact, weight=1.0,
            )
    assert get_motif("gf12_mul_toom4_42t").toffoli == 42
    # Democion: baja el peso.
    w0 = get_motif("gf12_mul_karatsuba_63t").weight
    w1 = demote_motif("gf12_mul_karatsuba_63t", 0.5)
    assert w1 < w0
    print("motifs gm gap + learning: OK")


def test_adaptive():
    a = AdaptiveSearch(k=0.5, s=0.5, window=4, stall_limit=3)
    # Sin resultados, sigma_bar neutro y s no se mueve mucho.
    assert a.sigma_bar() == 0.5
    # Exitos seguidos -> s sube hacia 1.
    for _ in range(4):
        a.record("f1", True)
    assert a.sigma_bar() == 1.0
    assert a.aggressiveness() > 0.5
    # Fracasos seguidos -> s baja hacia 0.
    b = AdaptiveSearch(k=0.5, s=0.8, window=4, stall_limit=3)
    for _ in range(4):
        b.record("f1", False)
    assert b.sigma_bar() == 0.0
    assert b.aggressiveness() < 0.8
    # Saturacion: 3 intentos sin mejora podan la familia.
    c = AdaptiveSearch(k=0.2, s=0.5, window=10, stall_limit=3)
    assert not c.is_pruned("f2")
    c.record("f2", False)
    c.record("f2", False)
    assert not c.is_pruned("f2")
    c.record("f2", False)
    assert c.is_pruned("f2")
    # Una mejora resetea el contador de estancamiento.
    d = AdaptiveSearch(k=0.2, s=0.5, window=10, stall_limit=3)
    d.record("f3", False)
    d.record("f3", False)
    d.record("f3", True)
    assert d.stall_count("f3") == 0
    assert not d.is_pruned("f3")
    # Sugerencias cualitativas segun s.
    assert "conservador" in AdaptiveSearch(s=0.1).suggest_step()
    assert "agresivo" in AdaptiveSearch(s=0.9).suggest_step()
    print("adaptive: OK")


def test_adaptive_task_and_failure():
    # Seleccion por brecha de GM: la mas rezagada es dfthcsos.
    ratios = {"invsqrt": 27.91, "dqi": 70.79, "dfthcsos": 11.39}
    assert select_task(ratios) == "dfthcsos"
    share = effort_share(ratios)
    assert abs(sum(share.values()) - 1.0) < 1e-9
    # La mas rezagada recibe mas esfuerzo que la mas avanzada.
    assert share["dfthcsos"] > share["dqi"]
    assert share["dfthcsos"] > share["invsqrt"]
    # Violacion dura -> s cae rapido (forzado a <= 0.3).
    e = AdaptiveSearch(k=0.2, s=0.8, window=10, stall_limit=10)
    e.record("f", False, hard_violation=True)
    assert e.aggressiveness() <= 0.3
    # Sin violacion dura, un fracaso normal no fuerza s a <= 0.3.
    f = AdaptiveSearch(k=0.2, s=0.8, window=10, stall_limit=10)
    f.record("f", False, hard_violation=False)
    assert f.aggressiveness() > 0.3
    print("adaptive task + failure: OK")


def test_package_audit():
    import zipfile, io
    import numpy as np
    # Zip valido minimo: invsqrt.kmb, dqi.kmb, dfthcsos/angle_k_0.kmb,
    # dfthcsos/angle_k_1.kmb, dfthcsos/submission.npz con las 7 claves.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("invsqrt.kmb", b"x")
        z.writestr("dqi.kmb", b"x")
        z.writestr("dfthcsos/angle_k_0.kmb", b"x")
        z.writestr("dfthcsos/angle_k_1.kmb", b"x")
        nb = io.BytesIO()
        np.savez(nb, U=np.zeros(2), W=np.zeros(2), H2_I=np.zeros(2),
                 H1_I=np.zeros(2), Hsym_lower=np.zeros(2),
                 tree_edges=np.zeros(2, dtype=int))
        z.writestr("dfthcsos/submission.npz", nb.getvalue())
    open("/tmp/test_pkg_ok.zip", "wb").write(buf.getvalue())
    res = audit_zip("/tmp/test_pkg_ok.zip")
    assert res["ok"], res["errors"]
    # Zip con hueco en angle_k (falta angle_k_1) -> error.
    buf2 = io.BytesIO()
    with zipfile.ZipFile(buf2, "w") as z:
        z.writestr("invsqrt.kmb", b"x")
        z.writestr("dqi.kmb", b"x")
        z.writestr("dfthcsos/angle_k_0.kmb", b"x")
        z.writestr("dfthcsos/angle_k_2.kmb", b"x")
        z.writestr("dfthcsos/submission.npz", nb.getvalue())
    open("/tmp/test_pkg_bad.zip", "wb").write(buf2.getvalue())
    res2 = audit_zip("/tmp/test_pkg_bad.zip")
    assert not res2["ok"] and any("hueco" in e for e in res2["errors"])
    # Zip sin submission.npz -> error.
    buf3 = io.BytesIO()
    with zipfile.ZipFile(buf3, "w") as z:
        z.writestr("invsqrt.kmb", b"x")
        z.writestr("dqi.kmb", b"x")
        z.writestr("dfthcsos/angle_k_0.kmb", b"x")
    open("/tmp/test_pkg_no_npz.zip", "wb").write(buf3.getvalue())
    res3 = audit_zip("/tmp/test_pkg_no_npz.zip")
    assert not res3["ok"]
    print("package audit: OK")


if __name__ == "__main__":
    test_motifs()
    test_motifs_metric_impact()
    test_motifs_gm_gap()
    test_adaptive()
    test_adaptive_task_and_failure()
    test_package_audit()
    print("TODOS LOS TESTS PASAN")

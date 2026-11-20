"""Tests de los huecos H3, H4, H5, H6 y H21 (auditoría MORPH/JSON/
orquestador, v2.17.15).

- H3: load_plan no tira pasos en texto: los que no se pueden
  convertir quedan en `unparsed`.
- H4: load_plan pliega la meta y el presupuesto de las directivas,
  y run_orchestrator usa esa meta.
- H5: pasos y métodos se validan contra STEPS/METHODS; un método
  inválido se rechaza, no se acepta (y no llega al túnel).
- H6: move() a un destino que no está en el plan devuelve False
  y no mueve nada.
- H21: operations.validate_submission corre la auditoría de
  empaquetado (vqcc/package_audit) y registra su resultado.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import numpy as np
import pytest

from auto_mvp.json_directive import load_plan, parse_directive
from auto_mvp.operations import (apply_morph_tunnel, decode_json_config,
                                 run_orchestrator, validate_submission)
from auto_mvp.step_plan import StepPlan

GRAPH = {"source": "cost_model", "root": {
    "name": "dqi-bm-forney", "kind": "dqi", "t_count": 1511522,
    "qubits": 1414, "rotations": 0, "cliffords": 0,
    "children": [
        [{"name": "bm_forward", "kind": "bm_forward", "t_count": None,
          "qubits": None, "rotations": 0, "cliffords": 0,
          "children": []}, 1],
        [{"name": "chien", "kind": "chien", "t_count": None,
          "qubits": None, "rotations": 0, "cliffords": 0,
          "children": []}, 1]]}}


# --- H3: pasos en texto que no se convierten -> unparsed ---

def test_h3_string_steps_no_convertibles_van_a_unparsed():
    plan = load_plan({"steps": ["tunela chien",
                                "reordena gate antes que proxy",
                                "usa numeric para proxy"]})
    assert plan["steps"] == [{"step": "proxy", "method": "numeric",
                              "params": {}}]
    raws = [d.raw for d in plan["unparsed"]]
    assert raws == ["tunela chien", "reordena gate antes que proxy"]
    assert all(d.reason for d in plan["unparsed"])


def test_h3_string_step_desconocido_no_desaparece():
    plan = load_plan({"steps": ["haz magia con los qubits"]})
    assert plan["steps"] == []
    assert len(plan["unparsed"]) == 1
    assert plan["unparsed"][0].raw == "haz magia con los qubits"


def test_h3_dict_step_invalido_no_desaparece():
    plan = load_plan({"steps": [{"step": "banana", "method": "numeric"},
                                {"step": "proxy", "method": "beam"}]})
    assert plan["steps"] == []
    assert len(plan["unparsed"]) == 2
    assert all(d.reason for d in plan["unparsed"])


# --- H4: la meta y el presupuesto de las directivas se pliegan ---

def test_h4_directiva_meta_se_pliega_en_el_plan():
    plan = load_plan({"directives": ["meta 30"]})
    assert plan["meta_mvp"] == 30.0


def test_h4_directiva_presupuesto_se_pliega_en_el_plan():
    plan = load_plan({"directives": ["presupuesto 20 intentos",
                                     "presupuesto 6 horas"]})
    assert plan["budget"] == {"trials": 20.0, "hours": 6.0}


def test_h4_directiva_meta_manda_sobre_la_clave_explicita():
    plan = load_plan({"meta_mvp": 2.0, "directives": ["sube la meta a 30"]})
    assert plan["meta_mvp"] == 30.0


def test_h4_decode_json_config_devuelve_meta_y_presupuesto_plegados():
    out = decode_json_config({"directives": ["meta 30",
                                            "presupuesto 20 intentos"]})
    assert out["meta_mvp"] == 30.0
    assert out["budget"] == {"trials": 20.0}


def test_h4_run_orchestrator_usa_la_meta_de_la_directiva(tmp_path):
    res = run_orchestrator([], config={"directives": ["meta 2"]},
                           runs_dir=tmp_path / "runs")
    assert res["meta_mvp"] == 2.0
    assert res["screened"] == 0


# --- H5: validación contra STEPS/METHODS ---

def test_h5_metodo_invalido_no_se_acepta_en_parse():
    d = parse_directive("reemplaza proxy por banana")
    assert not d.parsed and d.reason
    assert "banana" in d.reason


def test_h5_paso_invalido_no_se_acepta_en_parse():
    assert not parse_directive("reemplaza banana por numeric").parsed
    assert not parse_directive("reordena banana antes que gate").parsed
    assert not parse_directive("inserta banana despues de compile").parsed
    assert not parse_directive("quita banana").parsed


def test_h5_metodo_de_otro_paso_no_se_acepta():
    # beam es método de tunnel, no de proxy.
    assert not parse_directive("usa beam para proxy").parsed
    assert not parse_directive("cambia gate a beam").parsed


def test_h5_replace_method_rechaza_metodo_invalido():
    plan = StepPlan()
    assert plan.replace_method("proxy", "banana") is False
    assert plan.method_of("proxy") == "metadata"
    assert plan.replace_method("banana", "numeric") is False
    assert plan.replace_method("tunnel", "beam") is True
    assert plan.method_of("tunnel") == "beam"


def test_h5_apply_no_instala_metodo_invalido():
    plan = StepPlan()
    assert plan.apply(parse_directive("reemplaza proxy por banana")) is False
    assert plan.method_of("proxy") == "metadata"
    assert plan.apply(parse_directive("usa banana en vez de greedy")) is False
    assert plan.method_of("tunnel") == "greedy"


def test_h5_insert_rechaza_paso_y_metodo_invalidos():
    plan = StepPlan()
    assert plan.insert("banana", "dcp", before="proxy") is False
    assert plan.insert("calibrate", "banana", before="proxy") is False
    assert plan.insert("calibrate", "dcp", before="proxy") is True


def test_h5_metodo_tunel_invalido_no_llega_a_morph_tunnel():
    with pytest.raises(ValueError, match="banana"):
        apply_morph_tunnel(GRAPH, method="banana")
    out = apply_morph_tunnel(GRAPH, method="greedy")
    assert out["final_T"] < out["baseline_T"]  # greedy sí tunela


# --- H6: move() a destino inexistente no mueve nada ---

def test_h6_move_a_destino_inexistente_no_mueve():
    plan = StepPlan()
    antes = plan.order
    assert plan.move("tunnel", before="verify") is False
    assert plan.order == antes
    assert plan.move("tunnel", after="verify") is False
    assert plan.order == antes
    assert plan.log == []


def test_h6_move_a_destino_existente_sigue_funcionando():
    plan = StepPlan()
    assert plan.move("tunnel", after="gate") is True
    assert plan.order == ["proxy", "gate", "tunnel", "compile", "observe"]
    assert plan.move("observe", before="proxy") is True
    assert plan.order[0] == "observe"


# --- H21: validate_submission corre la auditoría de empaquetado ---

NPZ_KEYS = ("U", "W", "H2_I", "H1_I", "Hsym_lower", "tree_edges")


def _npz_bytes() -> bytes:
    buf = io.BytesIO()
    np.savez(buf, **{k: np.zeros(2) for k in NPZ_KEYS})
    return buf.getvalue()


def _zip_submission(path: Path, gap: bool = False,
                    npz_bytes: bytes | None = None) -> Path:
    names = {"invsqrt.kmb": b"x", "dqi.kmb": b"x",
             "dfthcsos/angle_k_0.kmb": b"x",
             "dfthcsos/submission.npz": _npz_bytes()
             if npz_bytes is None else npz_bytes}
    if not gap:
        names["dfthcsos/angle_k_1.kmb"] = b"x"
    else:
        names["dfthcsos/angle_k_2.kmb"] = b"x"
    with zipfile.ZipFile(path, "w") as z:
        for name, data in names.items():
            z.writestr(name, data)
    return path


def test_h21_validate_submission_registra_la_auditoria(tmp_path):
    z = _zip_submission(tmp_path / "submission.zip")
    out = validate_submission(z)
    assert out["packaging"]["ok"] is True
    assert out["package_audit"]["ok"] is True, out["package_audit"]
    assert out["package_audit"]["files"]


def test_h21_auditoria_falla_con_hueco_en_angle_k(tmp_path):
    z = _zip_submission(tmp_path / "gap.zip", gap=True)
    out = validate_submission(z)
    assert out["package_audit"]["ok"] is False
    assert any("hueco" in e for e in out["package_audit"]["errors"])


def test_h21_validate_submission_dir_tambien_audita(tmp_path):
    d = tmp_path / "sub"
    (d / "dfthcsos").mkdir(parents=True)
    (d / "invsqrt.kmb").write_bytes(b"x")
    (d / "dqi.kmb").write_bytes(b"x")
    (d / "dfthcsos" / "angle_k_0.kmb").write_bytes(b"x")
    (d / "dfthcsos" / "submission.npz").write_bytes(_npz_bytes())
    out = validate_submission(d)
    assert out["package_audit"]["ok"] is True, out["package_audit"]


def test_h21_auditoria_cierra_la_puerta_aunque_packaging_pase(
        tmp_path, monkeypatch):
    # La auditoría real es un subconjunto de packaging.py (sus
    # reglas de estructura ya las cubre packaging), así que el
    # cierre por auditoría se prueba con una falla simulada: el
    # cableado debe degradar READY a NOT_CREATED y registrar el
    # motivo de la auditoría.
    import auto_mvp.vqcc.package_audit as pa
    monkeypatch.setattr(
        pa, "audit_zip",
        lambda p: {"ok": False, "errors": ["falla simulada de auditoría"],
                   "files": []})
    z = _zip_submission(tmp_path / "ok.zip")
    out = validate_submission(
        z, task_statuses={"invsqrt": "PASS", "dqi": "PASS",
                          "dfthcsos": "PASS"})
    assert out["packaging"]["ok"] is True
    assert out["package_audit"]["ok"] is False
    assert out["submission"]["status"] == "NOT_CREATED"
    assert any("auditor" in r and "falla simulada" in r
               for r in out["submission"]["reasons"])


def test_h21_auditoria_ok_deja_ready_con_puerta_pass(tmp_path):
    z = _zip_submission(tmp_path / "ok.zip")
    out = validate_submission(
        z, task_statuses={"invsqrt": "PASS", "dqi": "PASS",
                          "dfthcsos": "PASS"})
    assert out["submission"]["status"] == "READY"

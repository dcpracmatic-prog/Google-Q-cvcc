"""AUTO_MVP v0.9.0 — formato del submission.zip y su validador.

Verifica, con ZIPs reales (contenido falso, formato real: el
validador revisa el FORMATO, no el contenido), que:
- Un ZIP con el formato oficial pasa (rutas exactas, angle_k
  consecutivos, NPZ con las 6 claves).
- Cada desviación falla, con su motivo: duplicados (la v0.3.0),
  huecos en angle_k, directorio raíz extra, archivo extra, falta
  invsqrt/dqi, NPZ sin clave, NPZ ilegible.
- El constructor arma el ZIP con la estructura correcta y lo
  borra si no pasa la validación (fail-closed).
- submission_ready da READY solo si la puerta fail-closed Y el
  formato pasan; sin validación de formato, NO se arma el ZIP.
"""
from __future__ import annotations

import json
import subprocess
import zipfile
from pathlib import Path

import numpy as np
import pytest

from auto_mvp.packaging import (EXPECTED_NPZ_KEYS, build_submission_zip,
                                submission_ready, validate_submission_dir,
                                validate_submission_zip)

VENV_PY = "/home/hatch/workspace/sandbox-run/venv/bin/python"
KEYS = list(EXPECTED_NPZ_KEYS)


def _npz(path: Path, keys: list[str] | None = None) -> Path:
    np.savez(path, **{k: np.zeros(2) for k in (keys or KEYS)})
    return path


def _files(tmp_path: Path) -> dict[str, Path]:
    d = tmp_path / "src"
    d.mkdir()
    out = {"invsqrt": d / "invsqrt.kmb", "dqi": d / "dqi.kmb",
           "a0": d / "angle_k_0.kmb", "a1": d / "angle_k_1.kmb",
           "npz": d / "submission.npz"}
    for k, p in out.items():
        if k == "npz":
            _npz(p)
        else:
            p.write_bytes(b"circuito falso (formato, no contenido)")
    return out


def _zip(tmp_path: Path, entries: dict[str, Path | bytes]) -> Path:
    z = tmp_path / "submission.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for name, src in entries.items():
            if isinstance(src, bytes):
                zf.writestr(name, src)
            else:
                zf.write(src, name)
    return z


def _valid(tmp_path: Path) -> Path:
    f = _files(tmp_path)
    return _zip(tmp_path, {"invsqrt.kmb": f["invsqrt"],
                           "dqi.kmb": f["dqi"],
                           "dfthcsos/angle_k_0.kmb": f["a0"],
                           "dfthcsos/angle_k_1.kmb": f["a1"],
                           "dfthcsos/submission.npz": f["npz"]})


def test_valid_zip_passes(tmp_path):
    out = validate_submission_zip(_valid(tmp_path))
    assert out["ok"] is True, out
    assert out["angles"] == 2 and out["npz_keys"] == sorted(KEYS)
    assert out["reasons"] == [] and out["warnings"] == []


def test_valid_kmx_and_one_angle(tmp_path):
    f = _files(tmp_path)
    z = _zip(tmp_path, {"invsqrt.kmx": f["invsqrt"],
                        "dqi.kmx": f["dqi"],
                        "dfthcsos/angle_k_0.kmx": f["a0"],
                        "dfthcsos/submission.npz": f["npz"]})
    assert validate_submission_zip(z)["ok"] is True


def test_duplicates_fail(tmp_path):
    f = _files(tmp_path)
    # La v0.3.0: el mismo archivo en dos rutas (invsqrt.kmb y .kmx).
    z = _zip(tmp_path, {"invsqrt.kmb": f["invsqrt"],
                        "invsqrt.kmx": f["invsqrt"],
                        "dqi.kmb": f["dqi"],
                        "dfthcsos/angle_k_0.kmb": f["a0"],
                        "dfthcsos/submission.npz": f["npz"]})
    out = validate_submission_zip(z)
    assert out["ok"] is False
    assert any("duplicado" in r for r in out["reasons"])
    # Y dos entradas con el mismo nombre dentro del ZIP.
    z2 = tmp_path / "dup.zip"
    with zipfile.ZipFile(z2, "w") as zf:
        zf.writestr("invsqrt.kmb", b"a")
        zf.writestr("invsqrt.kmb", b"b")
        zf.writestr("dqi.kmb", b"c")
        zf.writestr("dfthcsos/angle_k_0.kmb", b"d")
        zf.writestr("dfthcsos/submission.npz",
                    (tmp_path / "src" / "submission.npz").read_bytes())
    out2 = validate_submission_zip(z2)
    assert out2["ok"] is False
    assert any("duplicados" in r for r in out2["reasons"])


def test_gaps_and_extra_root_and_extra_file(tmp_path):
    f = _files(tmp_path)
    # Hueco: angle_k_0 y angle_k_2, sin angle_k_1.
    z = _zip(tmp_path, {"invsqrt.kmb": f["invsqrt"],
                        "dqi.kmb": f["dqi"],
                        "dfthcsos/angle_k_0.kmb": f["a0"],
                        "dfthcsos/angle_k_2.kmb": f["a1"],
                        "dfthcsos/submission.npz": f["npz"]})
    out = validate_submission_zip(z)
    assert out["ok"] is False and any("huecos" in r for r in out["reasons"])
    # Directorio raíz extra.
    z = _zip(tmp_path, {"submission/invsqrt.kmb": f["invsqrt"],
                        "submission/dqi.kmb": f["dqi"],
                        "submission/dfthcsos/angle_k_0.kmb": f["a0"],
                        "submission/dfthcsos/submission.npz": f["npz"]})
    out = validate_submission_zip(z)
    assert out["ok"] is False
    assert any("fuera del formato" in r for r in out["reasons"])
    # Archivo extra.
    z = _zip(tmp_path, {"invsqrt.kmb": f["invsqrt"],
                        "dqi.kmb": f["dqi"],
                        "dfthcsos/angle_k_0.kmb": f["a0"],
                        "dfthcsos/submission.npz": f["npz"],
                        "README.txt": b"extra"})
    assert validate_submission_zip(z)["ok"] is False


def test_missing_files_and_npz_keys(tmp_path):
    f = _files(tmp_path)
    # Falta invsqrt.
    z = _zip(tmp_path, {"dqi.kmb": f["dqi"],
                        "dfthcsos/angle_k_0.kmb": f["a0"],
                        "dfthcsos/submission.npz": f["npz"]})
    out = validate_submission_zip(z)
    assert out["ok"] is False and any("falta invsqrt" in r for r in out["reasons"])
    # NPZ sin una clave.
    bad_npz = _npz(tmp_path / "bad.npz", keys=KEYS[:-1])
    z = _zip(tmp_path, {"invsqrt.kmb": f["invsqrt"],
                        "dqi.kmb": f["dqi"],
                        "dfthcsos/angle_k_0.kmb": f["a0"],
                        "dfthcsos/submission.npz": bad_npz})
    out = validate_submission_zip(z)
    assert out["ok"] is False
    assert any("sin claves" in r and "tree_edges" in r for r in out["reasons"])
    # NPZ con una clave extra: aviso, no fallo.
    extra_npz = _npz(tmp_path / "extra.npz", keys=KEYS + ["extra"])
    z = _zip(tmp_path, {"invsqrt.kmb": f["invsqrt"],
                        "dqi.kmb": f["dqi"],
                        "dfthcsos/angle_k_0.kmb": f["a0"],
                        "dfthcsos/submission.npz": extra_npz})
    out = validate_submission_zip(z)
    assert out["ok"] is True and len(out["warnings"]) == 1
    # NPZ ilegible (no es un zip).
    z = _zip(tmp_path, {"invsqrt.kmb": f["invsqrt"],
                        "dqi.kmb": f["dqi"],
                        "dfthcsos/angle_k_0.kmb": f["a0"],
                        "dfthcsos/submission.npz": b"no es un npz"})
    assert validate_submission_zip(z)["ok"] is False


def test_dir_validator(tmp_path):
    f = _files(tmp_path)
    d = tmp_path / "sub"
    (d / "dfthcsos").mkdir(parents=True)
    for src, name in ((f["invsqrt"], "invsqrt.kmb"),
                      (f["dqi"], "dqi.kmb"),
                      (f["a0"], "dfthcsos/angle_k_0.kmb"),
                      (f["npz"], "dfthcsos/submission.npz")):
        (d / name).write_bytes(src.read_bytes())
    assert validate_submission_dir(d)["ok"] is True
    # angle_k_0 y angle_k_1: consecutivos, sigue pasando.
    (d / "dfthcsos" / "angle_k_1.kmb").write_bytes(b"x")
    assert validate_submission_dir(d)["ok"] is True
    (d / "extra.txt").write_text("x")
    assert validate_submission_dir(d)["ok"] is False


def test_builder_builds_and_validates(tmp_path):
    f = _files(tmp_path)
    out = build_submission_zip(f["invsqrt"], f["dqi"], [f["a0"], f["a1"]],
                               f["npz"], tmp_path / "out" / "submission.zip")
    assert out["ok"] is True and out["angles"] == 2
    assert Path(out["path"]).is_file()
    # Con un NPZ sin clave, el ZIP armado no pasa y se BORRA.
    bad_npz = _npz(tmp_path / "bad.npz", keys=KEYS[:-1])
    out = build_submission_zip(f["invsqrt"], f["dqi"], [f["a0"]],
                               bad_npz, tmp_path / "out2" / "submission.zip")
    assert out["ok"] is False
    assert not Path(out["path"]).exists()


def test_submission_ready_needs_gate_and_format(tmp_path):
    good = validate_submission_zip(_valid(tmp_path))
    assert good["ok"] is True
    ok_tasks = {"invsqrt": "PASS", "dqi": "PASS", "dfthcsos": "PASS"}
    assert submission_ready(ok_tasks, good)["status"] == "READY"
    # Sin validación de formato, NO se arma el ZIP.
    assert submission_ready(ok_tasks, None)["status"] == "NOT_CREATED"
    # Con formato malo, NO se arma.
    bad = validate_submission_zip(tmp_path / "no-existe.zip")
    assert submission_ready(ok_tasks, bad)["status"] == "NOT_CREATED"
    # Con la puerta en NOT_RUN, NO se arma aunque el formato pase.
    assert submission_ready({"invsqrt": "NOT_RUN", "dqi": "PASS",
                             "dfthcsos": "PASS"}, good)["status"] == "NOT_CREATED"
    # En modo smoke tampoco (la puerta exige full).
    assert submission_ready(ok_tasks, good, mode="smoke")["status"] == "NOT_CREATED"


def test_cli_validate_and_mcp_validate(tmp_path):
    z = _valid(tmp_path)
    r = subprocess.run([VENV_PY, "-m", "auto_mvp.cli", "validate",
                        "--path", str(z)], capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["packaging"]["ok"] is True
    r = subprocess.run([VENV_PY, "-m", "auto_mvp.cli", "validate",
                        "--path", str(z), "--tasks",
                        '{"invsqrt": "PASS", "dqi": "PASS", "dfthcsos": "PASS"}'],
                       capture_output=True, text=True, timeout=120)
    assert json.loads(r.stdout)["submission"]["status"] == "READY"
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                            / "skills" / "auto-mvp-vqcc"))
    from mcp_server import handle
    resp = handle({"jsonrpc": "2.0", "id": 8, "method": "tools/call",
                   "params": {"name": "validate_submission",
                              "arguments": {"path": str(z)}}})
    text = json.loads(resp["result"]["content"][0]["text"])
    assert text["packaging"]["ok"] is True

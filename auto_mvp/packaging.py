"""AUTO_MVP — formato del submission.zip y su validador (desde v0.9.0).

El formato oficial (guía VQCC 2026-11-06 + verificadores en disco;
la v0.3.0 falló justo por duplicados en otras rutas, así que el
formato ahora vive en el repo, no solo en memoria):

    invsqrt.kmb  (o invsqrt.kmx, UNO solo)
    dqi.kmb      (o dqi.kmx, UNO solo)
    dfthcsos/
        angle_k_0.kmb  (o .kmx)
        angle_k_1.kmb
        ...            (consecutivos desde 0, SIN huecos)
        submission.npz (claves: U, W, H2_I, H1_I, Hsym_lower, tree_edges)

Reglas que el validador comprueba (fail-closed: cualquier fallo
bloquea el envío, igual que la puerta de los verificadores):
- Sin directorio raíz extra (todo cuelga de la raíz del ZIP).
- Sin duplicados (ni el mismo archivo en dos rutas, ni dos
  entradas con el mismo nombre dentro del ZIP).
- Exactamente un invsqrt y un dqi (.kmb o .kmx, no los dos).
- angle_k consecutivos desde 0, sin huecos, cada uno .kmb o .kmx.
- submission.npz presente, con las 6 claves (se leen los nombres
  de los .npy dentro del npz, solo stdlib, sin numpy).
- Nada fuera del formato (ni archivos extra, ni ocultos).

El validador revisa el FORMATO, no el contenido: que un circuito
sea correcto, que la química cumpla sus umbrales o que el S sea
bueno es trabajo de los verificadores oficiales (la puerta
fail-closed). Un ZIP con formato válido y circuitos malos sigue
siendo basura: el formato no sustituye al verificador.
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Any, Callable

EXPECTED_NPZ_KEYS = ("U", "W", "H2_I", "H1_I", "Hsym_lower", "tree_edges")
ANGLE_RE = re.compile(r"^dfthcsos/angle_k_(\d+)\.(kmb|kmx)$")
TOP = {"invsqrt.kmb", "invsqrt.kmx", "dqi.kmb", "dqi.kmx"}
NPZ_PATH = "dfthcsos/submission.npz"


def npz_keys(path: str | Path) -> list[str]:
    """Las claves de un .npz, leyendo los nombres de los .npy (stdlib)."""
    with zipfile.ZipFile(path) as zf:
        return sorted(n[:-4] for n in zf.namelist()
                      if n.endswith(".npy"))


def _check(names: list[str],
           read_npz_keys: Callable[[], list[str] | None]) -> dict[str, Any]:
    """El chequeo, común al ZIP y al directorio (nombres relativos)."""
    reasons: list[str] = []
    warnings: list[str] = []
    files = sorted(n for n in names if not n.endswith("/"))
    # Duplicados dentro del ZIP (el mismo nombre dos veces).
    if len(files) != len(set(files)):
        dupes = sorted({n for n in files if files.count(n) > 1})
        reasons.append(f"duplicados en el ZIP: {dupes}")
    # Nada fuera del formato ni directorio raíz extra.
    for n in files:
        if n in TOP or n == NPZ_PATH or ANGLE_RE.match(n):
            continue
        reasons.append(f"fuera del formato: {n!r}")
    # Exactamente un invsqrt y un dqi (.kmb o .kmx, no los dos).
    for stem in ("invsqrt", "dqi"):
        have = [n for n in files if n in {f"{stem}.kmb", f"{stem}.kmx"}]
        if len(have) == 0:
            reasons.append(f"falta {stem}.kmb o {stem}.kmx")
        elif len(have) > 1:
            reasons.append(f"duplicado: {stem} aparece como {have}")
    # angle_k consecutivos desde 0, sin huecos, uno por índice.
    idxs: list[int] = []
    for n in files:
        m = ANGLE_RE.match(n)
        if m:
            idxs.append(int(m.group(1)))
    if not idxs:
        reasons.append("faltan los circuitos angle_k_* en dfthcsos/")
    else:
        if sorted(idxs) != list(range(len(idxs))):
            reasons.append(
                f"angle_k con huecos o repetidos: {sorted(idxs)}")
        if len(idxs) != len(set(idxs)):
            reasons.append(f"angle_k repetido: {sorted(idxs)}")
    # submission.npz con las 6 claves.
    keys: list[str] | None = None
    if NPZ_PATH not in files:
        reasons.append("falta dfthcsos/submission.npz")
    else:
        try:
            keys = read_npz_keys()
        except Exception as e:  # npz corrupto o ilegible
            reasons.append(f"submission.npz ilegible: {e}")
            keys = None
        if keys is not None:
            missing = [k for k in EXPECTED_NPZ_KEYS if k not in keys]
            if missing:
                reasons.append(f"submission.npz sin claves: {missing}")
            extra = [k for k in keys if k not in EXPECTED_NPZ_KEYS]
            if extra:
                warnings.append(f"submission.npz con claves extra: {extra}")
    return {"ok": not reasons, "reasons": reasons, "warnings": warnings,
            "files": files, "angles": len(idxs),
            "npz_keys": keys}


def validate_submission_zip(path: str | Path) -> dict[str, Any]:
    """Valida el formato de un submission.zip (fail-closed)."""
    path = Path(path)
    if not path.is_file():
        return {"ok": False, "reasons": [f"no existe el ZIP: {path}"],
                "warnings": [], "files": [], "angles": 0, "npz_keys": None}
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            bad = zf.testzip()
            if bad is not None:
                return {"ok": False,
                        "reasons": [f"entrada corrupta en el ZIP: {bad}"],
                        "warnings": [], "files": names, "angles": 0,
                        "npz_keys": None}
            npz_bytes = zf.read(NPZ_PATH) if NPZ_PATH in names else None
    except zipfile.BadZipFile as e:
        return {"ok": False, "reasons": [f"ZIP inválido: {e}"],
                "warnings": [], "files": [], "angles": 0, "npz_keys": None}

    def _keys() -> list[str] | None:
        if npz_bytes is None:
            return None
        with zipfile.ZipFile(io.BytesIO(npz_bytes)) as nzf:
            return sorted(n[:-4] for n in nzf.namelist()
                          if n.endswith(".npy"))

    out = _check(names, _keys)
    out["path"] = str(path)
    return out


def validate_submission_dir(path: str | Path) -> dict[str, Any]:
    """Valida el formato de un directorio de submission (antes de zip)."""
    path = Path(path)
    if not path.is_dir():
        return {"ok": False, "reasons": [f"no existe el directorio: {path}"],
                "warnings": [], "files": [], "angles": 0, "npz_keys": None}
    names = sorted(str(p.relative_to(path)).replace("\\", "/")
                   for p in path.rglob("*") if p.is_file())
    npz = path / NPZ_PATH
    out = _check(names, lambda: npz_keys(npz) if npz.is_file() else None)
    out["path"] = str(path)
    return out


def build_submission_zip(invsqrt: str | Path, dqi: str | Path,
                         angles: list[str | Path], npz: str | Path,
                         out_path: str | Path) -> dict[str, Any]:
    """Arma el submission.zip con la estructura correcta y lo valida.

    angles van en orden (angle_k_0, angle_k_1, ...). Si el ZIP
    armado no pasa la validación, se BORRA (fail-closed: no queda
    un ZIP malo que se pueda enviar por error) y se devuelven los
    motivos.
    """
    invsqrt, dqi, npz = Path(invsqrt), Path(dqi), Path(npz)
    out_path = Path(out_path)
    for p, what in ((invsqrt, "invsqrt"), (dqi, "dqi"), (npz, "npz")):
        if not p.is_file():
            return {"ok": False, "path": str(out_path),
                    "reasons": [f"falta el archivo {what}: {p}"],
                    "warnings": [], "files": [], "angles": 0,
                    "npz_keys": None}
    if not angles:
        return {"ok": False, "path": str(out_path),
                "reasons": ["no hay circuitos angle_k_*"],
                "warnings": [], "files": [], "angles": 0, "npz_keys": None}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w",
                         compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(invsqrt, f"invsqrt{invsqrt.suffix}")
        zf.write(dqi, f"dqi{dqi.suffix}")
        for i, a in enumerate(angles):
            a = Path(a)
            zf.write(a, f"dfthcsos/angle_k_{i}{a.suffix}")
        zf.write(npz, NPZ_PATH)
    result = validate_submission_zip(out_path)
    if not result["ok"]:
        out_path.unlink(missing_ok=True)  # fail-closed: no queda ZIP malo
        result["path"] = str(out_path)
    return result


def submission_ready(task_statuses: dict[str, str],
                     packaging: dict[str, Any] | None = None,
                     mode: str = "full") -> dict[str, Any]:
    """¿Se puede armar el submission.zip? Puerta + formato, fail-closed.

    La puerta (los tres verificadores en modo full) Y el formato
    del ZIP deben pasar. Si falta la validación del formato, el
    resultado lo dice y NO se arma el ZIP.
    """
    from .numeric_lab import fail_closed_gate
    gate = fail_closed_gate(task_statuses, mode=mode)
    reasons = list(gate.get("reasons", []))
    if gate["status"] != "FULL_LOCAL_VERIFIERS_PASS":
        return {"status": "NOT_CREATED", "reasons": reasons,
                "gate": gate, "packaging": packaging}
    if packaging is None:
        reasons.append("falta la validación del formato del ZIP "
                       "(validate_submission_zip)")
        return {"status": "NOT_CREATED", "reasons": reasons,
                "gate": gate, "packaging": None}
    if not packaging.get("ok"):
        reasons.extend(packaging.get("reasons", []))
        return {"status": "NOT_CREATED", "reasons": reasons,
                "gate": gate, "packaging": packaging}
    return {"status": "READY", "reasons": reasons, "gate": gate,
            "packaging": packaging}

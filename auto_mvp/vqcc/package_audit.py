"""Auditoria de empaquetado .zip antes de enviar (Ley Cuantica v6.1, punto 4).

Disciplina de envios: 5 envios diarios, ~45 min por evaluacion, hasta
2 entregas finales. No se gasta un envio por un error de formato.
Esta auditoria valida el .zip ANTES de enviar:
- En la raiz: invsqrt.kmb/.kmx y dqi.kmb/.kmx (exactamente esos nombres).
- Carpeta dfthcsos/ con angle_k_0, angle_k_1, ... consecutivos sin huecos.
- dfthcsos/submission.npz con las claves exactas (U, W, H2_I, H1_I,
  Hsym_lower, tree_edges).
- Sin directorios raiz extra (nada fuera de invsqrt, dqi, dfthcsos).
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

REQUIRED_NPZ_KEYS = {"U", "W", "H2_I", "H1_I", "Hsym_lower", "tree_edges"}
ANGLE_RE = re.compile(r"^dfthcsos/angle_k_(\d+)\.(kmb|kmx)$")


def audit_zip(zip_path: str | Path) -> dict:
    """Audita un submission.zip. Devuelve {"ok": bool, "errors": [...],
    "files": [...]}. ok=True solo si pasa todas las reglas."""
    errors: list[str] = []
    zpath = Path(zip_path)
    if not zpath.is_file():
        return {"ok": False, "errors": [f"no existe: {zpath}"], "files": []}
    with zipfile.ZipFile(zpath) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
    files = sorted(names)
    # 1) Raiz: invsqrt y dqi (kmb o kmx).
    for base in ("invsqrt", "dqi"):
        if not any(n in (f"{base}.kmb", f"{base}.kmx") for n in names):
            errors.append(f"falta {base}.kmb/.kmx en la raiz")
    # 2) Sin directorios raiz extra.
    roots = {n.split("/")[0] for n in names if "/" in n}
    roots |= {n for n in names if "/" not in n}
    allowed_roots = {"invsqrt.kmb", "invsqrt.kmx", "dqi.kmb", "dqi.kmx", "dfthcsos"}
    extra = roots - allowed_roots
    if extra:
        errors.append(f"directorios/archivos raiz extra: {sorted(extra)}")
    # 3) dfthcsos/angle_k_i consecutivos sin huecos, desde 0.
    idxs = sorted(int(m.group(1)) for n in names if (m := ANGLE_RE.match(n)))
    if not idxs:
        errors.append("faltan angle_k_*.kmb/.kmx en dfthcsos/")
    elif idxs != list(range(len(idxs))):
        errors.append(f"angle_k con huecos o sin empezar en 0: {idxs}")
    # 4) dfthcsos/submission.npz con las claves exactas.
    if "dfthcsos/submission.npz" not in names:
        errors.append("falta dfthcsos/submission.npz")
    else:
        try:
            import numpy as np
            import io
            with zipfile.ZipFile(zpath) as z:
                data = np.load(io.BytesIO(z.read("dfthcsos/submission.npz")))
            keys = set(data.files)
            missing = REQUIRED_NPZ_KEYS - keys
            if missing:
                errors.append(f"submission.npz sin claves: {sorted(missing)}")
        except Exception as e:
            errors.append(f"no se pudo leer submission.npz: {e}")
    return {"ok": not errors, "errors": errors, "files": files}


def audit_submission_dir(sub_dir: str | Path) -> dict:
    """Audita un directorio de submission (antes de empaquetar)."""
    d = Path(sub_dir)
    if not d.is_dir():
        return {"ok": False, "errors": [f"no existe: {d}"], "files": []}
    import tempfile, os
    tmp = tempfile.mktemp(suffix=".zip")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(d.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(d).as_posix())
    res = audit_zip(tmp)
    os.unlink(tmp)
    return res

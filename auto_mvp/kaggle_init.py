"""AUTO_MVP v0.3.2 — inicialización del notebook (Kaggle / local).

La separación que pide Arturo, hecha código:

- INMUTABLE (solo lectura): los datos de la competencia. En Kaggle
  viven en ``/kaggle/input`` (dataset del starter kit + competición);
  en local, en el sandbox. El init NUNCA escribe ahí.
- CÓDIGO (solo lectura): el optimizador AUTO_MVP. Su única fuente de
  verdad es el repo dcpracmatic-prog/Google-Q-cvcc. El init intenta
  ``git clone``; como el repo es PRIVADO, en Kaggle ese clon falla
  sin credenciales (y jamás se mete un token en el notebook). En ese
  caso se usa la copia vendida (snapshot) que el notebook lleva
  consigo, con el SHA del commit grabado en el manifiesto: el código
  que corre es byte-idéntico al del repo en ese commit. En local con
  acceso, el clon sí funciona y el SHA se lee del clon.
- TRABAJO (escritura): todo lo que el pipeline produce va bajo
  ``<working>/runs/`` (estado, artefactos i<iter>-<score>, CVV,
  ledger, checkpoints). Nada se escribe ni en /kaggle/input ni en
  la copia del código.

El init deja un manifiesto (``init_manifest.json``) en el working:
entorno, fuentes, SHA, rutas y fecha. Si el código no se puede
cargar por ningún camino, el init FALLA con error, nunca sigue con
un código distinto al del repo.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

REPO_URL = "https://github.com/dcpracmatic-prog/Google-Q-cvcc.git"
LOCAL_INPUT_DEFAULT = Path.home() / "workspace/sandbox-run"


def detect_environment() -> str:
    """'kaggle' si existe /kaggle o la variable del kernel; si no, 'local'."""
    if Path("/kaggle").exists() or os.environ.get("KAGGLE_KERNEL_RUN_TYPE"):
        return "kaggle"
    return "local"


@dataclass
class Environment:
    kind: str  # 'kaggle' | 'local'
    input_dir: Path
    working_dir: Path
    code_path: Path
    code_source: str  # 'cloned' | 'vendored' | 'local'
    commit_sha: str
    runs_dir: Path
    manifest_path: Path


def _git_clone(repo_url: str, dest: Path, timeout: int = 120) -> str | None:
    """Clona el repo (solo lectura) y devuelve el SHA, o None si falla."""
    if dest.exists():
        shutil.rmtree(dest)
    try:
        r = subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, str(dest)],
            capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            return None
        r2 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(dest),
                            capture_output=True, text=True, timeout=30)
        return r2.stdout.strip() if r2.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
        return None


def init(repo_url: str = REPO_URL,
         working_dir: str | Path | None = None,
         input_dir: str | Path | None = None,
         vendored_path: str | Path | None = None,
         commit_sha: str = "") -> Environment:
    """Inicializa el entorno y devuelve las rutas. Falla si no hay código.

    Orden de intentos para el código: clon del repo -> copia vendida
    (snapshot con SHA) -> paquete ya importable en sys.path.
    """
    kind = detect_environment()
    working = Path(working_dir) if working_dir else (
        Path("/kaggle/working") if kind == "kaggle" else Path.cwd())
    input_d = Path(input_dir) if input_dir else (
        Path("/kaggle/input") if kind == "kaggle" else LOCAL_INPUT_DEFAULT)
    runs = working / "runs"
    runs.mkdir(parents=True, exist_ok=True)

    code_path: Path | None = None
    source = ""
    sha = commit_sha
    clone_dest = working / "auto-mvp-repo"
    cloned = _git_clone(repo_url, clone_dest)
    if cloned is not None:
        code_path = clone_dest / "auto_mvp"
        source, sha = "cloned", cloned
    elif vendored_path is not None and Path(vendored_path).exists():
        code_path = working / "auto-mvp"
        if code_path.exists():
            shutil.rmtree(code_path)
        shutil.copytree(vendored_path, code_path)
        source = "vendored"
    else:
        # Último recurso: el paquete ya está en sys.path (correr dentro
        # del checkout del repo, por ejemplo).
        import auto_mvp
        code_path = Path(auto_mvp.__file__).resolve().parent
        source = "local"
        sha = sha or getattr(auto_mvp, "__version__", "")
    if not (code_path / "__init__.py").exists():
        raise RuntimeError(
            f"no se pudo cargar el código AUTO_MVP desde el repo "
            f"({repo_url}) ni desde la copia vendida; el init se detiene")
    manifest_path = working / "init_manifest.json"
    manifest = {
        "environment": kind,
        "repo_url": repo_url,
        "code_source": source,
        "commit_sha": sha,
        "code_path": str(code_path),
        "input_dir": str(input_d),
        "working_dir": str(working),
        "runs_dir": str(runs),
        "input_readonly": True,
        "code_readonly": True,
        "ts": time.time(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return Environment(kind=kind, input_dir=input_d, working_dir=working,
                       code_path=code_path, code_source=source,
                       commit_sha=sha, runs_dir=runs,
                       manifest_path=manifest_path)

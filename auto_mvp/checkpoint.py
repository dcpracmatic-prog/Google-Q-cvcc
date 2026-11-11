"""AUTO_MVP v0.3.0 — checkpoint inmediato de cada mejor (fase 5).

La especificación pide "salva asíncrona de récords": cada vez que
aparece una configuración superior, se congela de inmediato como el
MVP temporal certificado, sin esperar al final del ciclo. Este módulo
es esa pieza, con escritura atómica:

- ``save`` escribe a un temporal en el mismo directorio y luego hace
  ``os.replace``: o el checkpoint nuevo está completo, o sigue el
  viejo. Nunca hay un best.json a medias, ni siquiera si el proceso
  muere a mitad de la escritura.
- Se guarda ``best.json`` (el mejor verificado actual) y una copia
  por récord en ``history/best-<checksum8>.json`` (acotado: se
  conservan los últimos 20).
- Solo se guardan mejores VERIFICADOS (el orquestador lo garantiza y
  el payload lo registra en ``verified_by``). Un mejor proyectado
  sin verificar no entra aquí: vive en el ledger, no en el checkpoint.

El payload es JSON plano: S, tarea, mutación, parámetros, evidencia
de integridad resumida (hashes, no circuitos) y el CVV checksum que
lo sella en la cadena.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

MAX_HISTORY = 20


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".tmp.",
                               dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


class Checkpoint:
    """Checkpoint atómico del mejor verificado."""

    def __init__(self, directory: str | Path):
        self.dir = Path(directory)
        self.best_path = self.dir / "best.json"
        self.history_dir = self.dir / "history"

    def save(self, payload: dict[str, Any]) -> Path:
        """Guarda el mejor verificado y devuelve la ruta del snapshot."""
        text = json.dumps(payload, sort_keys=True, indent=1,
                          ensure_ascii=False)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
        _atomic_write(self.best_path, text)
        snap = self.history_dir / f"best-{digest}.json"
        _atomic_write(snap, text)
        self._prune_history()
        return snap

    def _prune_history(self) -> None:
        snaps = sorted(self.history_dir.glob("best-*.json"),
                       key=lambda p: p.stat().st_mtime)
        for old in snaps[:-MAX_HISTORY]:
            try:
                old.unlink()
            except FileNotFoundError:
                pass

    def load(self) -> dict[str, Any] | None:
        if not self.best_path.exists():
            return None
        return json.loads(self.best_path.read_text(encoding="utf-8"))

    def load_history(self) -> list[dict[str, Any]]:
        out = []
        for p in sorted(self.history_dir.glob("best-*.json")):
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except (ValueError, OSError):
                continue
        return out

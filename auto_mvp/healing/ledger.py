"""Bitácora de auditoría append-only (JSONL): qué se detectó, propuso, verificó y aplicó."""
from __future__ import annotations
import json, os, time
from typing import Any, Dict, List, Optional


class Ledger:
    """Bitácora append-only (JSONL). Con max_bytes, rota a 1 MB (idea
    del gobernador v9 de Arturo: rotar al llegar a 1 MB)."""

    def __init__(self, path: Optional[str] = None, max_bytes: Optional[int] = None):
        self.path, self.rows = path, []
        self.max_bytes = max_bytes

    def _rotate_if_needed(self) -> None:
        if not self.path or not self.max_bytes:
            return
        try:
            if os.path.getsize(self.path) >= self.max_bytes:
                rotated = self.path + ".1"
                if os.path.exists(rotated):
                    os.unlink(rotated)
                os.rename(self.path, rotated)
        except FileNotFoundError:
            pass

    def log(self, event: str, **data: Any) -> None:
        row: Dict[str, Any] = {"ts": time.time(), "event": event, **data}
        self.rows.append(row)
        if self.path:
            os.makedirs(os.path.dirname(os.path.abspath(self.path)) or ".", exist_ok=True)
            self._rotate_if_needed()
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    def events(self) -> List[str]:
        return [r["event"] for r in self.rows]

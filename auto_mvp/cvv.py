"""AUTO_MVP v0.3.0 — bitácora con cadena de hashes, vector CVV (fase 4).

Cada hito de mejora se sella con un CVV: el hash del estado anterior,
el checksum del registro actual y quién lo verificó. La cadena es
TAMPER-EVIDENT (si alguien cambia un récord, la cadena se rompe al
recalcularla), NO una firma criptográfica: no hay clave, así que no
prueba quién escribió el récord, solo que nadie lo alteró después.

Esquema de registro (el de la especificación v0.0.1, corregido):
- "score" es el S OFICIAL (R·Q²·T en DQI, Q·C en invsqrt,
  lambda_eff·T·Q en química), no Q. Los ejemplos de la spec ponían
  5630.0 / 1414.1, que son Q, no S.
- Los hashes son reales (sha256 hex); nada de placeholders como
  "dead...beef".
- "logic_integrity": "PASSED" (integridad revisada) o "PASSED_STRICT"
  (integridad + verificación oficial). Un récord sin integridad
  verificada no lleva CVV de récord: se registra como evento, no
  como hito.

La cadena es la genealogía de los récords, no el registro de
intentos: los intentos van al VQCCLedger; aquí solo entran el
baseline, cada mejora aceptada, cada veto por regresión y la
convergencia final.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

GENESIS_PREV = "0" * 64


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def _checksum(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


@dataclass
class CvvRecord:
    """Un hito sellado. ``cvv`` se calcula al añadirlo a la cadena."""
    cycle: int
    phase: str
    target_goal: str
    algebraic_state_hash: str
    score: float
    logic_verified: bool
    status: str
    delta_improvement: str | None = None
    best_found_so_far: bool = False
    veto_reason: str | None = None
    certified: bool = False
    verified_by: str = ""
    logic_integrity: str = "PASSED"
    prev_hash: str = GENESIS_PREV
    checksum: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def payload(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "cycle": self.cycle,
            "phase": self.phase,
            "target_goal": self.target_goal,
            "algebraic_state_hash": self.algebraic_state_hash,
            "score": self.score,
            "logic_verified": self.logic_verified,
            "status": self.status,
            "best_found_so_far": self.best_found_so_far,
            "verified_by": self.verified_by,
            "logic_integrity": self.logic_integrity,
            "prev_hash": self.prev_hash,
        }
        if self.delta_improvement is not None:
            d["delta_improvement"] = self.delta_improvement
        if self.veto_reason is not None:
            d["veto_reason"] = self.veto_reason
        if self.certified:
            d["certified"] = True
        d.update(self.extra)
        return d

    def to_dict(self) -> dict[str, Any]:
        d = self.payload()
        d["cvv"] = {
            "prev_hash": self.prev_hash,
            "checksum": self.checksum,
            "verified_by": self.verified_by,
            "logic_integrity": self.logic_integrity,
        }
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CvvRecord":
        cvv = d.get("cvv", {})
        return cls(
            cycle=int(d["cycle"]),
            phase=str(d["phase"]),
            target_goal=str(d.get("target_goal", "")),
            algebraic_state_hash=str(d.get("algebraic_state_hash", "")),
            score=float(d["score"]),
            logic_verified=bool(d.get("logic_verified", False)),
            status=str(d.get("status", "")),
            delta_improvement=d.get("delta_improvement"),
            best_found_so_far=bool(d.get("best_found_so_far", False)),
            veto_reason=d.get("veto_reason"),
            certified=bool(d.get("certified", False)),
            verified_by=str(d.get("verified_by", cvv.get("verified_by", ""))),
            logic_integrity=str(d.get("logic_integrity",
                                      cvv.get("logic_integrity", "PASSED"))),
            prev_hash=str(d.get("prev_hash", cvv.get("prev_hash", GENESIS_PREV))),
            checksum=str(cvv.get("checksum", "")),
            extra={k: v for k, v in d.items()
                   if k not in {"cycle", "phase", "target_goal",
                                "algebraic_state_hash", "score",
                                "logic_verified", "status",
                                "delta_improvement", "best_found_so_far",
                                "veto_reason", "certified", "verified_by",
                                "logic_integrity", "prev_hash", "cvv"}},
        )


class CvvChain:
    """Cadena de hitos CVV con verificación de integridad."""

    def __init__(self, records: list[CvvRecord] | None = None):
        self.records: list[CvvRecord] = list(records or [])

    def _seal(self, record: CvvRecord) -> CvvRecord:
        record.prev_hash = (self.records[-1].checksum if self.records
                            else GENESIS_PREV)
        record.checksum = _checksum(record.payload())
        return record

    def append(self, record: CvvRecord) -> CvvRecord:
        """Sella el récord (prev_hash + checksum) y lo añade."""
        sealed = self._seal(record)
        self.records.append(sealed)
        return sealed

    def verify(self) -> tuple[bool, int | None]:
        """Recalcula la cadena. Devuelve (ok, índice del primer roto)."""
        prev = GENESIS_PREV
        for i, rec in enumerate(self.records):
            if rec.prev_hash != prev:
                return False, i
            if rec.checksum != _checksum(rec.payload()):
                return False, i
            prev = rec.checksum
        return True, None

    def to_jsonl(self) -> str:
        return "".join(json.dumps(r.to_dict(), ensure_ascii=False) + "\n"
                       for r in self.records)

    @classmethod
    def from_jsonl(cls, text: str) -> "CvvChain":
        records = [CvvRecord.from_dict(json.loads(line))
                   for line in text.splitlines() if line.strip()]
        return cls(records)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.to_jsonl(), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "CvvChain":
        return cls.from_jsonl(Path(path).read_text(encoding="utf-8"))

    def __len__(self) -> int:
        return len(self.records)

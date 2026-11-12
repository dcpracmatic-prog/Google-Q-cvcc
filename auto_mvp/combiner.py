"""AUTO_MVP — la guía: el mejor por tarea, entre corridas (desde v1.0.0).

La idea de Arturo (2026-11-11): el auto-optimizador es una GUÍA,
no un compilador ni un validador. Su trabajo es juntar la base de
las tres tareas que sumen el puntaje pedido, y exportarla para
auditarla. Después, con esa base y ese mapa, se diseña el
submission real.

- Un ledger persistente (``best_per_task.json``): el mejor
  componente por tarea, guardado ENTRE corridas. La corrida 1 puede
  traer el mejor invsqrt, la corrida 2 el mejor DQI, la corrida 3
  la mejor química: la combinación toma el mejor de cada tarea,
  venga de la corrida que venga. Cada entrada guarda su procedencia
  (corrida, iteración, candidato, medido o proyectado), para que la
  auditoría sea transparente y legal: nada se mezcla sin decir de
  dónde salió.
- La combinación: dado un puntaje objetivo (meta_mvp, ej. 30.00),
  calcula la GM de los tres mejores y, si no llega, cuánto le falta
  a CADA tarea (el S que cada una necesitaría, con las otras dos
  fijas). Ese es el mapa: qué hay que mejorar y cuánto.
- La exportación: cuando la combinación alcanza el objetivo,
  exporta los tres componentes en un ZIP de auditoría (estructura
  + código ejecutable + manifiesto con procedencia), para que se
  puedan auditar antes de diseñar el submission real. El ZIP de
  auditoría NO es el submission.zip de la competencia (ese lo arma
  la puerta fail-closed con los .kmb y el .npz).

La estimación usa la referencia oficial de cómo se califica (las
fórmulas de costs.py, copiadas de los verificadores). No compila ni
valida: eso es la fase 3 y los verificadores oficiales.
"""
from __future__ import annotations

import json
import math
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .vqcc.contracts import BEST_SUBMISSION_S, REFERENCE_S

TASKS = ("invsqrt", "dqi", "dfthcsos")

# El mejor envío (ref 58076483): la base de partida, medida por el
# verificador oficial. Todo lo que lo mejore entra al ledger.
BEST_SUBMISSION_REF = "58076483"
BEST_SUBMISSION_NAMES = {
    "invsqrt": "invsqrt-propio-certificado",
    "dqi": "dqi-publico-hibrido",
    "dfthcsos": "quimica-publica",
}


def seed_entries() -> dict[str, dict[str, Any]]:
    """Las tres entradas de partida: el mejor envío, medido."""
    out = {}
    for task in TASKS:
        S = float(BEST_SUBMISSION_S[task])
        out[task] = {
            "task": task,
            "name": BEST_SUBMISSION_NAMES[task],
            "kind": "best_submission",
            "S": S,
            "ratio": REFERENCE_S[task] / S,
            "metrics": {"S": S},
            "artifact_name": None,
            "run_id": f"best-submission-{BEST_SUBMISSION_REF}",
            "iteration": None,
            "measured": True,
            "source_commit": None,
        }
    return out


def _gm_of_S(S: dict[str, float]) -> float:
    rs = [REFERENCE_S[t] / s for t, s in S.items()]
    return math.exp(sum(math.log(r) for r in rs) / len(rs))


@dataclass
class BestLedger:
    """El mejor componente por tarea, guardado entre corridas.

    ``path`` es el JSON persistente (runs/best_per_task.json). Si no
    existe, se siembra con el mejor envío (medido). ``record`` solo
    reemplaza si el S es menor (mejor): un S mayor no borra el
    mejor. Cada reemplazo queda registrado en ``history``.
    """

    path: str | Path
    entries: dict[str, dict[str, Any]] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        if self.path.is_file():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.entries = data.get("entries", {})
            self.history = data.get("history", [])
        if not self.entries:
            self.entries = seed_entries()
            self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"entries": self.entries, "history": self.history},
                       indent=2, ensure_ascii=False), encoding="utf-8")

    def record(self, task: str, entry: dict[str, Any]) -> dict[str, Any]:
        """Registra un componente; solo reemplaza si mejora el S.

        La entrada trae task, name, kind, S, ratio (o se calcula),
        metrics, artifact_name, run_id, iteration, measured y
        source_commit. Devuelve si mejoró y qué reemplazó.
        """
        if task not in TASKS:
            raise ValueError(f"tarea desconocida: {task!r}")
        S = float(entry["S"])
        if not (math.isfinite(S) and S > 0):
            raise ValueError(f"S debe ser finito y > 0, got {S}")
        new = dict(entry)
        new["task"] = task
        new.setdefault("ratio", REFERENCE_S[task] / S)
        new.setdefault("measured", False)
        current = self.entries.get(task)
        improved = current is None or S < float(current["S"])
        previous = dict(current) if current is not None else None
        if improved:
            self.entries[task] = new
            self.history.append({
                "task": task, "at": datetime.now(timezone.utc).isoformat(),
                "previous_S": (previous or {}).get("S"),
                "new_S": S, "name": new.get("name"),
                "run_id": new.get("run_id"),
                "iteration": new.get("iteration"),
                "measured": new.get("measured", False),
            })
            self.save()
        return {"improved": improved, "previous": previous, "entry": new}

    def best(self) -> dict[str, dict[str, Any]]:
        return {t: dict(self.entries[t]) for t in TASKS if t in self.entries}

    def combined_S(self) -> dict[str, float]:
        return {t: float(self.entries[t]["S"]) for t in TASKS
                if t in self.entries}

    def combined_gm(self) -> float | None:
        S = self.combined_S()
        if len(S) != len(TASKS):
            return None
        return _gm_of_S(S)

    def required_S(self, task: str, target_gm: float) -> float | None:
        """El S que esta tarea necesitaría para llegar al objetivo.

        Con las otras dos tareas fijas en su mejor S. None si falta
        alguna de las otras dos.
        """
        S = self.combined_S()
        others = {t: s for t, s in S.items() if t != task}
        if len(others) != len(TASKS) - 1:
            return None
        needed_product = float(target_gm) ** len(TASKS)
        for t, s in others.items():
            needed_product /= REFERENCE_S[t] / s
        return REFERENCE_S[task] / needed_product

    def gaps(self, target_gm: float) -> dict[str, dict[str, Any]]:
        """Por tarea: S actual, S necesario, y cuánto falta."""
        out = {}
        for task in TASKS:
            need = self.required_S(task, target_gm)
            cur = self.entries.get(task, {}).get("S")
            out[task] = {
                "current_S": cur,
                "required_S": need,
                "ratio_needed": (REFERENCE_S[task] / need) if need else None,
                "current_ratio": (REFERENCE_S[task] / cur) if cur else None,
            }
        return out


def combine(ledger: BestLedger, target_gm: float) -> dict[str, Any]:
    """La mejor combinación de las tres tareas, contra el objetivo.

    Junta el mejor de cada tarea (venga de la corrida que venga) y
    dice si la combinación llega al objetivo, y si no, cuánto le
    falta a cada tarea. Es una GUÍA: la GM es una estimación con la
    fórmula oficial, no un puntaje medido.
    """
    gm = ledger.combined_gm()
    components = ledger.best()
    projected = any(not c.get("measured", False) for c in components.values())
    return {
        "target": float(target_gm),
        "gm": gm,
        "reached": gm is not None and gm >= float(target_gm),
        "projected": projected,
        "components": components,
        "required": ledger.gaps(target_gm),
    }


def export_audit_zip(ledger: BestLedger, out_path: str | Path,
                     dataset_root: str | Path | None = None,
                     target_gm: float | None = None) -> dict[str, Any]:
    """Exporta los tres mejores componentes en un ZIP de auditoría.

    Por tarea: si el componente tiene artifact_name y está en el
    dataset, copia su structure.json, module.py y source/ (la
    estructura completa y el código ejecutable); si no, escribe un
    component.json con sus métricas y su procedencia. Siempre lleva
    un manifest.json con el objetivo, la GM (medida o proyectada),
    y la procedencia de cada componente (corrida, iteración,
    candidato, medido o proyectado). El ZIP es la BASE para auditar
    y diseñar el submission real, no el submission.zip de la
    competencia.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    combo = combine(ledger, target_gm if target_gm is not None
                    else (ledger.combined_gm() or 0.0))
    files: list[str] = []
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for task in TASKS:
            entry = ledger.entries.get(task)
            if entry is None:
                continue
            copied = False
            if dataset_root is not None and entry.get("artifact_name"):
                src = Path(dataset_root) / str(entry["artifact_name"])
                if src.is_dir():
                    for p in sorted(src.rglob("*")):
                        if p.is_file():
                            arc = f"{task}/{p.relative_to(src)}"
                            zf.write(p, arc)
                            files.append(arc)
                    copied = True
            if not copied:
                arc = f"{task}/component.json"
                zf.writestr(arc, json.dumps(entry, indent=2,
                                            ensure_ascii=False))
                files.append(arc)
        manifest = {
            "target": combo["target"],
            "gm": combo["gm"],
            "reached": combo["reached"],
            "projected": combo["projected"],
            "components": {t: {
                "name": e.get("name"), "kind": e.get("kind"),
                "S": e.get("S"), "ratio": e.get("ratio"),
                "measured": e.get("measured", False),
                "run_id": e.get("run_id"),
                "iteration": e.get("iteration"),
                "artifact_name": e.get("artifact_name"),
                "source_commit": e.get("source_commit"),
            } for t, e in combo["components"].items()},
            "required": combo["required"],
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2,
                                                ensure_ascii=False))
        files.append("manifest.json")
    return {"path": str(out_path), "files": files, "gm": combo["gm"],
            "reached": combo["reached"], "projected": combo["projected"],
            "target": combo["target"]}

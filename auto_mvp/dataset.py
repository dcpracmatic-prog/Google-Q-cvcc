"""AUTO_MVP v0.8.0 — dataset de trabajo: exportar e inyectar módulos.

El diseño fail-closed está perfecto para el submission.zip FINAL
(solo los tres verificadores en modo full lo arman, para no subir
basura al ranking de Kaggle). Pero los candidatos que el sistema
criba y promueve NO deben quedarse atrapados en métricas frías o
resúmenes vacíos (un manifest.json con S y GM): cada módulo
promovido exporta e inyecta su ESTRUCTURA COMPLETA y su CÓDIGO
EJECUTABLE al dataset de trabajo, para que realmente se pueda
evaluar y compilar.

El dataset de trabajo vive en ``<runs_dir>/dataset/`` (nunca en
/kaggle/input, que es INTOCABLE): cada módulo tiene su carpeta
``dataset/<nombre>/`` con:
- ``structure.json``: el grafo de llamadas completo (Qualtran),
  las métricas, la evidencia de integridad y el S/GM registrados.
- ``module.py``: el código ejecutable del módulo (solo stdlib):
  rebuild la estructura, recomputa S y GM con las fórmulas
  oficiales y los compara con los registrados. ``python module.py``
  lo verifica.
- ``source/...``: el código del constructor del módulo, cuando el
  candidato lo trae (se exporta tal cual, sin tocarlo).
- ``manifest.json``: el manifiesto del artefacto (el de siempre).

Y el índice ``dataset/index.json`` lista todos los módulos
inyectados (nombre, kind, tarea, S, GM, rutas). El cargador
(``WorkingDataset``) lee el índice y carga un módulo por nombre:
su grafo, sus métricas y la ruta de su código ejecutable. Así la
fase 3 (compilación) consume el dataset, no un manifiesto pelado.

Límites (dichos con el dato): la compilación a .kmb (kickmix) es
la fase 3 (``compile_fn``) y NO es parte de esta exportación: el
dataset da la estructura y el código que la compilación necesita,
pero el .kmb lo construye el compile_fn. Un módulo sin grafo de
llamadas se exporta con sus métricas y su module.py (que verifica
S/GM desde las métricas), y lo dice en el export.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .qualtran_bridge import CallGraph

INDEX_NAME = "index.json"


def _structure(record: dict[str, Any]) -> dict[str, Any]:
    """La estructura completa del módulo promovido (no un resumen)."""
    return {
        "name": record.get("artifact_name", ""),
        "kind": record.get("kind", "candidate"),
        "task": record.get("task", ""),
        "iteration": record.get("iteration"),
        "gm": record.get("gm"),
        "S": record.get("S", {}),
        "ratios": record.get("ratios", {}),
        "metrics": record.get("metrics", {}),
        "call_graph": record.get("call_graph"),
        "integrity": record.get("integrity"),
        "source_commit": record.get("source_commit", ""),
        "source_files": sorted((record.get("source") or {}).keys()),
    }


MODULE_TEMPLATE = '''"""Módulo exportado: __NAME__ (__KIND__, __TASK__).
Generado por AUTO_MVP v0.8.0 desde el dataset de trabajo.
Ejecutable (solo stdlib):  python module.py
Verifica la estructura completa y recomputa S y GM con las fórmulas
oficiales de la competencia. No es un resumen: es el módulo.
"""
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAME = "__NAME__"
TASK = "__TASK__"

# Referencias oficiales (las de la competencia y las del mejor envío).
REFERENCE_S = {"invsqrt": 2076774.0, "dqi": 2.44e13, "dfthcsos": 3355599588.32}
BEST_SUBMISSION_S = {"invsqrt": 100568.5, "dqi": 3.7676e11, "dfthcsos": 326800029.87}


def load_structure():
    with open(HERE / "structure.json", encoding="utf-8") as f:
        return json.load(f)


def repetition_overhead(eps):
    if not 0.0 <= eps < 1 / 16:
        raise ValueError(f"eps debe estar en [0, 1/16), got {eps}")
    if eps == 0.0:
        return 1.0
    return math.log(2.0) / -math.log(0.5 + 2.0 * math.sqrt(eps))


def compute_S(task, metrics):
    if task == "dqi":
        return repetition_overhead(metrics["eps_plus"]) * metrics["Q"] ** 2 * metrics["T"]
    if task == "invsqrt":
        # v0.9.1: T incluye la síntesis de rotaciones (la fórmula del
        # verificador oficial). El margen es la cota inferior que
        # deja el rel_error: (2^-24 - rel_error) / sqrt(x_max).
        t_total = metrics.get("t_count", 0)
        n_rot = metrics.get("rotations", 0)
        if n_rot:
            rel_error = metrics.get("rel_error")
            if rel_error is None:
                raise ValueError("rotations > 0 sin rel_error")
            margin = (2.0 ** -24 - rel_error) / 3133452.0 ** 0.5
            if not margin > 0:
                raise ValueError("sin tolerancia para la síntesis de rotaciones")
            eps = 3.141592653589793 * margin / n_rot
            t_total += n_rot * (0.56 * math.log2(1.0 / eps) + 5.3)
        return metrics["Q"] * (metrics.get("toffoli", 0) + t_total / 4.0)
    if task == "dfthcsos":
        return metrics["lambda_eff"] * metrics["Ttot"] * metrics["Qtot"]
    raise ValueError(f"tarea desconocida: {task!r}")


def compute_gm(task, S):
    scores = dict(BEST_SUBMISSION_S)
    scores[task] = S
    ratios = [REFERENCE_S[t] / scores[t] for t in ("invsqrt", "dqi", "dfthcsos")]
    return math.exp(sum(math.log(r) for r in ratios) / len(ratios))


def build():
    """Reconstruye el grafo de llamadas y las métricas del módulo."""
    st = load_structure()
    return st.get("call_graph"), st["metrics"]


def verify():
    """Recomputa S y GM desde la estructura y los compara con los registrados."""
    st = load_structure()
    task = st["task"]
    metrics = st["metrics"]
    S = compute_S(task, metrics)
    gm = compute_gm(task, S)
    recorded_S = st.get("S") or {}
    recorded_gm = st.get("gm")
    ok = True
    reasons = []
    s0 = recorded_S.get(task)
    if s0 is None or abs(S - s0) / max(abs(s0), 1e-12) > 1e-6:
        ok = False
        reasons.append(f"S recomputado {S:.6g} != registrado {s0}")
    if recorded_gm is not None and abs(gm - recorded_gm) / max(abs(recorded_gm), 1e-12) > 1e-6:
        ok = False
        reasons.append(f"GM recomputada {gm:.6g} != registrada {recorded_gm}")
    graph, _ = build()
    return {"name": NAME, "task": task, "S": S, "gm": gm,
            "has_call_graph": graph is not None, "ok": ok, "reasons": reasons}


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2, ensure_ascii=False))
'''


def render_module(name: str, kind: str, task: str) -> str:
    """El código ejecutable del módulo (solo stdlib)."""
    return (MODULE_TEMPLATE
            .replace("__NAME__", name)
            .replace("__KIND__", kind)
            .replace("__TASK__", task))


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def export_candidate(record: dict[str, Any], artifact_dir: str | Path,
                     dataset_root: str | Path) -> dict[str, Any]:
    """Exporta e inyecta un módulo promovido.

    Escribe structure.json, module.py y source/... en el directorio
    del artefacto Y en ``dataset_root/<nombre>/``, y actualiza
    ``dataset_root/index.json``. Devuelve las rutas y qué trae.
    """
    artifact_dir = Path(artifact_dir)
    dataset_root = Path(dataset_root)
    name = record.get("artifact_name") or artifact_dir.name
    record = dict(record)
    record["artifact_name"] = name
    structure = _structure(record)
    module_src = render_module(name, structure["kind"], structure["task"])
    files: list[str] = []
    for dest in (artifact_dir, dataset_root / name):
        dest.mkdir(parents=True, exist_ok=True)
        _write_json(dest / "structure.json", structure)
        (dest / "module.py").write_text(module_src, encoding="utf-8")
        files.append(str(dest / "structure.json"))
        files.append(str(dest / "module.py"))
        source = record.get("source") or {}
        for fname, code in sorted(source.items()):
            # El código del constructor, tal cual (sin tocarlo).
            target = dest / "source" / fname
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(code, encoding="utf-8")
            files.append(str(target))
        # El manifiesto del artefacto también vive en el dataset.
        manifest = artifact_dir / "manifest.json"
        if manifest.is_file() and dest != artifact_dir:
            shutil.copyfile(manifest, dest / "manifest.json")
            files.append(str(dest / "manifest.json"))
    entry = {"name": name, "kind": structure["kind"],
             "task": structure["task"], "iteration": structure["iteration"],
             "gm": structure["gm"], "S": structure["S"],
             "has_call_graph": structure["call_graph"] is not None,
             "has_source": bool(structure["source_files"]),
             "dataset_dir": str(dataset_root / name)}
    WorkingDataset(dataset_root).add(entry)
    return {"name": name, "artifact_dir": str(artifact_dir),
            "dataset_dir": str(dataset_root / name), "files": files,
            "has_call_graph": entry["has_call_graph"],
            "has_source": entry["has_source"]}


class WorkingDataset:
    """El dataset de trabajo: módulos promovidos, inyectados y cargables."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def index_path(self) -> Path:
        return self.root / INDEX_NAME

    def index(self) -> list[dict[str, Any]]:
        if not self.index_path.is_file():
            return []
        return json.loads(self.index_path.read_text(encoding="utf-8"))

    def add(self, entry: dict[str, Any]) -> None:
        entries = [e for e in self.index() if e.get("name") != entry["name"]]
        entries.append(dict(entry))
        _write_json(self.index_path, entries)

    def names(self) -> list[str]:
        return [e["name"] for e in self.index()]

    def load(self, name: str) -> dict[str, Any]:
        """Carga un módulo por nombre: su grafo, sus métricas y su código.

        Devuelve el grafo de llamadas (CallGraph o None), las
        métricas, el S/GM y la ruta del module.py ejecutable.
        """
        matches = [e for e in self.index() if e["name"] == name]
        if not matches:
            raise KeyError(f"módulo no inyectado en el dataset: {name!r}")
        mod_dir = self.root / name
        structure = json.loads((mod_dir / "structure.json").read_text(
            encoding="utf-8"))
        graph = None
        if structure.get("call_graph") is not None:
            graph = CallGraph.from_dict(structure["call_graph"])
        return {"name": name, "kind": structure["kind"],
                "task": structure["task"], "metrics": structure["metrics"],
                "S": structure["S"], "gm": structure["gm"],
                "call_graph": graph,
                "total_T": graph.total_T() if graph is not None else None,
                "total_Q": graph.total_Q() if graph is not None else None,
                "module_path": str(mod_dir / "module.py"),
                "structure_path": str(mod_dir / "structure.json")}

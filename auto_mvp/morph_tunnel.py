"""AUTO_MVP — tunelamiento morfológico (MORPH) sobre Qualtran (desde v0.6.0).

El motor morfogenético de la especificación AUTO_MVP v0.0.1 (fase 3)
tenía un problema real: no tenía fórmula ni algoritmo definidos. La
corrección de Arturo (2026-11-11) es que la formalización SÍ existe:
es Qualtran — su representación de circuitos (Bloqs, grafo de
llamadas) y su modelo de costo (T y Q como cantidades de primera
clase). Este módulo es ese motor, sobre esa formalización:

- Opera sobre el grafo de llamadas de Qualtran (``qualtran_bridge``):
  reemplaza BLOQUES, no solo pruebas paramétricas fijas. Un "túnel"
  es un salto en el paisaje de costo: reemplazar un bloque por otro
  equivalente para cruzar una barrera que la búsqueda paramétrica no
  cruza (ej. reemplazar la búsqueda de Chien por inversión por lotes
  Montgomery: el circuito salta de T=1,511,522 a T=1,315,731).
  El motor NO reordena bloques: no verifica conmutación en ningún
  sitio, así que un reordenamiento nunca se propone ni se aplica.
- Cada regla de reemplazo trae su EVIDENCIA medida (cost_model
  exacto o verificador oficial) y su delta de costo MEDIDO. Una
  regla sin evidencia no se aplica: el motor nunca tunela con un
  costo inventado.
- La equivalencia funcional de un reemplazo NO la demuestra
  Qualtran (no demuestra que dos Bloqs sean iguales) ni este motor:
  viene de la verificación medida que nombra la evidencia. Si una
  regla no tiene verificación medida, el motor la rechaza y lo dice.

Reglas reales del registro (medidas, no proyectadas):
- "chien-montgomery-b17": Chien -> Montgomery b=17 (bloque).
  T 1,511,522 -> 1,315,731, Q igual (1,414). Evidencia: cost_model
  exacto, registrado en tests/test_auto_mvp_v060.py
  (test_tunnel_montgomery_measured): S=3.2331e12, medido. El
  archivo montgomery-v4 INFORME_V4.md NO existe en el repo y no
  se cita.
- "multiplier-toom4": multiplicador Toom-3 -> Toom-4 (circuito).
  S 1.99836e13 -> 1.923348e13 (Q=1,899, R=1.22901). Evidencia:
  dqi_cost.estimate_variant(42, v1=True, e2=True) en
  auto_mvp/circuits/cost_models/dqi_cost.py: Q=1,899, T=4,477,394,
  S=1.923348e13 (kernel 144398281 de Kaggle, medido en el
  verificador oficial). El delta en T se deriva de los S medidos,
  con la fórmula escrita.
- Cada regla cita su artefacto en ``evidence_artifact`` (ruta
  relativa a la raíz del repo): el constructor comprueba que el
  archivo exista y falla si no existe. Una cita a un archivo que
  no está en el repo es un error, no una evidencia.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .qualtran_bridge import Block, CallGraph

# S = R * Q^2 * T (DQI). Con Q y R fijos, el delta en T sale de los S.
DQI_R = 1.22901


def _repo_root() -> Path:
    """La raíz del repo (el directorio con pyproject.toml).

    Se busca hacia arriba desde este archivo: así funciona tanto
    desde el repo como desde una copia vendida (build/lib).
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path(__file__).resolve().parents[1]


@dataclass
class ReplacementRule:
    """Una regla de reemplazo (un túnel) con su evidencia medida.

    target: nombre o kind del bloque a reemplazar.
    replacement: nombre del bloque que lo sustituye.
    delta_T / delta_Q: cambio MEDIDO en el costo total del circuito
        (negativo = mejora). Si no se pasan, se derivan de
        s_before/s_after (con q y r).
    s_before / s_after: S medidos antes y después (para derivar
        delta_T con Q y R fijos).
    q / r: Q y R del circuito (para derivar delta_T).
    scope: "block" (el reemplazo es un bloque dentro del circuito)
        o "circuit" (se reemplaza un subsistema entero).
    evidence: la verificación medida que respalda la equivalencia
        (obligatoria: una regla sin evidencia no se aplica).
    evidence_artifact: ruta relativa a la raíz del repo del
        artefacto que registra la medición citada en ``evidence``
        (módulo, nota o test). Si se cita, el archivo tiene que
        existir: el constructor falla si no existe. Vacío = la
        regla no cita artefacto (solo vale para reglas sintéticas
        de test; las reglas del registro RULES siempre citan uno).
    requires_order: (a, b) — la regla solo aplica si el bloque a
        precede al bloque b en los hijos del padre (precondición de
        orden; si no se cumple, la regla no aplica: el motor NO
        reordena, porque no verifica conmutación).
    """
    name: str
    target: str
    replacement: str
    delta_T: float | None = None
    delta_Q: float = 0.0
    s_before: float | None = None
    s_after: float | None = None
    q: float | None = None
    r: float = DQI_R
    scope: str = "block"
    evidence: str = ""
    evidence_artifact: str = ""
    requires_order: tuple[str, str] | None = None

    def __post_init__(self):
        if not self.evidence:
            raise ValueError(f"la regla {self.name!r} no tiene evidencia medida")
        if self.evidence_artifact:
            path = _repo_root() / self.evidence_artifact
            if not path.is_file():
                raise ValueError(
                    f"la regla {self.name!r} cita el artefacto "
                    f"{self.evidence_artifact!r}, que no existe en el repo "
                    f"(se buscó en {path}); cita un artefacto real o quita "
                    f"la cita")
        if self.delta_T is None:
            if None in (self.s_before, self.s_after, self.q):
                raise ValueError(
                    f"la regla {self.name!r} no tiene delta_T ni S medidos")
            self.delta_T = (self.s_after - self.s_before) / (
                self.r * float(self.q) ** 2)

    def applies_to(self, graph: CallGraph) -> bool:
        """El bloque objetivo existe y la precondición de orden se cumple."""
        if graph.find(self.target) is None:
            return False
        if self.requires_order is None:
            return True
        a, b = self.requires_order
        parent = _parent_of(graph.root, a) or _parent_of(graph.root, b)
        if parent is None:
            return False
        names = [c.name for c, _ in parent.children]
        kinds = [c.kind for c, _ in parent.children]
        seq = names + kinds
        return a in seq and b in seq and seq.index(a) < seq.index(b)


def _parent_of(block: Block, name: str) -> Block | None:
    for child, _ in block.children:
        if child.name == name or child.kind == name:
            return block
        found = _parent_of(child, name)
        if found is not None:
            return found
    return None


def _replace_block(block: Block, target: str, replacement: Block) -> bool:
    """Reemplaza el primer bloque llamado ``target`` (recursivo)."""
    for i, (child, count) in enumerate(block.children):
        if child.name == target or child.kind == target:
            block.children[i] = (replacement, count)
            return True
        if _replace_block(child, target, replacement):
            return True
    return False


@dataclass
class TunnelMove:
    rule: str
    target: str
    replacement: str
    old_T: float | None
    new_T: float | None
    kind: str = "replace"  # solo "replace": el motor ya no reordena
    evidence: str = ""


@dataclass
class TunnelResult:
    graph: CallGraph
    moves: list[TunnelMove] = field(default_factory=list)
    baseline_T: float | None = None
    final_T: float | None = None
    baseline_Q: int | None = None
    final_Q: int | None = None
    stopped: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "baseline_T": self.baseline_T, "final_T": self.final_T,
            "baseline_Q": self.baseline_Q, "final_Q": self.final_Q,
            "moves": [m.__dict__ for m in self.moves],
            "stopped": self.stopped,
        }


def _apply_rule(graph: CallGraph, rule: ReplacementRule) -> CallGraph | None:
    """Aplica una regla: reemplaza el bloque y actualiza el costo medido.

    El T total ANTES de reemplazar se mide del grafo original; el
    T después es ese total + el delta MEDIDO de la regla (a nivel de
    circuito). El bloque de reemplazo no trae T propio medido: el T
    de la raíz (el total medido) es la autoridad, no la suma de
    hijos con un T desconocido.
    """
    old_T = graph.total_T()
    if old_T is None or rule.delta_T is None:
        return None
    target = graph.find(rule.target)
    if target is None:
        return None
    new = copy.deepcopy(graph)
    replacement = Block(name=rule.replacement, kind=rule.replacement,
                        t_count=None, qubits=target.qubits)
    if not _replace_block(new.root, rule.target, replacement):
        return None
    new.root.t_count = old_T + rule.delta_T
    if rule.delta_Q:
        new.root.qubits = (new.root.qubits or 0) + int(rule.delta_Q)
    return new


def tunnel(graph: CallGraph, rules: list[ReplacementRule],
           max_moves: int = 10, method: str = "greedy",
           verify: Callable[[CallGraph], bool] | None = None) -> TunnelResult:
    """Tunela por el paisaje de costo: reemplaza bloques.

    method "greedy": en cada paso aplica la regla que más baja T.
    method "beam": explora varias secuencias (ancho 3) y se queda
    con la mejor. Una regla con precondición de orden
    (``requires_order``) que no se cumple simplemente no aplica:
    el motor NO reordena bloques para desbloquearla, porque no
    verifica conmutación en ningún sitio.
    ``verify`` es el gancho de integridad (ej. el filtro de
    integridad): se llama con cada grafo candidato tunelado; si
    devuelve False, ese candidato se descarta y no se aplica, y la
    búsqueda sigue con las demás reglas (no se aborta). Si es None,
    no se filtra nada.
    """
    baseline_T = graph.total_T()
    baseline_Q = graph.total_Q()
    if method == "beam":
        return _tunnel_beam(graph, rules, max_moves, verify,
                            baseline_T, baseline_Q)
    current = copy.deepcopy(graph)
    moves: list[TunnelMove] = []
    stopped = "sin reglas que mejoren"
    for _ in range(max_moves):
        best: tuple[ReplacementRule, CallGraph, float] | None = None
        for rule in rules:
            if not rule.applies_to(current):
                continue
            cand = _apply_rule(current, rule)
            if cand is None:
                continue
            new_T = cand.total_T()
            old_T = current.total_T()
            if new_T is None or old_T is None or new_T >= old_T:
                continue
            if verify is not None and not verify(cand):
                continue
            if best is None or new_T < best[2]:
                best = (rule, cand, new_T)
        if best is not None:
            rule, new_graph, new_T = best
            old_T = current.total_T()
            current = new_graph
            moves.append(TunnelMove(rule=rule.name, target=rule.target,
                                    replacement=rule.replacement,
                                    old_T=old_T, new_T=new_T,
                                    evidence=rule.evidence))
            continue
        # Ninguna regla aplica o mejora: se para. No se reordena
        # para desbloquear reglas con precondición de orden: el
        # motor no verifica conmutación (H9: la rama de desbloqueo
        # por reorder se eliminó; era código muerto que afirmaba
        # conmutación sin comprobarla).
        break
    else:
        stopped = "límite de movimientos"
    return TunnelResult(graph=current, moves=moves, baseline_T=baseline_T,
                        final_T=current.total_T(), baseline_Q=baseline_Q,
                        final_Q=current.total_Q(), stopped=stopped)


def _tunnel_beam(graph: CallGraph, rules: list[ReplacementRule],
                 max_moves: int, verify: Callable[[CallGraph], bool] | None,
                 baseline_T: float | None, baseline_Q: int | None) -> TunnelResult:
    """Búsqueda por haz (ancho 3) sobre secuencias de reglas."""
    beam: list[tuple[CallGraph, list[TunnelMove]]] = [(copy.deepcopy(graph), [])]
    best_state = (copy.deepcopy(graph), [])
    for _ in range(max_moves):
        candidates: list[tuple[float, CallGraph, list[TunnelMove]]] = []
        for g, mv in beam:
            for rule in rules:
                if not rule.applies_to(g):
                    continue
                cand = _apply_rule(g, rule)
                if cand is None:
                    continue
                new_T = cand.total_T()
                old_T = g.total_T()
                if new_T is None or old_T is None or new_T >= old_T:
                    continue
                if verify is not None and not verify(cand):
                    continue
                candidates.append((new_T, cand, mv + [TunnelMove(
                    rule=rule.name, target=rule.target,
                    replacement=rule.replacement, old_T=old_T, new_T=new_T,
                    evidence=rule.evidence)]))
        if not candidates:
            break
        candidates.sort(key=lambda c: c[0])
        beam = [(c[1], c[2]) for c in candidates[:3]]
        if beam[0][0].total_T() is not None and (
                best_state[0].total_T() is None
                or beam[0][0].total_T() < best_state[0].total_T()):
            best_state = beam[0]
    g, mv = best_state
    return TunnelResult(graph=g, moves=mv, baseline_T=baseline_T,
                        final_T=g.total_T(), baseline_Q=baseline_Q,
                        final_Q=g.total_Q(),
                        stopped="haz agotado" if not mv else "mejor haz")


# --- Registro de reglas reales (medidas) ---
RULES: list[ReplacementRule] = [
    ReplacementRule(
        name="chien-montgomery-b17", target="chien",
        replacement="montgomery-b17", delta_T=-195_791.0, delta_Q=0.0,
        scope="block",
        evidence=("cost_model exacto, registrado en "
                  "tests/test_auto_mvp_v060.py "
                  "(test_tunnel_montgomery_measured): Q=1,414, "
                  "T=1,511,522 -> 1,315,731, S=3.2331e12, medido"),
        evidence_artifact="tests/test_auto_mvp_v060.py"),
    # Medido en el ensamble Toom-3+V1+E2 (Q=1,899), no en la semilla
    # BM+Forney (Q=1,414): el delta es el del ensamble. La regla
    # aplica a grafos con bloque "multiplier"; quien la aplique a
    # otro circuito mezcla deltas de circuitos distintos.
    ReplacementRule(
        name="multiplier-toom4", target="multiplier",
        replacement="toom4", s_before=1.99836e13, s_after=1.923348e13,
        q=1899.0, r=DQI_R, scope="circuit",
        evidence=("dqi_cost.estimate_variant(42, v1=True, e2=True) en "
                  "auto_mvp/circuits/cost_models/dqi_cost.py: Q=1,899, "
                  "T=4,477,394, S=1.923348e13 (kernel 144398281 de "
                  "Kaggle, medido en el verificador oficial)"),
        evidence_artifact="auto_mvp/circuits/cost_models/dqi_cost.py"),
]

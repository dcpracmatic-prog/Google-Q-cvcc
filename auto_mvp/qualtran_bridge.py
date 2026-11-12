"""AUTO_MVP — puente Qualtran: la formalización algorítmica (desde v0.6.0).

La formalización algorítmica del sistema NO se inventa desde cero:
es Qualtran (su representación de circuitos y su modelo de costo).
Este módulo es el puente:

- ``Block`` / ``CallGraph``: la representación formal de un circuito
  como grafo de llamadas de bloques (Bloqs). Cada bloque tiene su
  costo T y sus cúbits como cantidades de PRIMERA CLASE: el T total
  de un bloque compuesto es la suma de los T de sus llamados (la
  misma semántica de ``Bloq.t_complexity()`` y ``Bloq.call_graph()``
  de Qualtran); los cúbits son los del bloque raíz (su firma), no
  la suma de los hijos.
- ``from_qualtran_bloq``: extrae el grafo de llamadas de un Bloq
  REAL de Qualtran (verificado contra la librería 0.8.0.dev0: Toffoli
  T=4, Add(QUInt(4)) T=12 con And 3 + And_adj 3 y CNOT 15). El repo es solo
  stdlib, así que Qualtran se importa solo aquí, bajo demanda: sin
  Qualtran instalado, el puente trabaja con grafos construidos a
  mano (los del cost_model) y ``from_qualtran_bloq`` dice que falta
  la librería, no inventa el grafo.

Límites que Qualtran NO cubre (dicho con el dato, no recortado):
- Qualtran NO demuestra que dos Bloqs sean funcionalmente iguales.
  La equivalencia de un reemplazo (tunelamiento) viene de la
  verificación MEDIDA (cost_model exacto, verificador oficial),
  nunca de Qualtran.
- El circuito DQI de la competencia es un circuito kickmix, no un
  Bloq de Qualtran. El puente opera sobre Bloqs de Qualtran y sobre
  grafos de llamadas construidos desde el cost_model; convertir el
  DQI kickmix completo a un Bloq es una tarea aparte, no hecha aquí.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

QUALTRAN_VERSION = "0.8.0.dev0"  # la versión verificada en el venv


@dataclass
class Block:
    """Un bloque del grafo de llamadas (un Bloq de Qualtran).

    name: nombre del bloque (str(bloq) en Qualtran).
    kind: clase del bloque (ej. "Toffoli", "Add", "chien", "bm_forward").
    t_count: Toffolis del bloque. None = no medido (el motor no lo
        suma: un costo desconocido nunca se inventa).
    qubits: cúbits del bloque (su firma). None = no medido.
    children: (bloque hijo, veces que se llama) — el grafo de
        llamadas. Un bloque compuesto tiene hijos; una hoja no.
    rotations / cliffords: el resto de TComplexity de Qualtran.
    """
    name: str
    kind: str = ""
    t_count: int | float | None = None
    qubits: int | None = None
    children: list[tuple["Block", int]] = field(default_factory=list)
    rotations: int = 0
    cliffords: int = 0

    @property
    def is_leaf(self) -> bool:
        return not self.children

    def total_T(self) -> float | None:
        """T total del bloque (suma de los llamados, como Qualtran).

        El T propio del bloque (el de t_complexity / cost_model,
        medido) ES el total: en Qualtran es la suma de los llamados,
        así que ambas vías coinciden. Si el bloque no trae T propio
        medido, se suma el T de sus hijos por su multiplicidad. Si
        nada está medido, el total es None: un costo desconocido
        nunca se inventa.
        """
        if self.t_count is not None:
            return float(self.t_count)
        if not self.children:
            return None
        total = 0.0
        for child, count in self.children:
            ct = child.total_T()
            if ct is None:
                return None
            total += ct * count
        return total

    def find(self, name: str) -> "Block | None":
        """Busca un bloque por nombre en el subgrafo."""
        if self.name == name or self.kind == name:
            return self
        for child, _ in self.children:
            found = child.find(name)
            if found is not None:
                return found
        return None

    def flatten(self) -> list[tuple["Block", int]]:
        """(bloque, multiplicidad total) de todo el subgrafo."""
        out: list[tuple[Block, int]] = [(self, 1)]
        for child, count in self.children:
            for sub, mult in child.flatten():
                out.append((sub, mult * count))
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "kind": self.kind,
            "t_count": self.t_count, "qubits": self.qubits,
            "rotations": self.rotations, "cliffords": self.cliffords,
            "children": [[c.to_dict(), n] for c, n in self.children],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Block":
        return cls(
            name=d["name"], kind=d.get("kind", ""),
            t_count=d.get("t_count"), qubits=d.get("qubits"),
            rotations=d.get("rotations", 0), cliffords=d.get("cliffords", 0),
            children=[(cls.from_dict(c), int(n))
                      for c, n in d.get("children", [])])


@dataclass
class CallGraph:
    """El grafo de llamadas de un circuito (raíz + costos)."""
    root: Block
    source: str = ""  # "qualtran" | "cost_model" | "json" | "manual"

    def total_T(self) -> float | None:
        return self.root.total_T()

    def total_Q(self) -> int | None:
        return self.root.qubits

    def cost(self) -> dict[str, Any]:
        """T y Q como cantidades de primera clase."""
        return {"T": self.total_T(), "Q": self.total_Q()}

    def find(self, name: str) -> Block | None:
        return self.root.find(name)

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "root": self.root.to_dict()}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CallGraph":
        return cls(root=Block.from_dict(d["root"]),
                   source=d.get("source", ""))


def _bloq_qubits(bloq) -> int | None:
    """Cúbits de la firma de un Bloq (suma de bitsize × shape).

    Un registro tiene bitsize (bits por elemento) y shape (cuántos
    elementos): un Toffoli tiene ctrl bitsize 1 shape (2,) + target
    bitsize 1 = 3 cúbits. None si un bitsize es simbólico.
    """
    try:
        total = 0
        for reg in bloq.signature:
            bits = reg.bitsize
            if not isinstance(bits, int):
                return None
            shape = getattr(reg, "shape", ())
            n = 1
            for d in shape:
                n *= int(d)
            total += bits * n
        return total
    except Exception:
        return None


def from_qualtran_bloq(bloq, depth: int = 10, _seen: frozenset | None = None) -> CallGraph:
    """Extrae el grafo de llamadas de un Bloq REAL de Qualtran.

    Usa ``bloq.call_graph()`` (que en 0.8.0.dev0 devuelve
    ``(DiGraph, {bloq: count})``) y ``bloq.t_complexity()``. La
    recursión baja por los llamados directos, sin el propio bloque
    (una hoja es un bloque cuyo único llamado es él mismo). Con un
    ciclo en el grafo o sin Qualtran, se para con el dato, no con
    un grafo inventado.
    """
    try:
        import qualtran  # noqa: F401
    except ImportError as e:
        raise ImportError(
            "Qualtran no está instalado en este entorno; el puente "
            "necesita qualtran para extraer un Bloq real") from e
    seen = set() if _seen is None else set(_seen)
    key = repr(bloq)
    if depth <= 0 or key in seen:
        return CallGraph(root=_leaf(bloq), source="qualtran")
    seen.add(key)
    graph, counts = bloq.call_graph()
    children: list[tuple[Block, int]] = []
    for callee, count in counts.items():
        if repr(callee) == key:
            continue  # el propio bloque: es una hoja, no un hijo
        sub = from_qualtran_bloq(callee, depth=depth - 1, _seen=frozenset(seen))
        children.append((sub.root, int(count)))
    tc = bloq.t_complexity()
    root = Block(
        name=str(bloq), kind=type(bloq).__name__,
        t_count=int(tc.t),
        qubits=_bloq_qubits(bloq),
        children=children,
        rotations=int(tc.rotations), cliffords=int(tc.clifford))
    return CallGraph(root=root, source="qualtran")


def _leaf(bloq) -> Block:
    """Un Bloq como hoja (sin bajar más: ciclo o profundidad agotada)."""
    try:
        tc = bloq.t_complexity()
        t, rot, clif = int(tc.t), int(tc.rotations), int(tc.clifford)
    except Exception:
        t, rot, clif = None, 0, 0
    return Block(name=str(bloq), kind=type(bloq).__name__, t_count=t,
                 qubits=_bloq_qubits(bloq), rotations=rot, cliffords=clif)

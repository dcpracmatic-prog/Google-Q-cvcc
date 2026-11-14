"""AUTO_MVP v2.10 — el PEEPHOLE CON CONMUTACIÓN: cancelar pares
que no son adyacentes.

El peephole de v2.7 (con pila) solo cancela compuertas idénticas
ADYACENTES: si entre dos X sobre el mismo qubit hay una CX sobre
otros qubits, no se ven. Pero esa CX no toca el qubit de las X, así
que CONMUTA con ellas: las dos X son efectivamente adyacentes y se
pueden cancelar. Este operador busca esos pares: una compuerta
autoinversa que ya está en la pila, separada de la nueva por
compuertas que actúan sobre qubits DISJUNTOS (y por tanto conmutan
con ella).

Reglas (todas exactas, todas locales):
- Solo se cancelan pares idénticos de compuertas autoinversas
  (X, Z, H, CX, SWAP, CCX, CSWAP), como en el peephole.
- Entre las dos, TODAS las compuertas tienen que actuar sobre
  qubits disjuntos de los de la compuerta (si una toca sus qubits,
  no conmuta y el par no se cancela). Es la regla conservadora:
  solo la disyunción, sin casos especiales de conmutación.
- La búsqueda hacia atrás está acotada (MAX_GAP compuertas, 256
  por defecto en v2.11: en la semilla el resultado satura ahí): un
  par más separado no se busca (el resultado sigue siendo válido,
  solo se pierde una cancelación lejana).
- La Z_POW no entra aquí (la fusión es del peephole, que ya la hace
  en adyacencia); este operador solo cancela pares autoinversos.
- PUSH/POP y las líneas no-compuerta vacían la pila, como en el
  peephole: nada se cancela a través de ellas.

Eficacia: un índice (opcode, operandos) -> compuertas en la pila
hace que buscar el par sea O(1) (la comprobación de disyunción
solo corre cuando hay un candidato y está acotada a MAX_GAP). Así
el operador es lineal en el tamaño del circuito (como el peephole)
y se puede correr en el DQI sin OOM ni horas.
"""
from __future__ import annotations

from pathlib import Path

from .peephole import SELF_INVERSE, _split

# Máxima distancia (en compuertas) entre las dos del par.
# v2.11: era 16; en la semilla el resultado satura en 256 (42 con
# 16, 48 con 32, 58 con 64, 70 con 128, 76 con 256 y lo mismo con
# 512/1024/4096). 256 es el punto donde ya no aparece nada más.
MAX_GAP = 256


def _qubits_of(op: str, args: list[str]) -> frozenset:
    """Los qubits que toca una compuerta (por su opcode)."""
    if op in ("CCX", "CCZ", "CSWAP", "CCZ_IF"):
        return frozenset(args[:3])
    if op in ("CX", "CZ"):
        return frozenset(args[:2])
    if op in ("X", "Z", "H", "SWAP", "Z_POW"):
        return frozenset(args[:1])
    return frozenset(a for a in args if a.startswith("q"))


def _commuting_pass(lines, out, max_pending: int = 4096,
                    max_gap: int = MAX_GAP) -> dict:
    """Una pasada con conmutación sobre las líneas, con pila.

    Como _peephole_pass, pero al llegar una compuerta autoinversa
    se busca hacia atrás (hasta max_gap compuertas) un par idéntico
    separado solo por compuertas en qubits disjuntos. Si se
    encuentra, las dos se cancelan (la de la pila sale y la nueva
    no entra); si no, la nueva entra a la pila. Devuelve las stats.
    """
    stats = {"removed": 0, "pairs_cancelled": 0, "pairs_commuting": 0}
    depth = 0
    # La pila: (opcode, operandos, línea, depth, qubits).
    stack: list[tuple[str, list[str], str, int, frozenset]] = []
    # Índice: (opcode, operandos) -> compuertas en la pila (los
    # objetos, en orden; solo autoinversas). Sirve para saber en
    # O(1) si hay un par candidato, sin escanear la pila.
    index: dict[tuple[str, tuple[str, ...]], list[tuple]] = {}

    def flush_stack() -> None:
        for _, _, line, _, _ in stack:
            out.append(line)
        stack.clear()
        index.clear()

    def push(op: str, args: list[str], raw: str) -> None:
        gate = (op, args, raw, depth, _qubits_of(op, args))
        stack.append(gate)
        if op in SELF_INVERSE:
            index.setdefault((op, tuple(args)), []).append(gate)
        if len(stack) > max_pending:
            # Lo más viejo se confirma a la salida (como el
            # peephole: pop(0), el mismo costo que ya paga).
            old = stack.pop(0)
            if old[0] in SELF_INVERSE:
                lst = index.get((old[0], tuple(old[1])))
                if lst:
                    lst.remove(old)
                    if not lst:
                        del index[(old[0], tuple(old[1]))]
            out.append(old[2])

    for raw in lines:
        op, args = _split(raw)
        if op == "PUSH_CONDITION":
            flush_stack()
            depth += 1
            out.append(raw)
            continue
        if op == "POP_CONDITION":
            flush_stack()
            depth = max(0, depth - 1)
            out.append(raw)
            continue
        if not op or op in ("REGISTER", "APPEND_TO_REGISTER"):
            flush_stack()
            out.append(raw)
            continue
        # ¿Hay un par idéntico hacia atrás, separado solo por
        # compuertas en qubits disjuntos?
        cancelled = False
        if op in SELF_INVERSE and stack:
            key = (op, tuple(args))
            if index.get(key):
                qs = _qubits_of(op, args)
                # Escanear hacia atrás, acotado a max_gap.
                limit = max(0, len(stack) - max_gap - 1)
                for pos in range(len(stack) - 1, limit - 1, -1):
                    g_op, g_args, _, g_depth, _ = stack[pos]
                    if g_depth != depth:
                        break
                    if g_op != op or g_args != args:
                        continue
                    # ¿Todo lo que hay entre medias es disjunto?
                    ok = True
                    for j in range(pos + 1, len(stack)):
                        if stack[j][4] & qs:
                            ok = False
                            break
                    if ok:
                        gate = stack.pop(pos)
                        lst = index.get(key)
                        if lst:
                            lst.remove(gate)
                            if not lst:
                                del index[key]
                        stats["removed"] += 2
                        stats["pairs_cancelled"] += 1
                        if len(stack) - pos > 0:
                            stats["pairs_commuting"] += 1
                        cancelled = True
                    break
        if not cancelled:
            push(op, args, raw)
    flush_stack()
    return stats


def commuting_clean(lines, out=None) -> tuple[list[str] | None, dict]:
    """Limpia un .kmx (lista de líneas) con conmutación.

    Devuelve (líneas_limpias, stats). Con ``out`` (una lista o un
    objeto con append) las líneas limpias van ahí.
    """
    if out is None:
        out = []
    stats = _commuting_pass(lines, out)
    return out, stats


class _StreamingList(list):
    """Una lista que escribe a disco al hacer append (streaming)."""

    def __init__(self, fh):
        self._fh = fh

    def append(self, line: str) -> None:
        self._fh.write(line + "\n")


def clean_commuting_file(in_path: str | Path, out_path: str | Path) -> dict:
    """Limpia un .kmx en disco, en streaming, en una sola pasada.

    Devuelve las stats. Lee línea a línea y escribe al vuelo.
    """
    in_path = Path(in_path)
    out_path = Path(out_path)
    with in_path.open(encoding="utf-8") as fin, \
            out_path.open("w", encoding="utf-8") as fout:
        _, stats = commuting_clean(
            (line.rstrip("\n") for line in fin),
            out=_StreamingList(fout))
    return stats

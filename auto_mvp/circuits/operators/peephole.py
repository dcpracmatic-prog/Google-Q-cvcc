"""AUTO_MVP v2.4 — el PEEPHOLE: la ruta Fast de GUOQ, bien hecha.

La especificación del Protocolo Autónomo (Capa 3, GUOQ) describe la
ruta Fast como reescritura algebraica inmediata: fusionar rotaciones
Z_POW adyacentes sobre el mismo qubit y remover pares de compuertas
Clifford idénticas adyacentes. Los scripts quantum_circuit_optimizer
(v1-v3) intentaban esto, pero sobre un formato .kmx/.kmb INVENTADO
y con matrices 2x2 que no representan las compuertas de varios
qubits. Este módulo lo hace sobre el .kmx REAL de kickmix, y solo
con reescrituras EXACTAS (identidades locales), así que la validez
se preserva por construcción — y el verificador oficial lo confirma
después (fast_verify).

Reglas (todas exactas, todas locales, sin reordenar nada):
- Z_POW adyacente sobre el mismo qubit (misma profundidad de
  condición) se fusiona sumando los ángulos (en vueltas, mod 2).
  Si la suma es 0, se van las dos (identidad). Menos rotaciones =
  menos costo de síntesis (el verificador cobra por rotación).
- Pares idénticos adyacentes de compuertas autoinversas se cancelan:
  X, Z, H, CX, SWAP, CCX, CSWAP (cada una es su propia inversa).
  Solo se cancelan si los operandos escritos son idénticos.
- No se toca nada más: ni R (reset/medición), ni T (T·T=S, no es
  identidad), ni S (S·S=Z, cambia el tipo de puerta), ni compuertas
  en distinta profundidad de condición (PUSH/POP entre medias rompe
  la adyacencia), ni nada que no sea una identidad exacta.

La limpieza es UNA SOLA PASADA con PILA (v2.7): la pasada con una
sola compuerta pendiente NO era idempotente, porque al cancelar un
par las compuertas que lo rodeaban se volvían adyacentes y solo se
veían en la siguiente pasada (en la semilla invsqrt hacían falta
más de 15 pasadas, 4 por pasada, para llegar al punto fijo). Con
una pila, la salida ES la pila: cada compuerta nueva se compara
con la última emitida, y al cancelar un par la siguiente compuerta
se compara con la que quedó debajo, en la misma pasada. Es el
algoritmo clásico de reducción (como cancelar paréntesis): una
pasada encuentra TODAS las cancelaciones, así que el resultado sí
es idempotente y no hace falta repetir. Cada reescritura sigue
siendo exacta, así que la validez se preserva y el S no cambia.
"""
from __future__ import annotations

from decimal import Context, Decimal, localcontext
from pathlib import Path

# Compuertas autoinversas: G·G = I (con los mismos operandos).
SELF_INVERSE = {"X", "Z", "H", "CX", "SWAP", "CCX", "CSWAP"}


def _split(line: str) -> tuple[str, list[str]]:
    """Una línea .kmx sin comentario: (opcode, operandos)."""
    s = line.split("#", 1)[0].strip()
    if not s:
        return "", []
    parts = s.split()
    return parts[0], parts[1:]


def _peephole_pass(lines, out, max_pending: int = 4096) -> dict:
    """Una sola pasada de la ruta Fast sobre las líneas, con pila.

    La pila guarda las compuertas emitidas que aún pueden cancelarse
    con la siguiente (en memoria, acotada a ``max_pending``; lo
    confirmado va a ``out`` en streaming, así que no se carga el
    circuito entero). Cada compuerta nueva se compara con la última
    de la pila: si es el mismo par autoinverso, se cancelan las dos
    (se saca de la pila y la nueva no entra); si es una Z_POW sobre
    el mismo qubit que la última, se fusionan los ángulos; si no,
    entra a la pila. Al cancelar un par, la siguiente compuerta se
    compara con la que quedó debajo, en la misma pasada: es el
    algoritmo clásico de reducción, así que una pasada encuentra
    TODAS las cancelaciones (las que se vuelven adyacentes al
    cancelar un par se ven sin repetir la pasada). Las líneas que
    no son compuertas (REGISTER, APPEND_TO_REGISTER, comentarios,
    vacías) y PUSH/POP pasan tal cual y vacían la pila a ``out``
    (nada se cancela a través de ellas).

    Devuelve las stats de la pasada.
    """
    stats = {"removed": 0, "zpow_fused": 0, "zpow_removed": 0,
             "pairs_cancelled": 0}
    # El salto de línea se hereda de la entrada (igual que en
    # rotation_merge v2.13.0): si las líneas traen "\n", la Z_POW
    # fusionada también lo lleva, para que ''.join() de la salida
    # sea un .kmx válido. Sin esto, la línea fusionada se pegaba
    # a la siguiente y el .kmx ya no cargaba.
    if isinstance(lines, (list, tuple)):
        nl = "\n" if any(l.endswith("\n") for l in lines) else ""
    else:
        nl = ""
    depth = 0
    # La pila de compuertas emitidas que aún pueden cancelarse.
    # Cada elemento es (opcode, operandos, línea, depth).
    stack: list[tuple[str, list[str], str, int]] = []

    def flush_stack() -> None:
        for _, _, line, _ in stack:
            out.append(line)
        stack.clear()

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
        # Una compuerta: ¿se combina con la última de la pila?
        if stack and stack[-1][3] == depth:
            top_op, top_args, _, _ = stack[-1]
            if op == "Z_POW" and top_op == "Z_POW" and args and top_args \
                    and args[0] == top_args[0]:
                # Fusionar: sumar ángulos en vueltas (mod 2), en
                # Decimal EXACTO (los ángulos del .kmx son decimales
                # de 60 dígitos; por float se pierde ~1e-16 y el S
                # medido se mueve ~5e-04 — hallazgo de la auditoría
                # de v2.5 en rotation_merge; y el contexto por defecto
                # redondea a 28 dígitos, por eso prec=100).
                try:
                    with localcontext(Context(prec=100)):
                        a = (Decimal(top_args[1]) + Decimal(args[1])) % 2
                except (IndexError, ValueError, ArithmeticError):
                    a = None
                if a is not None:
                    if a == 0:
                        stack.pop()
                        stats["removed"] += 2
                        stats["zpow_removed"] += 2
                    else:
                        # normalize() quita los ceros sobrantes de la
                        # suma (0.25+0.75 = 1.00 -> 1.0).
                        astr = format(a.normalize(), "f")
                        if "." not in astr:
                            astr += ".0"
                        stack[-1] = ("Z_POW", [args[0], astr],
                                     f"Z_POW {args[0]} {astr}" + nl, depth)
                        stats["zpow_fused"] += 1
                    continue
            if op == top_op and op in SELF_INVERSE and args == top_args:
                # Par idéntico autoinverso: se cancelan las dos.
                stack.pop()
                stats["removed"] += 2
                stats["pairs_cancelled"] += 1
                continue
        stack.append((op, args, raw, depth))
        # Acotar la pila: lo más viejo se confirma a la salida.
        # (Una cancelación que necesitara más de max_pending
        # compuertas intermedias se perdería, pero el resultado
        # sigue siendo válido; en la semilla y el DQI las cadenas
        # son mucho más cortas.)
        if len(stack) > max_pending:
            _, _, line, _ = stack.pop(0)
            out.append(line)
    flush_stack()
    return stats


def peephole_clean(lines, out=None) -> tuple[list[str] | None, dict]:
    """Limpia un .kmx (lista de líneas) con la ruta Fast.

    Devuelve (líneas_limpias, stats). Una sola pasada con pila
    encuentra TODAS las cancelaciones (ver _peephole_pass), así
    que el resultado es idempotente: una segunda pasada no quita
    nada. Cada reescritura es exacta, así que la validez se
    preserva y el S no cambia.

    Con ``out`` (una lista o un objeto con append, p. ej. un
    escritor a disco) las líneas limpias van ahí en vez de a una
    lista nueva.
    """
    if out is None:
        out = []
    stats = _peephole_pass(lines, out)
    return out, stats


class _StreamingList(list):
    """Una lista que escribe a disco al hacer append (streaming).

    Hereda de list para que el código que la recibe no cambie, pero
    no guarda nada: cada línea va directa al archivo. Así los
    operadores trabajan en circuitos de 64M de líneas sin OOM.
    """

    def __init__(self, fh):
        self._fh = fh

    def append(self, line: str) -> None:
        self._fh.write(line + "\n")


def clean_file(in_path: str | Path, out_path: str | Path) -> dict:
    """Limpia un .kmx en disco, en streaming, en una sola pasada.

    Devuelve las stats. Lee línea a línea y escribe al vuelo (la
    pila interna está acotada, así que no se carga el circuito
    entero: el DQI tiene 64M de líneas).
    """
    in_path = Path(in_path)
    out_path = Path(out_path)
    with in_path.open(encoding="utf-8") as fin, \
            out_path.open("w", encoding="utf-8") as fout:
        _, stats = peephole_clean(
            (line.rstrip("\n") for line in fin),
            out=_StreamingList(fout))
    return stats

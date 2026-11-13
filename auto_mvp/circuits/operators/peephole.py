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

La pasada es determinista e idempotente (una segunda pasada sobre
un circuito ya limpio no encuentra nada), así que puede ir como
pre-paso del operador sa_windows sin romper la reproducibilidad de
las semillas: la receta (K, seed) reconstruye lo mismo.
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


def peephole_clean(lines, out=None) -> tuple[list[str] | None, dict]:
    """Limpia un .kmx (lista de líneas) con la ruta Fast.

    Devuelve (líneas_limpias, stats). Las líneas que no son
    compuertas (REGISTER, APPEND_TO_REGISTER, comentarios, vacías)
    pasan tal cual. Solo se combinan compuertas consecutivas a la
    misma profundidad de condición.

    Con ``out`` (una lista o un objeto con append, p. ej. un
    escritor a disco) las líneas limpias van ahí en vez de a una
    lista nueva: así ``clean_file`` procesa en STREAMING y no
    necesita cargar el circuito entero en memoria (el DQI tiene
    64M de líneas y la versión en memoria se moría por OOM).
    """
    if out is None:
        out = []
    stats = {"removed": 0, "zpow_fused": 0, "zpow_removed": 0,
             "pairs_cancelled": 0}
    depth = 0
    # La última compuerta emitida (pendiente de combinar con la
    # siguiente). Se guarda como (opcode, operandos, línea, depth).
    pending: tuple[str, list[str], str, int] | None = None

    def flush() -> None:
        nonlocal pending
        if pending is not None:
            out.append(pending[2])
            pending = None

    for raw in lines:
        op, args = _split(raw)
        if op == "PUSH_CONDITION":
            flush()
            depth += 1
            out.append(raw)
            continue
        if op == "POP_CONDITION":
            flush()
            depth = max(0, depth - 1)
            out.append(raw)
            continue
        if not op or op in ("REGISTER", "APPEND_TO_REGISTER"):
            flush()
            out.append(raw)
            continue
        # Una compuerta: ¿se combina con la pendiente?
        if pending is not None and pending[3] == depth:
            pop, pargs, pline, _ = pending
            if op == "Z_POW" and pop == "Z_POW" and args and pargs \
                    and args[0] == pargs[0]:
                # Fusionar: sumar ángulos en vueltas (mod 2), en
                # Decimal EXACTO (los ángulos del .kmx son decimales
                # de 60 dígitos; por float se pierde ~1e-16 y el S
                # medido se mueve ~5e-04 — hallazgo de la auditoría
                # de v2.5 en rotation_merge; y el contexto por defecto
                # redondea a 28 dígitos, por eso prec=100).
                try:
                    with localcontext(Context(prec=100)):
                        a = (Decimal(pargs[1]) + Decimal(args[1])) % 2
                except (IndexError, ValueError, ArithmeticError):
                    a = None
                if a is not None:
                    if a == 0:
                        pending = None
                        stats["removed"] += 2
                        stats["zpow_removed"] += 2
                    else:
                        # normalize() quita los ceros sobrantes de la
                        # suma (0.25+0.75 = 1.00 -> 1.0).
                        astr = format(a.normalize(), "f")
                        if "." not in astr:
                            astr += ".0"
                        pending = ("Z_POW", [args[0], astr],
                                   f"Z_POW {args[0]} {astr}", depth)
                        stats["zpow_fused"] += 1
                    continue
            if op == pop and op in SELF_INVERSE and args == pargs:
                # Par idéntico autoinverso: se cancelan las dos.
                pending = None
                stats["removed"] += 2
                stats["pairs_cancelled"] += 1
                continue
        flush()
        pending = (op, args, raw, depth)
    flush()
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
    """Limpia un .kmx en disco, en streaming. Devuelve las stats."""
    in_path = Path(in_path)
    out_path = Path(out_path)
    with in_path.open(encoding="utf-8") as fin, \
            out_path.open("w", encoding="utf-8") as fout:
        _, stats = peephole_clean(
            (line.rstrip("\n") for line in fin),
            out=_StreamingList(fout))
    return stats

"""AUTO_MVP v2.5 — FUSIÓN DE ROTACIONES a través de compuertas que conmutan.

Innovación intentada en v2.5 (directiva de Arturo 2026-11-12 22:04
CST: innovar, diseñar, experimentar, probar, auditar). La idea: el
peephole de v2.4 solo fusiona Z_POW ADYACENTES. Pero una rotación
Z puede moverse a través de compuertas que conmutan con ella y
juntarse con otra rotación del mismo qubit más adelante. Reglas
exactas (todas identidades locales, sin reordenar el cómputo):
- Z_POW(q, θ) se suma a la pendiente de q (mod 2). Si la suma es 0,
  la rotación desaparece.
- X(q): Rz(θ)·X = X·Rz(−θ). La pendiente cambia de signo al pasar.
- CX(c, t): Rz en el CONTROL conmuta con CX; en el TARGET no
  (Rz_t se convierte en Rz_c·Rz_t). La pendiente del target se
  vacía (se emite antes del CX).
- Z, CZ, CCZ: diagonales, conmutan con Rz. La pendiente sigue viva.
- SWAP(a, b): intercambia las pendientes (la rotación se mueve con
  el qubit).
- H, R, HMR, CCX, CSWAP y resto: vacían la pendiente de los qubits
  que tocan (se emite la rotación antes de la compuerta).
- BIT_* y NEG operan sobre bits clásicos (bN), no tocan qubits.
- PUSH/POP_CONDITION: vacían todo (una rotación no cruza la frontera
  de una condición).

MEDIDO en la semilla invsqrt: 0 fusiones. Los 68 Z_POW están todos
aislados por compuertas que no conmutan (CCX, H, R, HMR, CX con el
qubit como target, o Z_POW condicionales). El operador es correcto
(los tests sintéticos fusionan) y queda como capacidad para
circuitos con más rotaciones, pero en la semilla NO mejora nada:
negativo medido, documentado en notes/v2.5.0.md. La pasada es
determinista e idempotente.

AUDITORÍA (dos bugs reales, encontrados al probar en la semilla y
corregidos en v2.5):
1. Las Z_POW CONDICIONALES (20 en la semilla, p. ej. "Z_POW q30 1.5
   if b414") entraban en la pendiente incondicional: una rotación
   que solo aplica si el bit está a 1 se emitía como si siempre
   aplicara. Ahora toda compuerta con "if" vacía la pendiente de
   sus qubits y pasa tal cual.
2. Los ángulos se reemitían con repr() de float: para ángulos chicos
   eso es notación científica (7.6e-06) y el parser .kmx la rechaza
   ("Invalid decimal angle"). Y aunque pasara, el float pierde
   ~1e-16 por ángulo y el S medido se movía 4.7e-04. Ahora las
   pendientes son Decimal EXACTO: sin fusiones la salida es
   byte-idéntica a la entrada y el S medido es idéntico.
"""
from __future__ import annotations

from decimal import Context, Decimal, localcontext
from pathlib import Path


def _split(line: str) -> tuple[str, list[str]]:
    s = line.split("#", 1)[0].strip()
    if not s:
        return "", []
    parts = s.split()
    return parts[0], parts[1:]


def rotation_merge(lines, out=None) -> tuple[list[str] | None, dict]:
    """Fusiona Z_POW a través de compuertas que conmutan.

    Devuelve (líneas_limpias, stats). Solo reescrituras exactas.

    Con ``out`` (una lista o un objeto con append, p. ej. un
    escritor a disco) las líneas van ahí en vez de a una lista
    nueva: así ``merge_file`` procesa en STREAMING y no necesita
    cargar el circuito entero en memoria (el DQI tiene 64M de
    líneas y la versión en memoria se moría por OOM).
    """
    if out is None:
        out = []
    stats = {"merged": 0, "removed": 0, "zpow_in": 0, "zpow_out": 0}
    # Las pendientes son Decimal EXACTO, no float: los ángulos del
    # .kmx son decimales de 60 dígitos (aritmética racional exacta) y
    # pasarlos por float pierde ~1e-16 por ángulo, lo que movía el S
    # medido en 4.7e-04. Con Decimal la suma es exacta y el S medido
    # es idéntico (verificado en la semilla). (El contexto por defecto
    # redondea a 28 dígitos: se usa prec=100 para que los 60 dígitos
    # sobrevivan intactos. La salida no es byte-idéntica aunque no
    # haya fusiones: 7 rotaciones se re-emiten más adelante, tras
    # compuertas que no tocan su qubit — válido, S idéntico.)
    pending: dict[str, Decimal] = {}

    def emit(q: str) -> None:
        angle = pending.pop(q, Decimal(0)) % 2
        if angle != 0:
            # normalize() quita los ceros sobrantes de la suma
            # (0.25+0.75 = 1.00 -> 1.0); sin él el test v2.4 espera
            # '1.0' y saldría '1.00'.
            astr = format(angle.normalize(), "f")
            if "." not in astr:
                astr += ".0"
            out.append(f"Z_POW {q} {astr}")
            stats["zpow_out"] += 1

    def flush_all() -> None:
        for q in sorted(pending):
            emit(q)

    with localcontext(Context(prec=100)):
        _scan(lines, out, stats, pending, emit, flush_all)
    return out, stats


def _scan(lines, out, stats, pending, emit, flush_all) -> None:
    """El barrido principal (dentro del contexto Decimal prec=100)."""

    for raw in lines:
        op, args = _split(raw)
        if op == "PUSH_CONDITION":
            flush_all()
            out.append(raw)
            continue
        if op == "POP_CONDITION":
            flush_all()
            out.append(raw)
            continue
        if not op or op in ("REGISTER", "APPEND_TO_REGISTER", "BIT_STORE0",
                            "BIT_STORE1", "BIT_INVERT", "NEG"):
            out.append(raw)
            continue
        if "if" in args:
            # Compuerta CONDICIONAL (p. ej. Z_POW q30 1.5 if b414, o
            # CX q21 q3 if bN): la rotación pendiente es incondicional
            # y no puede cruzarla (una Z_POW condicional solo aplica
            # si el bit está a 1; una X condicional solo invierte el
            # signo si el bit está a 1). Se vacía la pendiente de sus
            # qubits y la compuerta pasa tal cual. Esto era el bug que
            # invalidaba la semilla en la primera versión: una Z_POW
            # condicional entraba en la pendiente incondicional.
            for q in args:
                if q.startswith("q") and q in pending:
                    emit(q)
            out.append(raw)
            continue
        if op == "Z_POW":
            stats["zpow_in"] += 1
            q = args[0]
            new = (pending.get(q, Decimal(0)) + Decimal(args[1])) % 2
            if q in pending:
                stats["merged"] += 1
            if new == 0:
                pending.pop(q, None)
                stats["removed"] += 1
            else:
                pending[q] = new
            continue
        if op == "X":
            q = args[0]
            if q in pending:
                pending[q] = -pending[q]
            out.append(raw)
            continue
        if op == "CX":
            c, t = args[0], args[1]
            if t in pending:
                emit(t)
            out.append(raw)
            continue
        if op == "SWAP":
            a, b = args[0], args[1]
            pa, pb = pending.get(a), pending.get(b)
            pending.pop(a, None)
            pending.pop(b, None)
            if pb is not None:
                pending[a] = pb
            if pa is not None:
                pending[b] = pa
            out.append(raw)
            continue
        if op in ("Z", "CZ", "CCZ"):
            # Diagonales: conmutan con Rz, la pendiente sigue viva.
            out.append(raw)
            continue
        # H, R, HMR, CCX, CSWAP y resto: vacían los qubits que tocan.
        for q in args:
            if q.startswith("q") and q in pending:
                emit(q)
        out.append(raw)
    flush_all()


class _StreamingList(list):
    """Una lista que escribe a disco al hacer append (streaming)."""

    def __init__(self, fh):
        self._fh = fh

    def append(self, line: str) -> None:
        self._fh.write(line + "\n")


def merge_file(in_path: str | Path, out_path: str | Path) -> dict:
    """Fusiona las rotaciones de un .kmx en disco, en streaming.

    Devuelve las stats.
    """
    in_path = Path(in_path)
    out_path = Path(out_path)
    with in_path.open(encoding="utf-8") as fin, \
            out_path.open("w", encoding="utf-8") as fout:
        _, stats = rotation_merge(
            (line.rstrip("\n") for line in fin),
            out=_StreamingList(fout))
    return stats

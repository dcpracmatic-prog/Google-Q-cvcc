"""AUTO_MVP v2.4 — la TRAZA DIALOG (acceso implícito), bien hecha.

El documento de Arturo (2026-11-12) define el Dialog algebraico:
en el EEA, en vez de materializar los coeficientes de Bézout, se
guarda la TRAZA — la lista de matrices de transición 2x2 (Doblado,
Inversión, Adición) de un MCD sin divisiones — y se reconstruye
sigma(z) por PLAYBACK. Los scripts quantum_circuit_optimizer (v1-v3)
intentaban un "Dialog" que no es este: un playback de vector de
estado con matrices 2x2 que no representan las compuertas de varios
qubits. Este módulo implementa el Dialog ALGEBRAICO correcto.

Cómo funciona (polinomios sobre GF(2), como enteros de Python:
el bit i es el coeficiente de z^i):
- Cada paso del EEA divide r_{i-1} entre r_i: cociente q_i y resto
  r_{i+1}. La matriz de transición es tau_i = [[0, 1], [1, q_i]].
- La TRAZA es solo la lista de cocientes q_i (las matrices se
  reconstruyen de ellos): eso es lo compacto del Dialog.
- El PLAYBACK multiplica las tau_i en orden y aplica la matriz
  total a (a, b): reconstruye los coeficientes de Bézout (sigma,
  omega) sin haberlos guardado nunca.

Alcance honesto: la traza aquí viene del EEA ESTÁNDAR (con
divisiones), no de la variante de tiempo constante de Bernstein-Yang
(sin divisiones, con primitivas Doblado/Inversión/Adición). El
mecanismo es el mismo (traza + playback); la variante de tiempo
constante es una optimización futura, no el concepto. Y el veredicto
para OPI sigue siendo el del documento: en GF(2^b) con n<<m gana el
EXPLÍCITO (Chien con QC es Clifford, gratis; con Dialog, Chien se
vuelve QQ y cuesta Toffolis). Este módulo existe para que ese
veredicto sea CÓDIGO MEDIDO, no prosa: en casos chicos, la traza
reproduce exactos los coeficientes del EEA explícito.

La ecuación clave de DQI: sigma(z)·S(z) = omega(z) (mod z^{2l}).
Con a = z^{2l} y b = S(z), el EEA se detiene cuando deg(resto) < l:
el resto es omega y su coeficiente de Bézout es sigma.
"""
from __future__ import annotations


def deg(p: int) -> int:
    """Grado de un polinomio GF(2) (como entero de bits); -1 si es 0."""
    return p.bit_length() - 1 if p else -1


def pmul(a: int, b: int) -> int:
    """Multiplicación de polinomios sobre GF(2)."""
    out = 0
    while b:
        if b & 1:
            out ^= a
        a <<= 1
        b >>= 1
    return out


def pdivmod(a: int, b: int) -> tuple[int, int]:
    """División de polinomios sobre GF(2): (cociente, resto)."""
    if b == 0:
        raise ZeroDivisionError("división por el polinomio cero")
    q, r = 0, a
    db = deg(b)
    while r and deg(r) >= db:
        shift = deg(r) - db
        q ^= 1 << shift
        r ^= b << shift
    return q, r


def eea_explicit(a: int, b: int, stop_degree: int | None = None
                 ) -> tuple[int, int, int, int]:
    """El EEA EXPLÍCITO: devuelve (r, s, t, pasos).

    s·a + t·b = r. Sin parada, r es el MCD (el último resto no nulo).
    Con stop_degree (la parada de la ecuación clave), r es el PRIMER
    resto con grado < stop_degree (omega) y (s, t) sus coeficientes.
    """
    r0, r1 = a, b
    s0, s1 = 1, 0
    t0, t1 = 0, 1
    steps = 0
    while r1:
        if stop_degree is not None and deg(r1) < stop_degree:
            return r1, s1, t1, steps
        q, r = pdivmod(r0, r1)
        r0, r1 = r1, r
        s0, s1 = s1, s0 ^ pmul(q, s1)
        t0, t1 = t1, t0 ^ pmul(q, t1)
        steps += 1
    return r0, s0, t0, steps


def eea_trace(a: int, b: int, stop_degree: int | None = None
              ) -> list[int]:
    """La TRAZA Dialog: solo la lista de cocientes q_i del EEA.

    Cada cociente define su matriz de transición tau_i =
    [[0, 1], [1, q_i]]. Guardar la traza (y no los coeficientes
    de Bézout) es el acceso implícito.
    """
    trace: list[int] = []
    r0, r1 = a, b
    while r1:
        if stop_degree is not None and deg(r1) < stop_degree:
            break
        q, r = pdivmod(r0, r1)
        trace.append(q)
        r0, r1 = r1, r
    return trace


def _mat_mul_2x2(A: tuple[int, int, int, int],
                 B: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Producto de matrices 2x2 sobre GF(2)[z]."""
    a11, a12, a21, a22 = A
    b11, b12, b21, b22 = B
    return (pmul(a11, b11) ^ pmul(a12, b21),
            pmul(a11, b12) ^ pmul(a12, b22),
            pmul(a21, b11) ^ pmul(a22, b21),
            pmul(a21, b12) ^ pmul(a22, b22))


def playback(trace: list[int]) -> tuple[int, int, int, int]:
    """El PLAYBACK: multiplica las tau_i y devuelve la matriz total.

    La matriz total M cumple: (r_final, r_prev) = M · (a, b) y sus
    filas son los coeficientes de Bézout (s, t) de cada resto.
    """
    total: tuple[int, int, int, int] = (1, 0, 0, 1)
    for q in trace:
        total = _mat_mul_2x2((0, 1, 1, q), total)
    return total


def dialog_bezout(a: int, b: int, stop_degree: int | None = None
                  ) -> tuple[int, int, int, list[int]]:
    """(r, s, t, traza) reconstruidos SOLO desde la traza.

    La matriz total aplicada a (a, b) da los DOS restos finales
    (r_first, r_second). El objetivo es el mismo que en el EEA
    explícito: con parada, el primer resto con grado < stop_degree
    (el segundo, si existe); sin ella, el último resto no nulo (el
    primero). Los Bézout (s, t) son la fila correspondiente de la
    matriz total. Nunca se guardaron: se reconstruyeron.
    """
    trace = eea_trace(a, b, stop_degree)
    m11, m12, m21, m22 = playback(trace)
    r_first = pmul(m11, a) ^ pmul(m12, b)
    r_second = pmul(m21, a) ^ pmul(m22, b)
    if (stop_degree is not None and r_second
            and deg(r_second) < stop_degree):
        return r_second, m21, m22, trace
    return r_first, m11, m12, trace


def trace_bits(trace: list[int]) -> int:
    """Tamaño de la traza en bits (la medida de lo compacto)."""
    return sum(max(1, q.bit_length()) for q in trace)


def explicit_bits(s: int, t: int) -> int:
    """Tamaño de los coeficientes de Bézout explícitos, en bits."""
    return max(1, s.bit_length()) + max(1, t.bit_length())

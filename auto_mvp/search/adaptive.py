"""Control adaptativo de busqueda (Ley Cuantica de la Existencia v6/v6.1).

Dos mecanismos formales:
1. Dinamica con inercia: ds/dtau = k * (sigma_bar - s).
   s = agresividad/temperatura de busqueda (0..1). sigma_bar = tasa de
   exito real en los verificadores (fraccion de intentos que pasan y
   mejoran). Si las mutaciones agresivas rompen cotas duras (scratch,
   restauracion, Frobenius, Lambda, E_gap, eps+ < 1/16), sigma_bar baja
   y s baja de forma amortiguada -> cambios mas pequenos.
2. Saturacion informacional: sum I <= H(X). Cuando una familia de
   mutaciones deja de reducir el costo real o repite estructuras
   equivalentes durante N intentos, se poda esa rama (se marca esteril)
   y se cambia de estrategia.

Esto NO mejora un circuito por si solo. Hace la busqueda mas eficiente:
gasta menos intentos en ramas esteriles y ajusta la agresividad a lo
que el verificador realmente acepta.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class AdaptiveSearch:
    """Controlador de agresividad y poda de ramas."""
    # Inercia: s sigue a sigma_bar con constante k (0..1 por paso).
    k: float = 0.2
    s: float = 0.5  # agresividad inicial (0=conservador, 1=agresivo)
    # Ventana para medir la tasa de exito real.
    window: int = 20
    # Saturacion: intentos sin mejora antes de podar una rama.
    stall_limit: int = 25
    # Historial de resultados (True = paso verificador y mejoro).
    _results: deque = field(default_factory=lambda: deque(maxlen=20))
    # Intentos desde la ultima mejora, por familia de mutacion.
    _stall: dict = field(default_factory=dict)
    # Ramas podadas (esteriles).
    pruned: set = field(default_factory=set)

    def sigma_bar(self) -> float:
        """Tasa de exito real en la ventana (0..1)."""
        if not self._results:
            return 0.5
        return sum(1 for r in self._results if r) / len(self._results)

    def record(self, family: str, improved: bool,
               hard_violation: bool = False) -> None:
        """Registra un intento. improved=True solo si paso el verificador
        oficial (o el smoke test equivalente) Y bajo el costo real.
        hard_violation=True si rompio una cota dura (Q > 128, eps+ >= 1/16,
        error de fase en invsqrt, Frobenius > 0.020, Lambda <= 49,
        E_gap fuera de rango). En ese caso s cae RAPIDO hacia
        mutaciones locales/conservadoras. Si pasa las cotas duras pero
        mejora poco, s se mantiene en rango intermedio para explorar
        composiciones de motivos en lugar de descartar todo."""
        self._results.append(bool(improved))
        if improved:
            self._stall[family] = 0
        else:
            self._stall[family] = self._stall.get(family, 0) + 1
        # Dinamica con inercia: s se mueve hacia sigma_bar.
        # Si hubo violacion dura, la caida es mas rapida (k doble).
        k_eff = self.k * 2.0 if hard_violation else self.k
        self.s = self.s + k_eff * (self.sigma_bar() - self.s)
        # Si viola cota dura, forzar s hacia abajo de inmediato.
        if hard_violation:
            self.s = min(self.s, 0.3)
        self.s = max(0.05, min(0.95, self.s))
        # Saturacion: podar la familia si lleva demasiados intentos sin mejora.
        if self._stall.get(family, 0) >= self.stall_limit:
            self.pruned.add(family)

    def aggressiveness(self) -> float:
        """Agresividad actual s (0..1)."""
        return self.s

    def is_pruned(self, family: str) -> bool:
        """True si la familia esta podada (esteril)."""
        return family in self.pruned

    def stall_count(self, family: str) -> int:
        """Intentos sin mejora de una familia."""
        return self._stall.get(family, 0)

    def suggest_step(self) -> str:
        """Sugerencia cualitativa segun s (para el prompt del LLM)."""
        if self.s < 0.3:
            return "conservador: cambios pequenos, un parametro a la vez"
        if self.s < 0.7:
            return "moderado: cambios medianos, probar 2-3 variantes"
        return "agresivo: cambios grandes, explorar estructuras nuevas"


# --- Reparto de esfuerzo segun la brecha de media geometrica (v6.1, punto 2) ---
# La tarea con el menor cociente referencia/actual frena la GM: ahi se
# concentran los intentos, sin dejar que otra se rompa.
def select_task(ratios: dict) -> str:
    """Devuelve la tarea mas rezagada (menor ratio referencia/actual).
    Hoy: dfthcsos (11.39x) < invsqrt (27.91x) < dqi (70.79x)."""
    if not ratios:
        return "dfthcsos"
    return min(ratios, key=ratios.get)


def effort_share(ratios: dict) -> dict:
    """Reparte el esfuerzo (fraccion de intentos) inversamente al ratio:
    la tarea mas rezagada recibe mas intentos. Normalizado a suma 1."""
    if not ratios:
        return {"invsqrt": 1.0 / 3, "dqi": 1.0 / 3, "dfthcsos": 1.0 / 3}
    inv = {k: 1.0 / max(v, 1e-9) for k, v in ratios.items()}
    tot = sum(inv.values())
    return {k: v / tot for k, v in inv.items()}

"""Modelos de costos medidos (prefiltro): estiman en milisegundos.

Ninguno decide un puntaje: solo ordenan candidatos para que el paso
caro (construir + verificar con kickmix) solo se gaste en los que
pueden ganar. El S que cuenta es siempre el MEDIDO.
"""
from .dqi_cost import estimate_variant, explicit_corrected, score, sweep

__all__ = ["estimate_variant", "explicit_corrected", "score", "sweep"]

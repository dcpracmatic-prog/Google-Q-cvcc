"""AUTO_MVP v0.3.1 — caché de verificación por hash de parámetros.

Idea de los archivos DSP de Arturo (calibrar_dsp: caché por sonda):
verificar dos veces el mismo candidato es tirar cómputo. La caché
guarda el resultado de ``verify`` keyed por el hash canónico de la
identidad del candidato (tarea + métricas + parámetros +
``verified_by``). Un candidato idéntico no vuelve a verificarse.

LÍMITES HONESTOS:
- La caché es por identidad EXACTA: dos candidatos con los mismos
  números son el mismo candidato para el verificador (la verificación
  es determinista en los números). Si la verificación dependiera de
  algo fuera de la identidad (un archivo, el estado del hardware),
  la caché mentiría: por eso ``factorization_path`` (química, archivo
  .npz) forma parte de la clave cuando existe.
- La caché guarda el RESULTADO de la verificación, no el veredicto
  de integridad: un resultado cacheado sigue pasando por el filtro
  de integridad en el orquestador.
- Capacidad acotada (FIFO): cuando se llena, sale el más antiguo.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .integrity import canonical_hash


def candidate_key(candidate: dict[str, Any]) -> str:
    identity = {
        "task": candidate.get("task"),
        "metrics": candidate.get("metrics", {}),
        "params": candidate.get("params", {}),
        "verified_by": candidate.get("verified_by", ""),
        "factorization_path": candidate.get("factorization_path", ""),
        "S": candidate.get("S"),
    }
    return canonical_hash(identity)


@dataclass
class VerificationCache:
    max_entries: int = 1024
    hits: int = 0
    misses: int = 0
    _store: dict[str, Any] = field(default_factory=dict)

    def get(self, candidate: dict[str, Any]) -> Any | None:
        key = candidate_key(candidate)
        if key in self._store:
            self.hits += 1
            return self._store[key]
        self.misses += 1
        return None

    def put(self, candidate: dict[str, Any], result: Any) -> None:
        key = candidate_key(candidate)
        if key not in self._store and len(self._store) >= self.max_entries:
            oldest = next(iter(self._store))
            del self._store[oldest]
        self._store[key] = result

    def __len__(self) -> int:
        return len(self._store)


def verify_with_cache(cache: VerificationCache, verifier: Any,
                      candidate: dict[str, Any]) -> tuple[Any, bool]:
    """Verifica con caché. Devuelve (resultado, fue_acierto)."""
    cached = cache.get(candidate)
    if cached is not None:
        return cached, True
    result = verifier.verify(candidate)
    cache.put(candidate, result)
    return result, False

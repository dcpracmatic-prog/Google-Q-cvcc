"""AUTO_MVP v0.3.0 — filtro de integridad (fase 2 de la especificación).

La lección del paso 51: una reducción de Q puramente numérica (Q=1,990)
corrompió la equivalencia lógica del sigma y la criba por costo no lo
detectó, porque el costo no revisa la lógica. Este filtro cierra ese
hueco y es OBLIGATORIO para cualquier candidato con circuito real:

- El candidato trae EVIDENCIA de integridad (no promesas): hash del
  sigma contra la referencia clásica, C/B restaurados, dreg y alpha
  en cero, temporales en cero.
- Sin evidencia, no hay aceptación como verificado: un candidato sin
  evidencia solo puede ser mejor PROYECTADO, nunca mejor VERIFICADO.
- La evidencia se revisa envolviendo la CONSTRUCCIÓN del circuito
  (CircuitConstructionGuard), no solo al mutador: el paso 51 nunca
  pasó por el SearchLoop, pasó por el constructor.

Excepciones documentadas: un temporal puede quedar sucio POR DISEÑO
(por ejemplo tmpD2 en el paso 51 v3, +840q) solo si aparece en
``allowed_dirty`` con su motivo escrito. La excepción es explícita,
nombrada y acotada; lo que no está listado, debe estar en cero.

LÍMITE HONESTO: este módulo valida la evidencia que trae el candidato
y su consistencia interna (hashes, conteos, ceros). No re-ejecuta la
simulación kickmix por su cuenta: eso lo hace el verificador oficial
(vqcc.verify) o el constructor con su propio simulador. Un hash que
coincide prueba que el sigma ES el de la referencia, no que el
circuito se construyó bien por dentro; por eso el filtro exige
además C/B restaurados y temporales en cero.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable

from .gf212 import monic as _monic
from .gf212 import scale_factor as _scale_factor


def canonical_hash(values: Any) -> str:
    """SHA-256 del JSON canónico (claves ordenadas) de unos valores.

    Es la forma en que dos sigmas se comparan sin ambigüedad: mismo
    contenido, mismo hash; un coeficiente distinto, otro hash.
    """
    blob = json.dumps(values, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def monic_sigma(sigma: list[int]) -> list[int]:
    """Forma mónica del sigma en GF(2^12) (primer coeficiente 1)."""
    return _monic(sigma)


def sigma_scale_factor(sigma: list[int], ref: list[int]) -> int | None:
    """k tal que sigma == k·ref en GF(2^12), o None si no lo es."""
    return _scale_factor(sigma, ref)


@dataclass
class IntegrityEvidence:
    """Evidencia de integridad que acompaña a un candidato.

    kind: "circuit" (hay circuito real y simulación) o "projection"
        (solo números de costo, sin circuito).
    sigma: coeficientes del sigma medido (lista de enteros) o None.
    sigma_ref_hash: hash canónico del sigma de referencia (misma
        representación que ``sigma``) o None si no hay referencia.
    c_restored / b_restored: coeficientes C/B que volvieron a su valor
        inicial, de un total (por ejemplo 180/180 en 5 shots x 36).
    total_coef: el total contra el que se comparan los restaurados.
    dreg_zero / alpha_zero: dreg y alpha terminaron en cero.
    temporaries_zero / temporaries_total: temporales en cero del total.
    allowed_dirty: temporales sucios POR DISEÑO, cada uno con motivo
        (por ejemplo {"tmpD2": "ciclo de limpiezas paso 51, +840q"}).
    shots: número de shots de la verificación que produjo la evidencia.
    verified_by: quién produjo la evidencia ("gu_trace", "official",
        "circuit_sim", ...). Cadena libre, se registra tal cual.
    """
    kind: str = "projection"
    sigma: list[int] | None = None
    sigma_ref_hash: str | None = None
    # v0.3.1 (lección del paso 51 v3): el sigma del circuito es
    # k × sigma mónico (mismas raíces, misma decodificación). Si se
    # pasan los coeficientes de referencia (``sigma_ref``), la
    # comparación se hace en forma mónica y la escala k no importa;
    # si no, se compara el hash directo (la vía antigua). ``sigma_scale``
    # registra la k medida (informativo, lo calcula el productor).
    sigma_ref: list[int] | None = None
    sigma_scale: int | None = None
    c_restored: int = 0
    b_restored: int = 0
    total_coef: int = 0
    dreg_zero: bool = False
    alpha_zero: bool = False
    temporaries_zero: int = 0
    temporaries_total: int = 0
    allowed_dirty: dict[str, str] = field(default_factory=dict)
    shots: int = 0
    verified_by: str = ""

    def sigma_hash(self) -> str | None:
        if self.sigma is None:
            return None
        return canonical_hash(self.sigma)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "sigma_hash": self.sigma_hash(),
            "sigma_ref_hash": self.sigma_ref_hash,
            "sigma_ref": list(self.sigma_ref) if self.sigma_ref is not None else None,
            "sigma_scale": self.sigma_scale,
            "c_restored": self.c_restored,
            "b_restored": self.b_restored,
            "total_coef": self.total_coef,
            "dreg_zero": self.dreg_zero,
            "alpha_zero": self.alpha_zero,
            "temporaries_zero": self.temporaries_zero,
            "temporaries_total": self.temporaries_total,
            "allowed_dirty": dict(self.allowed_dirty),
            "shots": self.shots,
            "verified_by": self.verified_by,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "IntegrityEvidence":
        sigma = d.get("sigma")
        sigma_ref = d.get("sigma_ref")
        return cls(
            kind=d.get("kind", "projection"),
            sigma=list(sigma) if sigma is not None else None,
            sigma_ref_hash=d.get("sigma_ref_hash") or d.get("sigma_hash"),
            sigma_ref=list(sigma_ref) if sigma_ref is not None else None,
            sigma_scale=d.get("sigma_scale"),
            c_restored=int(d.get("c_restored", 0)),
            b_restored=int(d.get("b_restored", 0)),
            total_coef=int(d.get("total_coef", 0)),
            dreg_zero=bool(d.get("dreg_zero", False)),
            alpha_zero=bool(d.get("alpha_zero", False)),
            temporaries_zero=int(d.get("temporaries_zero", 0)),
            temporaries_total=int(d.get("temporaries_total", 0)),
            allowed_dirty=dict(d.get("allowed_dirty", {})),
            shots=int(d.get("shots", 0)),
            verified_by=str(d.get("verified_by", "")),
        )


class IntegrityViolation(Exception):
    """El candidato rompió la integridad lógica. Falla cerrada."""

    def __init__(self, reasons: list[str]):
        self.reasons = list(reasons)
        super().__init__("; ".join(reasons))


class IntegrityFilter:
    """Filtro de integridad obligatorio para candidatos con circuito.

    Reglas (todas deben pasar):
    1. La evidencia existe y es de kind "circuit" (un "projection"
       NUNCA pasa este filtro: solo puede aspirar a mejor proyectado).
    2. El hash del sigma coincide con el hash de referencia.
    3. C y B restaurados por completo (c_restored == b_restored ==
       total_coef, y total_coef > 0).
    4. dreg y alpha en cero.
    5. Temporales en cero, salvo los listados en allowed_dirty (cada
       uno con su motivo no vacío).

    ``check`` devuelve (pasó, [motivos]). ``require`` lanza
    IntegrityViolation si no pasa.
    """

    def check(self, evidence: IntegrityEvidence | dict[str, Any] | None
              ) -> tuple[bool, list[str]]:
        if evidence is None:
            return False, ["sin evidencia de integridad"]
        if isinstance(evidence, dict):
            evidence = IntegrityEvidence.from_dict(evidence)
        reasons: list[str] = []
        if evidence.kind != "circuit":
            reasons.append(
                f"kind={evidence.kind!r}: sin circuito no hay integridad "
                "que verificar (solo proyección)")
            return False, reasons
        got = evidence.sigma_hash()
        if evidence.sigma is None:
            reasons.append("falta el sigma medido")
        elif evidence.sigma_ref is not None:
            # Vía consciente de escala (paso 51 v3): se comparan las
            # formas mónicas. Un hash directo fallaría aunque el
            # circuito sea correcto (sigma = k × mónico).
            try:
                monic_got = _monic(evidence.sigma)
                monic_ref = _monic(evidence.sigma_ref)
            except ValueError as e:
                reasons.append(f"sigma no normalizable a mónico: {e}")
            else:
                if canonical_hash(monic_got) != canonical_hash(monic_ref):
                    reasons.append("SIGMA_DIVERGENCE: el sigma (forma "
                                   "mónica) no coincide con la referencia")
                elif _scale_factor(evidence.sigma, evidence.sigma_ref) is None:
                    reasons.append("SIGMA_DIVERGENCE: el sigma no es un "
                                   "múltiplo escalar de la referencia")
        elif evidence.sigma_ref_hash is None:
            reasons.append("falta el hash del sigma de referencia")
        elif got != evidence.sigma_ref_hash:
            reasons.append("SIGMA_DIVERGENCE: el hash del sigma no "
                           "coincide con la referencia")
        if evidence.total_coef <= 0:
            reasons.append("total_coef debe ser > 0")
        else:
            if evidence.c_restored != evidence.total_coef:
                reasons.append(
                    f"C restaurado {evidence.c_restored}/{evidence.total_coef}")
            if evidence.b_restored != evidence.total_coef:
                reasons.append(
                    f"B restaurado {evidence.b_restored}/{evidence.total_coef}")
        if not evidence.dreg_zero:
            reasons.append("dreg no terminó en cero")
        if not evidence.alpha_zero:
            reasons.append("alpha no terminó en cero")
        dirty = (evidence.temporaries_total - evidence.temporaries_zero
                 - len(evidence.allowed_dirty))
        if dirty > 0:
            reasons.append(
                f"{dirty} temporales sucios sin documentar")
        for name, why in evidence.allowed_dirty.items():
            if not str(why).strip():
                reasons.append(
                    f"temporal sucio {name!r} sin motivo documentado")
        if evidence.shots <= 0:
            reasons.append("shots debe ser > 0")
        return (not reasons), reasons

    def require(self, evidence: IntegrityEvidence | dict[str, Any] | None
                ) -> None:
        ok, reasons = self.check(evidence)
        if not ok:
            raise IntegrityViolation(reasons)


class CircuitConstructionGuard:
    """Envuelve la CONSTRUCCIÓN de un circuito con el filtro.

    ``build_fn`` es la función que construye el circuito y devuelve
    ``(artefacto, evidencia)``. El guardia ejecuta la construcción,
    revisa la evidencia y, si falla, NO devuelve el artefacto: lanza
    IntegrityViolation. Si pasa, devuelve (artefacto, evidencia).

    Así el filtro atrapa un paso 51 aunque el candidato nunca pase
    por el lazo de búsqueda: la construcción misma está vigilada.
    Uso como decorador o como contexto (``with guard: ...`` no
    construye nada por sí solo; el decorador es el camino principal).
    """

    def __init__(self, integrity: IntegrityFilter | None = None):
        self.filter = integrity or IntegrityFilter()

    def __call__(self, build_fn: Callable[..., tuple[Any, Any]]):
        def wrapped(*args: Any, **kwargs: Any):
            artifact, evidence = build_fn(*args, **kwargs)
            self.filter.require(evidence)
            return artifact, evidence
        wrapped.__name__ = getattr(build_fn, "__name__", "build")
        wrapped.__doc__ = getattr(build_fn, "__doc__", None)
        return wrapped

    def guard(self, build_fn: Callable[..., tuple[Any, Any]], *args: Any,
              **kwargs: Any) -> tuple[Any, Any]:
        return self(build_fn)(*args, **kwargs)

"""AUTO_MVP v2.12 — el ROL CAUSAL de cada operador: ¿causa o indicador?

La idea viene de un script de demostración (modelo de evidencia A y
causas latentes, 3 mundos sintéticos con ground truth conocido). Su
lección es: una correlación alta no dice si un candidato ES causa o
solo INDICA la causa. En el mundo "proxy_indicator" la correlación
entre la señal A y el efecto E es 0.82 (alta), pero intervenir sobre
A apenas mueve E (do(A)=0.10) mientras que la causa latente Z lo
mueve mucho (do(Z)=0.93): A es solo un indicador. En "direct_cause"
la correlación es 0.99 y do(A)=0.75: A sí es causa. En "mixed" ambos
contribuyen (do(A)=0.40, do(Z)=0.77). Los tres mundos tienen
correlación alta: solo la intervención (do) distingue cuál es cuál.

Esa lección es exactamente la disciplina de medición de la
herramienta. Cada operador es un candidato A: su "señal" visible es
lo que quita o limpia (compuertas removidas), y su "efecto" es el
puntaje S. El driver latente Z es el conteo de Toffolis (el S depende
de T: DQI S = R×Q²×T, invsqrt S = Q×C con C contando Toffolis). El
benchmark YA hace intervenciones: corre el operador (do(operador))
y mide S con el verificador oficial. Así que el delta_S del benchmark
ES un efecto do, no una correlación. Y lo que se ha medido es que
ningún operador mueve S en la semilla ni en el DQI: el peephole quita
122 Clifford (198 con conmutación) y el S no se mueve, porque solo
toca Clifford, no Toffolis. Es el mundo "proxy_indicator": mucha
señal, ningún efecto causal sobre el puntaje.

Este módulo formaliza esa clasificación sobre los datos MEDIDOS del
benchmark (nunca sobre la correlación "quité N compuertas"):

- classify_causal_role(candidate_effect, latent_effect, threshold):
  el clasificador general del script (misma lógica, mismo umbral):
  con los efectos do conocidos, dice si el candidato es causa
  directa, indicador, mixto o indeterminado. Los 3 mundos sintéticos
  del script son su test de ground truth.
- classify_operator_role(removed, delta_toffoli, delta_S): aplica
  ese razonamiento a un operador medido en el benchmark. Señal =
  quitó compuertas; causa = mejoró el S (delta_S < 0, medido por
  intervención); driver = movió los Toffolis (delta_toffoli < 0).
- select_minimum_action(options, target_gain): la regla del script
  (la opción de menor costo que alcanza la ganancia objetivo, o None
  si ninguna llega). Los costos y ganancias son los MEDIDOS, no
  didácticos: el costo es el tiempo de corrida del operador y la
  ganancia es -delta_S (o -delta_toffoli para DQI).
- classify_benchmark(report, costs, target_gain): clasifica todos
  los operadores de un reporte de benchmark y recomienda la acción
  mínima para una ganancia objetivo.

Hallazgo al analizar el script: el JSON que venía pegado con él NO
lo produce este script (tiene "minimum_action_selected" como texto
y sin "A_observed_evidence_vector" ni warning por escenario; el
script produce "minimum_action_demo" como dict, con el vector y el
warning por escenario). Los NÚMEROS sí coinciden (correlaciones
0.8179/0.9934/0.9344, do 0.10/0.75/0.40 y 0.93/0.08/0.77, roles y
acciones mínimas iguales). El JSON es de otra versión del script
(0.3-demo); el script pegado es esa misma versión en lógica pero
con otra estructura de salida.
"""
from __future__ import annotations

from typing import Any

ROLE_THRESHOLD = 0.20  # umbral didáctico, en unidades normalizadas

# Los cuatro roles, en las palabras del script.
ROLE_DIRECT = "el candidato tiene efecto causal directo apreciable"
ROLE_INDICATOR = "el candidato funciona principalmente como indicador"
ROLE_MIXED = "mixto: candidato y causa latente contribuyen"
ROLE_UNDETERMINED = "indeterminado con este umbral"


def classify_causal_role(effect_of_candidate: float,
                         effect_of_latent_cause: float,
                         threshold: float = ROLE_THRESHOLD) -> str:
    """Clasifica un candidato con sus efectos do conocidos.

    Es el clasificador del script de demostración (misma lógica):
    requiere los efectos causales (do), no una correlación. En datos
    reales esos efectos no salen de una correlación simple: requieren
    un diseño causal, intervención, experimento natural u otros
    supuestos. Aquí la intervención es correr el operador y medir S
    con el verificador (el benchmark ya lo hace).
    """
    candidate_acts = abs(effect_of_candidate) >= threshold
    latent_acts = abs(effect_of_latent_cause) >= threshold
    if candidate_acts and latent_acts:
        return ROLE_MIXED
    if candidate_acts:
        return ROLE_DIRECT
    if latent_acts:
        return ROLE_INDICATOR
    return ROLE_UNDETERMINED


def select_minimum_action(options: list[dict[str, Any]],
                          target_gain: float) -> dict[str, Any] | None:
    """La opción de menor costo que alcanza una ganancia objetivo.

    Cada opción lleva `name`, `cost` y `expected_gain`. Es la regla
    del script (ahí se llamaba `select_minimum_action` con
    `expected_integrity_gain`); aquí la ganancia es la MEDIDA
    (-delta_S, o -delta_toffoli para DQI) y el costo es el tiempo
    de corrida MEDIDO. Si ninguna opción llega a la ganancia, es
    None: la respuesta honesta es que nada de lo medido lo logra.
    """
    eligible = [o for o in options if o["expected_gain"] >= target_gain]
    if not eligible:
        return None
    return min(eligible, key=lambda o: o["cost"])


def classify_operator_role(removed: int, delta_toffoli: int | None,
                           delta_S: float | None) -> str:
    """El rol de un operador, con sus valores MEDIDOS en el benchmark.

    - removed: compuertas que quitó (su señal visible).
    - delta_toffoli: cambio en Toffolis (negativo = los bajó; None
      si la tarea no los mide).
    - delta_S: cambio en el S oficial (negativo = mejoró el puntaje;
      None si la tarea no lo mide).

    La lógica es la del script, con el driver latente Z = Toffolis:
    - Mejora el S moviendo los Toffolis -> causa directa.
    - Mejora el S sin mover los Toffolis -> mixto (otro camino,
      p. ej. bajó Q).
    - Quita compuertas pero no mueve ni S ni Toffolis -> indicador
      (limpia, pero el puntaje lo mueven los Toffolis, que no toca).
    - No quita nada y no mueve nada -> indeterminado.
    """
    signal = removed > 0
    improves_S = delta_S is not None and delta_S < 0
    moves_driver = delta_toffoli is not None and delta_toffoli < 0
    if improves_S and moves_driver:
        return ROLE_DIRECT
    if improves_S and not moves_driver:
        return ROLE_MIXED
    if signal and not improves_S:
        return ROLE_INDICATOR
    return ROLE_UNDETERMINED


def classify_benchmark(report: dict[str, Any],
                       costs: dict[str, float] | None = None,
                       target_gain: float = 0.0) -> dict[str, Any]:
    """Clasifica los operadores de un reporte de benchmark.

    `report` es lo que devuelve `benchmark()` (o su JSON). `costs`
    es el tiempo de corrida medido por operador (segundos); si no se
    da, todos cuestan 1.0 (la mínima acción solo ordena por ganancia).
    `target_gain` es la mejora de S (o de Toffolis en DQI) que se
    quiere alcanzar. Devuelve el rol de cada operador y la acción
    mínima para esa ganancia (o None si ningún operador medido llega).
    """
    costs = costs or {}
    roles: dict[str, str] = {}
    options: list[dict[str, Any]] = []
    for name, op in report.get("operators", {}).items():
        if name == "fanout":
            # El fan-out es una medición de potencial, no una
            # reescritura: su rol es el de su potencial.
            potential = op["stats"].get("total_potential_T", 0)
            roles[name] = (ROLE_INDICATOR if potential == 0
                           else ROLE_MIXED)
            options.append({"name": name, "cost": costs.get(name, 1.0),
                            "expected_gain": float(potential)})
            continue
        if name == "sa_windows" and op.get("valid") is None:
            roles[name] = ROLE_UNDETERMINED
            continue
        stats = op.get("stats", {})
        removed = int(stats.get("removed", 0))
        # La conmutación reporta "removed" igual que el peephole.
        roles[name] = classify_operator_role(
            removed, op.get("delta_toffoli"), op.get("delta_S"))
        # La ganancia es la mejora de S; si la tarea no mide S (DQI),
        # es la mejora en Toffolis.
        gain = op.get("delta_S")
        if gain is None:
            gain = op.get("delta_toffoli")
        options.append({"name": name, "cost": costs.get(name, 1.0),
                        "expected_gain": (float(-gain) + 0.0
                                          if gain is not None else 0.0)})
    action = select_minimum_action(options, target_gain)
    return {"roles": roles,
            "minimum_action": {
                "target_gain": target_gain,
                "selected_option": action["name"] if action else None,
                "selected_cost": action["cost"] if action else None,
                "options": options,
            }}

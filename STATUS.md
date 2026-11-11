# STATUS.md — estado del repo (v0.6.0, 2026-11-11)

## Qué está integrado (verificado con números)

- **v0.6.0 — capa de adaptación dinámica.** La formalización
  algorítmica es Qualtran (Bloqs, grafo de llamadas, T/Q de primera
  clase). `qualtran_bridge.py` (puente verificado contra Qualtran
  0.7.0 real: Toffoli T=4 Q=3; Add(QUInt(4)) T=12 Q=8, And 3+3 +
  CNOT 15), `morph_tunnel.py` (tunelamiento MORPH sobre el grafo:
  reglas con evidencia medida — Chien→Montgomery b=17, T 1,511,522
  → 1,315,731; Toom-3→Toom-4, S 1.99836e13 → 1.923348e13),
  `json_directive.py` (decodificador JSON en lenguaje natural,
  vocabulario controlado), `step_plan.py` (plan de pasos
  reprogramable en caliente, con log), `orchestrator.py`
  (AdaptiveOrchestrator: lee JSON, reordena, adapta en caliente).
  Tests 20/20 nuevos; suite completa 70/70.
- **v0.5.0** — meta_mvp absoluto, ventaja pura, Lab (numeric_lab +
  fail-closed), LOGIC_CORE MWIS. Notebook Kaggle v0.5.0 (versión 2,
  kernel 144474964, privado, complete, números idénticos local/Kaggle).
- **Mejor envío vigente: 23.94667** (ref 58076483). La meta 30.00
  sigue sin alcanzarse con el enfoque actual (veredicto 2026-11-11).

## Lo que Qualtran NO cubre (dicho con el dato, no recortado)

- **Equivalencia entre Bloqs.** Qualtran NO demuestra que dos
  Bloqs sean funcionalmente iguales. La equivalencia de un
  reemplazo (tunelamiento) viene de la verificación MEDIDA que
  nombra la evidencia de cada regla (cost_model exacto, verificador
  oficial 102,400 shots), nunca de Qualtran.
- **El circuito DQI como Bloq.** El circuito DQI de la competencia
  es un circuito kickmix, no un Bloq de Qualtran. El puente opera
  sobre Bloqs de Qualtran y sobre grafos de llamadas construidos
  desde el cost_model; convertir el DQI kickmix completo a un Bloq
  es una tarea aparte, no hecha aquí.
- **El "lenguaje natural" es un vocabulario controlado**, no NLP
  libre: las directivas se parsean con reglas deterministas. Lo que
  no encaja se devuelve como no parseado (con el motivo) y el
  orquestador lo registra; nunca se descarta en silencio.

## Lo que quedó sin cablear (reportado, no silenciado)

- **Paso "search" del plan:** la búsqueda de mutaciones vive en
  `vqcc/search.py` (SearchLoop); no es un paso por candidato del
  orquestador. El orquestador lo marca como "sin implementar" en el
  log de pasos cuando aparece en un plan.
- **Tensor TERM_U con atractor y entrenamiento algebraico
  implícito** (fase 3 de la spec AUTO_MVP v0.0.1): sin fórmula ni
  algoritmo definidos; no se construyeron.
- **state_regulator y quantum_circuit_optimizer** (v0.5.0): solo a
  nivel de mecanismo (su histéresis/gobernanza y su idea de dos
  velocidades ya viven en el pipeline); no se incorporaron como
  código.

## Reglas vigentes

- Repo PRIVADO (VQCC oculto mientras la competencia esté abierta).
- Números medidos (baseline vs optimizado); nada se afirma sin medir.
- Nada a Kaggle sin que Arturo lo pida (el notebook v0.5.0 ya está
  subido y verificado; v0.6.0 NO se subió a Kaggle en este turno).
- MORPH solo lee bitstrings DESPUÉS del flujo (MIS); la gobernanza
  y los vetos viven en el lazo de búsqueda, no en MORPH.

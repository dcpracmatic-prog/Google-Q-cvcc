# STATUS.md — estado del repo (v1.0.0, 2026-11-11)

## Qué está integrado (verificado con números)

- **v1.0.0 — la guía: el mejor por tarea, entre corridas.** El
  auto-optimizador es una GUÍA, no un compilador ni un validador.
  Un ledger persistente (`runs/best_per_task.json`) guarda el mejor
  componente por tarea ENTRE corridas (solo mejora; cada reemplazo
  queda en el historial con su procedencia: corrida, iteración,
  medido o proyectado). Dado un objetivo (ej. 30.00), `combine_best`
  dice si la combinación llega y cuánto le falta a CADA tarea (el
  DQI necesitaría S 1.9162e11, 127.3x; el invsqrt, S 51,149). Cuando
  llega, exporta la base de auditoría en un ZIP
  (`audit-base-<gm>.zip`) con los tres componentes y un
  manifest.json con su procedencia. Con la semilla (el mejor envío,
  GM 23.94676), 30.00 no se alcanza; con un DQI mejor (S 2.0e11)
  en una corrida y un invsqrt mejor (S 50,000) en otra, la
  combinación llega a GM 37.33. El pipeline alimenta el ledger al
  promover y exporta la base cuando la combinación llega al
  objetivo. Operación nueva en la Skill: `combine_best`
  (9 operaciones). Tests 6/6 nuevos; suite completa 110/110.
- **v0.9.1 — la síntesis de rotaciones en el costo invsqrt
  (fail-closed).** El proxy ya no ignora el costo de síntesis de
  rotaciones Z_POW finas: la fórmula es la del verificador oficial
  (`rotation_t_count(eps) = 0.56*log2(1/eps) + 5.3`, idéntica a la
  del verificador, verificada contra su archivo). El eps sale del
  margen de tolerancia que deja la aproximación (cota inferior
  `(2^-24 - rel_error) / sqrt(3,133,452)`; el e1 sale de la tabla
  del Lab cuando el candidato trae grado/segmentos). Con 37
  rotaciones y el e1 del mejor prefiltro, la referencia da
  S 2,077,168.5, a 0.019% del S oficial 2,076,774 (sin la síntesis
  daría 2,011,100, un 3.2% por debajo). Rotaciones sin rel_error,
  o rel_error >= 2^-24, se rechazan (fail-closed). El module.py
  exportado usa la misma fórmula. Sin rotaciones, la fórmula es
  la de siempre. Tests 7/7 nuevos; suite completa 104/104.
- **v0.9.0 — formato del submission.zip y su validador
  (fail-closed).** El formato oficial ahora vive en el repo
  (`auto_mvp/packaging.py`, SPEC_AUTO_MVP.md, PIPELINE.md), no
  solo en memoria (la v0.3.0 falló por duplicados en otras rutas).
  `validate_submission_zip` / `validate_submission_dir` comprueban
  rutas exactas, sin directorio raíz extra, sin duplicados, un
  solo invsqrt y un solo dqi, angle_k consecutivos desde 0 sin
  huecos, submission.npz con las 6 claves. `build_submission_zip`
  arma el ZIP y lo BORRA si no pasa. `submission_ready` da READY
  solo si la puerta fail-closed Y el formato pasan. El validador
  revisa el FORMATO, no el contenido. Operación nueva en la Skill:
  `validate_submission` (8 operaciones). Verificado con ZIPs
  reales: el válido pasa; cada desviación falla con su motivo.
  Tests 9/9 nuevos; suite completa 97/97.
- **v0.8.0 — dataset de trabajo (exportar e inyectar módulos).**
  El fail-closed sigue intacto para el submission.zip final, pero
  un módulo promovido ya no se queda en un manifiesto con métricas
  frías: cada promoción exporta e inyecta su estructura completa y
  su código ejecutable al dataset de trabajo
  (`<runs_dir>/dataset/<nombre>/`): `structure.json` (grafo
  completo), `module.py` (solo stdlib, recomputa S y GM) y
  `source/...` (el constructor, cuando el candidato lo trae). El
  índice `dataset/index.json` lista los módulos inyectados y
  `WorkingDataset.load` los carga por nombre. Verificado: el
  module.py exportado de Montgomery reproduce S 3.2331e12 y GM
  11.697 en un proceso limpio; el cargador devuelve el grafo
  tunelado (T 1,315,731, no el base 1,511,522). Operación nueva en
  la Skill: `export_module` (7 operaciones). Tests 7/7 nuevos;
  suite completa 88/88.
- **v0.7.0 — Skill / Tool nativa para LLMs (extra, no reemplazo).**
  El sistema sigue corriendo solo como antes, y además cualquier
  LLM puede invocarlo como herramienta: `skills/auto-mvp-vqcc/`
  (SKILL.md formato Agent Skills, mcp_server.py stdio solo stdlib
  para Claude, tools.py + functions.json para ChatGPT Code
  Interpreter y Grok, references/install.md por entorno y
  references/operations.md). Punto de entrada único:
  `auto_mvp/operations.py` + CLI (`python -m auto_mvp.cli`).
  Verificado: la skill en sandbox reproduce los números del repo
  (gate 30 -> 127.335; evaluate Montgomery -> S 3.2331e12, GM 11.697;
  tunnel -> T 1,511,522 -> 1,315,731; run -> promovido 1, tunelado 1;
  pip install desde el repo funciona). Tests 11/11 nuevos; suite
  completa 81/81.
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

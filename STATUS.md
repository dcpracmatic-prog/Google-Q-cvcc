# STATUS.md — estado del repo (v2.1.0)

Última actualización: 2026-11-12. Todo lo que dice aquí está
verificado en sandbox y/o en Kaggle; lo que no, dice que no.

## Versión

- **v2.1.0** (2026-11-12): verificación rápida para las TRES tareas
  con el protocolo oficial. `fast_verify_dqi` (hash desde el
  archivo .kmb, 2,048 shots, ~37 s) y `fast_verify_dfthcsos`
  (~28 s, reproduce el S de referencia exacto). Los 3 generadores
  y los 3 verificadores oficiales vendidos en
  `auto_mvp/circuits/` (el fcidump de 128 MB viene del dataset en
  runtime, no del repo).
- **v2.0.0** (DIRECTIVA v2.0 de Arturo, 2026-11-11 23:47 CST):
  fuerza bruta sobre CIRCUITOS. `auto_mvp/circuit.py` (cargar,
  contar, verificación rápida con el protocolo oficial, proponer
  con sa_windows) + `auto_mvp/circuit_auto.py` (corredor:
  proponer → validar → medir → repetir). Semilla, operador y
  verificador vendidos en `auto_mvp/circuits/`.
- Suite de tests: ver la última corrida en sandbox
  (`pytest tests/`). La v1.5.0 pasó 154/154.

## Verificado (v2.1)

- La verificación rápida reproduce el S certificado de la semilla
  invsqrt: S=100,556.7 (max_x=256) y S=100,585.4 (max_x=1024) vs
  certificado 100,568.5 (0.01–0.02% de error), en ~0.1 s, con el
  protocolo oficial (mismo chequeo, menos shots).
- **DQI** (`fast_verify_dqi`, 2,048 shots, ~37 s): la semilla V1
  (dqi_v1_logm7.kmb, Q=1888) pasa con eps+ = 0.0424, 0 errores,
  T = 5,708,467.7. La referencia (dqi.kmb, Q=1893) también pasa,
  0 errores. Con 256 shots el verificador oficial ABORTA aunque
  haya 0 errores (eps+ = 0.2929 > 1/16): el mínimo es 2,048 shots.
- **DQI, el hash**: el verificador oficial no puede hashear un
  circuito tamaño DQI en el venv de sandbox (`to_file` a .kmb
  falla siempre; no es memoria ni disco). La verificación rápida
  hashea desde el ARCHIVO .kmb, y ese hash ES el canónico
  (sha256 de dqi_v1_logm7.kmb = a260f79a..., el hash oficial del
  v1-verify). Para un .kmx se hashea el archivo .kmx (el hash
  solo elige qué casos de prueba se sortean). La certificación
  final de un ganador corre el verificador oficial completo
  (en Kaggle, donde el hash sí funciona).
- **Química** (`fast_verify_dfthcsos`, ~28 s): reproduce el S de
  referencia exacto (3,355,599,588.3) sobre el sample_submission.
  El sample_submission puntúa EN la referencia: es el ejemplo,
  no la pública (la pública es S = 326,800,029.87). El fcidump
  (128 MB) se enlaza desde el dataset en runtime; el
  fixed_shifts.npz (61 KB) sí está vendido en el repo.
- kickmix mide la semilla: 62 cúbits, 47,258 instrucciones,
  1,495 Toffoli-like estáticos (la media por shot es 1,325.48).
- Un circuito con un CCX cambiado de objetivo es INVÁLIDO (la
  verificación oficial lo rechaza) y un .kmx truncado también.
  La validez es el filtro: lo inválido no cuenta.
- sa_windows sobre invsqrt_pub: ganancia 0 (barrido completo K=5,
  151 ventanas, 5,119 s, 2026-11-09). La semilla ya es óptima para
  esas ventanas: el corredor propondrá y seguirá buscando, y eso
  es medido, no un fallo.
- El corredor v2.0 con 2 propuestas termina, guarda el mejor CON
  SU CIRCUITO (`runs/best/invsqrt.kmx`) y el ledger
  (`runs/circuit_ledger.json`).

## Límite honesto (lo que NO es, v2.1)

- v2.1 mide las TRES tareas con el protocolo oficial, pero el
  corredor (`circuit_auto.py`) solo corre **invsqrt** de punta a
  punta. Falta extenderlo a DQI y química con sus operadores de
  propuesta: sa_windows trabaja sobre .kmx (texto) y el DQI no se
  puede convertir de .kmb a .kmx en sandbox (el mismo fallo de
  `to_file` que impide el hash); la propuesta DQI tendrá que venir
  de mutar el GENERADOR (dqi_reference_circuit.py / el builder
  BM+Forney) y reconstruir, no de reescribir un .kmb.
- El S rápido de DQI es CONSERVADOR: con 2,048 shots el eps+
  (0.0424) infla R (~7.5) frente al certificado a 102,400 shots
  (R = 1.19). Dos candidatos se comparan con los MISMOS shots,
  así que el ranking lo decide Q²×T, que es lo que importa; la
  certificación final es el verificador oficial completo.
- Cada propuesta sa_windows tarda ~30 s o más (una ventana) y el
  barrido completo K=5 tardó 85 min. La búsqueda es lenta por
  diseño: es fuerza bruta sobre circuitos, no sobre números.
- El corredor v1.x (GM 30.0056) optimizaba **métricas y grafos de
  costos**, no circuitos. Su éxito era tautológico por diseño.
  **No mide nada real.** Se mantiene por compatibilidad, superado
  por la DIRECTIVA v2.0.
  no la receta para construir un .kmb. Un .kmb es una lista
  ordenada de compuertas sobre registros nombrados; no se puede
  construir desde (Q=740, T=429,936).
- El mutador usa los nombres de las herramientas de Arturo
  (morph, ventana SA, Lévy, MWIS) sobre un árbol de costos.
  sa_windows y DialogTraceEngine no están en el repo. MWIS/MaxCut
  operan sobre el grafo de conflictos de mutaciones, no de
  cúbits/compuertas. El Observer no se instancia en `run_auto`.
  FIELD/Dijkstra no está en el flujo del corredor.
- La optimización real solo existe donde hay circuito construido
  y medido (DQI BM+Forney en sandbox, invsqrt v1 certificado,
  factorización química medida).

## Pendiente (decisión de Arturo)

- Extender el corredor a DQI y química (v2.1 mide las tres, pero
  solo invsqrt corre de punta a punta): falta el operador de
  propuesta DQI (mutar el generador y reconstruir) y el de
  química (factorización + angles), más la semilla química
  pública (su .npz no está en el sample_submission).
- La decisión pendiente de 2026-11-11 sobre los 2 PDFs borrados
  por el commit c7dbb058 sigue abierta.

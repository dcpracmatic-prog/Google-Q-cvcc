# STATUS.md — estado del repo (v2.5.0)

Última actualización: 2026-11-12. Todo lo que dice aquí está
verificado en sandbox y/o en Kaggle; lo que no, dice que no.

## Versión

- **v2.5.0** (2026-11-12): INNOVAR, PROBAR, AUDITAR (directiva de
  Arturo 2026-11-12 22:04 CST). Dos piezas:
  - **ROTATION_MERGE** (`auto_mvp/circuits/operators/rotation_merge.py`):
    fusión de Z_POW a través de compuertas que conmutan (X con cambio
    de signo, control de CX, diagonales, SWAP). En la semilla invsqrt:
    **0 fusiones, negativo medido** (los 68 Z_POW están aislados).
    La auditoría encontró DOS bugs reales y los corrigió: (1) las
    Z_POW condicionales (20) entraban en la pendiente incondicional
    e invalidaban el circuito; (2) los ángulos por float (repr con
    notación científica que el parser rechaza, y ~1e-16 de pérdida
    que movía el S 4.7e-04) — ahora Decimal EXACTO prec=100, S
    idéntico, válido, idempotente. El peephole (v2.4) tenía el mismo
    bug latente en su fusión y se corrigió igual.
  - **REPORT** (`auto_mvp/report.py`): el reporte estructurado de
    una corrida — cuantitativo (propuestas, válidas, mejor S,
    ganancia, peephole, prefilter, modelo) y cualitativo (comentario
    en simple generado por reglas, no inventado). Corrida de prueba
    en `notes/v2.5.0-run.md`: 3 propuestas, 3 válidas, ganancia 0,
    peephole 132, prefilter 15 descartados, modelo sin llave. La
    nota de versión está en `notes/v2.5.0.md`.
- **v2.4.0** (2026-11-12): LA HERRAMIENTA, con lo que sirve de lo
  revisado (directiva de Arturo 2026-11-12 01:56 CST: crear la
  herramienta en GitHub, usar lo que sirva, que trate de dar mejores
  resultados). Dos piezas nuevas, ambas hechas BIEN (sobre los
  formatos reales, verificadas contra lo oficial):
  - **PEEPHOLE** (`auto_mvp/circuits/operators/peephole.py`): la
    ruta Fast de GUOQ (especificación Capa 3) — fusión de Z_POW
    adyacentes + cancelación de pares Clifford idénticos, con
    reescrituras EXACTAS sobre el .kmx real. En la semilla invsqrt
    quita 44 compuertas (18 pares CX + 4 X) y el S medido NO cambia
    (las Clifford no cuentan en C); la validez la confirma el
    verificador oficial (S idéntico 100,585.37). Integrado como
    pre-paso determinista de `propose_sa_windows` (la receta
    (K, seed) sigue reconstruyendo lo mismo).
  - **DIALOG** (`auto_mvp/circuits/dialog.py`): la traza algebraica
    (cocientes del EEA) + playback reconstruyen los coeficientes de
    Bézout sin haberlos guardado. 200/200 casos aleatorios: el
    playback es idéntico al EEA explícito (completo y ecuación
    clave), y sigma·S = omega (mod z^2l). Los scripts
    quantum_circuit_optimizer v1-v3 NO implementan esto (su
    "Dialog" es un playback de vector de estado con matrices 2x2
    que no representan las compuertas de varios qubits). Veredicto
    para OPI: en GF(2^b) con n<<m gana el EXPLÍCITO (Chien con QC
    es Clifford, gratis); Dialog gana solo en campos primos o si
    el EEA domina. La U-Net (Capa 2) y el GUOQ Slow (Capa 3) de la
    especificación siguen sin existir: la U-Net necesita datos de
    entrenamiento etiquetados (qué regiones son reducibles) que no
    existen; el Slow es sa_windows, que ya está.
- **v2.3.0** (2026-11-12): el PREFILTRO (directiva de Arturo
  2026-11-12 00:56 CST): el modelo propone un LOTE de deltas por
  ronda, el proxy (puerta, no producto) los ordena en milisegundos
  con su margen calibrado, MWIS elige un hueco caro por target, y
  solo 1-2 ganan el paso caro (construir + medir con kickmix).
  `auto_mvp/prefilter.py` + `auto_mvp/circuits/cost_models/dqi_cost.py`
  (el modelo de costos DQI vendido fiel: reproduce EXACTOS los 4
  decodificadores medidos 63/51/45/42T y el Toom-4+V1+E2 medido en
  Kaggle Q=1,899 T=4,477,394 S=1.923348e13). Sin historial el proxy
  no tiene señal: se explora con el mejor estimado y la medición
  CREA el historial. Aceleradores nativos MEDIDOS (no supuestos):
  cargan bien (spmm/field/swar), pero a estos tamaños Python gana:
  Dijkstra nativo 59.2 ms vs Python 4.2 ms (14x) Y devuelve una
  distancia MAL en 1/1000 nodos (236 vs 232); SpMM nativo 4.4 ms vs
  Python 1.67 ms (2.6x) con precisión float32 (diff máx 2.4e-07).
  Conclusión: en v2.3 las decisiones NO pasan por los nativos; se
  usa Python (correcto y más rápido a estos tamaños) y los nativos
  quedan para trabajo más grande, cuando se mida que ganan.
- **v2.2.0** (2026-11-12): modelo de lenguaje GRATIS (Gemini por
  defecto, Groq de respaldo) como estratega + el Notebook saca
  SOLO SEMILLAS (JSON de kilobytes, nunca .kmx). `auto_mvp/llm.py`
  (cliente compatible OpenAI, solo stdlib, llave por entorno),
  `auto_mvp/seed.py` (formato semilla por tarea) y
  `auto_mvp/llm_auto.py` (corredor: el modelo propone K y seed, el
  operador construye en temporal y se borra, el verificador decide).
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

## Verificado (v2.2)

- El modelo de lenguaje es el ESTRATEGA: propone K y seed como
  JSON chico, nunca compuertas. Sin llave, con 429 o con JSON
  malo, el corredor sigue con sa_windows (K rotando): la corrida
  nunca depende del modelo.
- **Solo salen semillas.** El circuito vive solo en temporal y se
  borra al terminar la ronda; en `runs/` quedan solo
  `seeds/<tarea>/<id>.json` (kilobytes) y el ledger. Los tests lo
  comprueban: después de correr, no hay ningún .kmx en `runs/`.
- **La semilla se reconstruye.** Re-correr sa_windows con los
  mismos (K, seed) da el mismo circuito (test de determinismo:
  misma ganancia y mismos bytes). Al arrancar, el corredor
  reconstruye la mejor semilla desde su cadena de padres y la
  MIDE: si el S no coincide (1%), vuelve a la base y lo dice.
- **Gratis y bueno (medido en la documentación pública,
  octubre-noviembre 2026):** Gemini Flash gratis, sin tarjeta
  (el nivel gratis más generoso por capacidad); Groq gratis
  (gpt-oss-120b: 30/min, 1,000/día, 200K tokens/día). La llave
  NUNCA va en el repo: entorno (`GEMINI_API_KEY` / `GROQ_API_KEY`)
  o secreto de Kaggle. Los límites cambian: se vuelven a mirar en
  la consola del proveedor antes de depender de ellos.

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

## Límite honesto (lo que NO es, v2.2)

- v2.2 mide las TRES tareas con el protocolo oficial y el corredor
  con modelo corre invsqrt de punta a punta, pero DQI y química
  siguen sin materializador: tienen su formato de semilla, pero
  falta el operador de propuesta DQI (mutar el generador y
  reconstruir) y el de química (entrenar la factorización).
- El S rápido de DQI es CONSERVADOR: con 2,048 shots el eps+
  (0.0424) infla R (~7.5) frente al certificado a 102,400 shots
  (R = 1.19). Dos candidatos se comparan con los MISMOS shots,
  así que el ranking lo decide Q²×T, que es lo que importa; la
  certificación final es el verificador oficial completo.
- Cada propuesta sa_windows tarda ~30 s o más (una ventana) y el
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

- Extender el corredor con modelo a DQI y química: falta el
  materializador DQI (mutar el generador y reconstruir) y el de
  química (entrenar la factorización), más la semilla química
  pública (su .npz no está en el sample_submission).
- La llave del modelo la pone Arturo: crear la llave gratis
  (Gemini en AI Studio o Groq en su consola, sin tarjeta) y
  ponerla como secreto del notebook de Kaggle (`GEMINI_API_KEY`
  o `GROQ_API_KEY`). Sin llave el corredor corre igual con
  sa_windows.
- La decisión pendiente de 2026-11-11 sobre los 2 PDFs borrados
  por el commit c7dbb058 sigue abierta.

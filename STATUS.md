# STATUS.md — estado del repo (v2.17.7)

Última actualización: 2026-11-18. Los resultados históricos se conservan;
las verificaciones nuevas indican explícitamente su alcance.

## Versión

- **v2.17.7** (2026-11-18): cierre del falso PASS de fase DQI. 
  `verify_small` compara por shot `read_phase_flipped_across_shots()`
  con la paridad calculada desde los errores de entrada conocidos, además
  de comprobar sigma y preservación de registros. El test pequeño usa
  8 shots por defecto y devuelve `valid=False` ante cualquier discrepancia.
  `llm_auto_dqi` solo clasifica y guarda candidatos cuando las tres
  comprobaciones pasan; con `verify=False` no promociona candidatos.
  Se añadió una regresión con un scan deliberadamente sin fase.
  **Alcance:** el cambio cierra la vía de promoción incorrecta; no corrige
  por sí mismo el posible defecto HMR/Forney. Las mediciones anteriores
  documentaron errores de fase (3/8 en una configuración); hasta que la
  fase pase en las pruebas nuevas y el verificador completo, el DQI debe
  considerarse no válido. La suite no se pudo ejecutar en este entorno.


- **v2.17.6** (2026-11-14): auditoría pedida por Arturo (el
  optimizador no mejoraba en Kaggle v2.17.4). Causa medida: el
  batch estaba restringido a {4, 8, 17, 36} en el prompt y en el
  fallback, y dentro de ese conjunto la base (batch=4) ya era lo
  mejor; batch=1 da S=3.9983e10 (9.5% mejor) pero nunca se probaba.
  Corrección: batch 1..64 en el prompt y en el fallback de
  `llm_auto_dqi.py` y `autonomous.py`, y un barrido sistemático
  (batch 1, 2, 3 con nslot mínimo) antes del bucle LLM, para que
  la mejora esté garantizada aunque el LLM no la proponga (el LLM
  sube nslot cuando varía batch). Medido con el LLM real en
  sandbox: best_S=3.9983e10, mejora 1.105x vs la base 4.418e10,
  batch=1, nslot=6, Q=1067, T=29481. Tests 28/28. Detalle en
  `notes/v2.17.6.md`.
- **v2.17.5** (2026-11-14): pedido de Arturo (penalización de no
  repetición + LLM que use las estructuras .py del repo + las 3
  tareas). La v4 en Kaggle repitió la mejor semilla (la #13 era
  idéntica a la #1, batch=4, nslot=16, toom3=true) y el reporte del
  Notebook se cayó con KeyError en las semillas inválidas (sin
  'qubits'). Ahora: `_NoRepetir` (seen global: knobs, códigos y
  nslots; el prompt lleva los ya probados; si el LLM repite, se
  cuenta `repetidas` y NO se mide); tarea código-repo (el LLM
  escribe `novel_seed(n, m)` usando build_hybrid_bm, toom3,
  dqi_S del repo mismo); `run_tres_tareas` (3 tareas — knobs,
  codigo_repo, param_nueva — cada una 1 hora o 25 circuitos
  DISTINTOS, seen compartido). La v4 en Kaggle SÍ completó
  run_autonomous (14 semillas, 12 llamadas LLM, 0 fallbacks,
  mejor S 1.8891e12, 19.1% mejor que la primera 2.3366e12); el
  "error" del kernel era solo el reporte. Tests 10/10
  (test_autonomous). Detalle en `notes/v2.17.5.md`.
- **v2.17.4** (2026-11-14): pedido de Arturo ("soluciona y vuelve
  a probar hasta que funcione"). El circuito híbrido ya no deja
  basura en ancilla: OMG se descomputa, tmpL se limpia con iadd
  (sin tmpL2), ctrl1 vuelve a 0, y Toom-3 queda desactivado (rompía
  B/Lreg en bm_backward). Medido a n=10: ancilla en 1 por shot
  165 → 0, S restaurado 8/8, errores de valor 0/8, T dinámico =
  estático = 28,587 (nativo). Se quitó el K_j del scan (escalaba
  el error de Forney y cambiaba la fase) y se arregló `gf_inv_new`
  (no desempaquetaba el scaffold). Tests 24/24 (híbrido + LLM DQI
  + autónomo + LLM v220). Pendiente: la fase sigue con 3 errores
  de 8 (varía con la semilla del simulador; apunta al HMR del
  scan). Detalle en `notes/v2.17.4.md`.
- **v2.17.3** (2026-11-14): pedido de Arturo (la semilla
  encontrada no era transparente). El corredor DQI ya guarda la
  mejor semilla: `mejor_semilla.kmb` (el circuito real) +
  `mejor_semilla.json` (la receta: versión y commit, knobs,
  Q/T/S, verificación y SHA256 del .kmb). `reproducir_semilla`
  reconstruye desde la receta y comprueba el SHA256 (en sandbox
  coincide: Q=1,139, T=22,152). Tests 6/6 en test_llm_dqi.
  Detalle en `notes/v2.17.3.md`.
- **v2.17.2** (2026-11-14): robustez de `run_autonomous` tras el
  error del Notebook v3 en Kaggle (el log llegó hasta "ejecutando
  run_autonomous" y ahí se cortó, sin semillas). La medición de
  cada semilla ahora va en try/except (`_medir_seguro`): si una
  medición falla (knobs que el generador rechaza, falta de
  memoria), se registra como inválida y se sigue con la siguiente,
  en vez de tumbar toda la corrida. Y cada semilla se escribe en
  `progreso.txt` (con flush) al medirse, para ver dónde se quedó
  la corrida si el kernel muere (Kaggle no da el mensaje de
  error). La semilla 0 a n=30, m=255 se midió en sandbox en 1.5 s
  (Q=2,919, T=230,199, válida), así que la escala no era el
  problema. Tests 7/7 (`tests/test_autonomous.py`, +1 de medición
  que falla). Detalle en `notes/v2.17.2.md`.
- **v2.17.1** (2026-11-14): corrección del bug que tumbó el
  Notebook v2 en Kaggle (error a los ~8 min, sin mensaje). Causa:
  `auto_mvp/autonomous.py` importaba `build_hybrid_bm` al cargarse
  y ese módulo crea `km.GF2Field(...)` al importarse; en Kaggle
  `import kickmix` trae un paquete VACÍO (sin GF2Field) hasta que
  `setup_kaggle()` lo arregla, así que el `from auto_mvp.autonomous
  import ...` del Notebook fallaba con AttributeError antes de
  bajar el GGUF. Ahora `autonomous.py` importa `llm_auto_dqi` /
  `build_hybrid_bm` perezoso DENTRO de `run_autonomous` (después de
  `setup_kaggle`), e importar el módulo es seguro sin kickmix
  (test de regresión en subproceso con kickmix vacío). Además
  `setup_kaggle` ya no exige encontrar la competencia: si no está
  montada, salta el .so y va directo a pip install kickmix (generar
  semillas no necesita el dataset). Tests 6/6
  (`tests/test_autonomous.py`). Detalle en `notes/v2.17.1.md`.
- **v2.17.0** (2026-11-14): pedido de Arturo (el Notebook solo un
  código de ejecución delgado; la lógica vive en el repo). Nuevo
  `auto_mvp/autonomous.py`: generación AUTÓNOMA de semillas de
  circuitos desde el repositorio. `LocalLLM` (Qwen2.5-Coder-1.5B-
  Instruct local, GGUF Q4_K_M, llama-cpp-python, temp 0.7, sin
  Gemini/Groq; `llama_cpp` se importa perezoso), `validate_code`
  (guarda de imports: solo math/typing/auto_mvp/kickmix),
  `setup_kaggle` (encuentra la competencia y deja kickmix con
  Circuit) y `run_autonomous` (sin base, sin baseline, sin
  puntuación máxima: la primera semilla se genera y se mide, cada
  semilla nueva —parametrización propuesta por el LLM— solo trata
  de hacerlo mejor que la mejor hasta ahora; al final el LLM
  propone una parametrización nueva `novel_nslot` chica y se mide
  una semilla con ella). Guarda `semillas.json` (las semillas +
  sus parametrizaciones), `param_nueva.json` y `VEREDICTO.json`.
  Sin modelo, sigue con los knobs por defecto. Probado en sandbox
  con cliente falso (5 semillas a escala chica, mejor toom3
  T=22,152 S=3.42e10; novel_nslot n=7 medido; código roto no
  aborta). Tests 5/5 (`tests/test_autonomous.py`). El Notebook de
  Kaggle ahora es delgado (2 celdas de código: instalar + ejecutar
  `run_autonomous`). Detalle en `notes/v2.17.0.md`.
- **v2.16.0** (2026-11-14): pedido de Arturo (que el LLM optimice
  durante la ejecución). Nuevo `auto_mvp/llm_auto_dqi.py`: el
  estratega propone deltas DQI (batch, nslot, toom3) como JSON, el
  generador híbrido materializa y se mide Q/T/S (S = R*Q^2*T,
  R=1.1912605); solo el menor S sobrevive. Toom-3 vendoreado en el
  repo (`toom3.py` + `mult51.py` + `poly_mul_2/6.txt`, 45 T/mult
  vs 63 T nativo; escala completa T 1,900,947 -> 1,519,563, Q igual
  6,791, S 1.04e14 -> 8.35e13). Sin llave, el corredor sigue con
  los knobs por defecto. Probado con cliente falso (mejora con
  toom3 guardada) y sin llave (cae al defecto). Tests 17/17.
  El LLM real no se probó aquí (no hay llave en este entorno).
  Detalle en `notes/v2.16.0.md`.
- **v2.15.0** (2026-11-14): pedido de Arturo (generador híbrido DQI).
  Nuevo `auto_mvp/circuits/generators/build_hybrid_bm.py`: decodificador
  BM + Forney con descomposición híbrida (sin reg_b, contrato solo de
  fase, MBUC/HMR, inversiones Montgomery por lotes, BM en vez de EEA).
  Verificado a escala chica (`--verify`: PASS; sigma 24/24, scan limpio
  12/12, circuito completo S restaurado 10/10 y ancillas a |0>).
  Escala completa (n=70, m=4095, batch=17): Q=6,791, T=1,900,947,
  S proyectado 1.04e14. **No competitivo todavía**: 4.3x peor que el
  baseline (2.44e13). Falta reutilización de slots S + reconstrucción
  de B (hacia Q~1,414) y Toom-3 (hacia T menor). Detalle en
  `notes/v2.15.0.md`.
- **v2.14.0** (2026-11-14): pedido de Arturo (que los pases apunten
  a lo que cobra el S, no a limpiar Clifford). Cuatro piezas:
  - **rotation_merge: Z_POW en controles de CCX/CSWAP pasa**
    (`rotation_merge.py`): una Z en los controles de un Toffoli
    conmuta con él, así que la pendiente sobrevive y puede
    fusionarse (antes se vaciaban los tres qubits). Sintético:
    dos Z_POW(0.25) separadas por un CCX fusionan a S (gratis),
    T 2.0 → 0.0. En la semilla y la muestra: 0 fusiones nuevas
    (negativo medido).
  - **commuting consciente de Toffoli** (`commuting.py`): para un
    par CCX, una intermedia puede quedarse si conmuta con el
    Toffoli (diagonal en controles, CX con control en a/b, otro
    Toffoli compatible); una diagonal o CX en el objetivo c sigue
    bloqueando. Stats nuevas: `toffoli_pairs_cancelled`,
    `toffoli_removed`. Medido: 10 sintéticos correctos; semilla
    198 quitados 0 Toffoli; muestra 4.216 quitados 0 Toffoli; DQI
    público 1.024.860 quitados (512.430 pares) **0 Toffoli** —
    igual que v2.11: el DQI no tiene pares Toffoli cancelables ni
    con la regla extendida (974 s).
  - **Modelo cobrable + delta_t** (`cost_models/chargeable.py`,
    `benchmark.py`): la regla de cobro del verificador (Clifford
    0, ángulo T 1, otro ángulo `0.56*log2(1/eps)+5.3`; CCX/CSWAP
    1 Toffoli). Hallazgo: el eps lo deriva el verificador del
    margen de error — en la semilla son 28.62 T por rotación, no
    18.74. El benchmark reporta `t_count` y `delta_t` con el
    T-count EXACTO del verificador (semilla: T = 1.186,36) y
    `delta_toffoli` ahora también en invsqrt.
  - **SA: aceptación solo por baja de cobrables** (`circuit.py`,
    `sa_windows.py`): la ganancia se verifica en el archivo de
    salida (Toffoli de entrada vs salida), no solo en el log; si
    el log dice que ganó pero el archivo no baja el Toffoli, se
    rechaza. La reducción de instrucciones/Clifford no cuenta.
    Ver `notes/v2.14.0.md` y `tests/test_tool_v2140.py` (9 tests).
- **v2.13.0** (2026-11-14): pedido de Arturo (subir el Notebook de
  mapeo a GitHub y corregir lo de rotation_merge). Dos piezas:
  - **Salto de línea heredado** (`rotation_merge.py`, `peephole.py`):
    las Z_POW re-emitidas en memoria llevaban el salto de línea de
    la entrada; sin él se pegaban a la siguiente línea y el `.kmx`
    ya no cargaba ("Invalid decimal angle"). Hallazgo del Notebook
    de mapeo en Kaggle v15/seed2. El `commuting` no tenía el defecto.
    Sin saltos en la entrada, la salida es idéntica a v2.12.0.
    Ver `notes/v2.13.0.md` y `tests/test_tool_v2130.py` (3 tests).
  - **Notebook de mapeo en el repo** (`kaggle-notebooks/`): el
    constructor, el Notebook y los scripts de Kaggle. Medido en
    Kaggle v16 (4,9 min): invsqrt S = 2.068.518,26 Q = 260 válido;
    DQI fast_verify 2048 válido S = 154.025.541.234.591,47; DFTHC
    oficial PASS score = 3.355.599.588,32 (el publicado); LLM Qwen
    1.5B en CPU, 3 semillas.
- **v2.12.0** (2026-11-13): pedido de Arturo (análisis del script
  de evidencia A y causas latentes, integrado a la herramienta).
  Una pieza:
  - **ROL CAUSAL** (`auto_mvp/causal.py`): el clasificador del
    script (correlación no es causa; solo la intervención
    distingue), aplicado a los datos MEDIDOS del benchmark. Medido
    en la semilla: peephole y commuting son indicadores (quitan
    Clifford, no mueven S ni Toffolis), rotation_merge, fan-out y
    SA son indeterminados, y la acción mínima para cualquier
    ganancia positiva de S es None. Los 3 mundos sintéticos del
    script son el test de ground truth del clasificador.
    Ver `notes/v2.12.0.md`.
- **v2.11.0** (2026-11-13): INNOVAR, PROBAR, AUDITAR, cuarta vuelta
  (directiva de Arturo 2026-11-13 18:25 CST, bucle ×5, vuelta 5/5,
  ÚLTIMA). Dos piezas:
  - **MAX_GAP 256** en la conmutación (antes 16): en la semilla el
    resultado satura en 256 (42 con 16, 48 con 32, 58 con 64, 70
    con 128, 76 con 256 y lo mismo con 512/1024/4096). Tras el
    peephole: 76 más (38 pares), S idéntico, válido, idempotente.
  - **CONMUTACIÓN EN EL BENCHMARK** (`auto_mvp/benchmark.py`):
    quinto operador de la comparación. Tabla de la semilla en
    `notes/v2.11.0-benchmark-invsqrt.md`: commuting 198 (99 pares,
    39 por conmutación), S idéntico. Medición DQI con GAP 256 en
    curso (GAP 16 daba +235.386). Ver `notes/v2.11.0.md`.
- **v2.10.0** (2026-11-13): INNOVAR, PROBAR, AUDITAR, cuarta vuelta
  (directiva de Arturo 2026-11-13 18:25 CST, bucle ×5, vuelta 4/5).
  Una pieza:
  - **PEEPHOLE CON CONMUTACIÓN**
    (`auto_mvp/circuits/operators/commuting.py`, streaming, una
    pasada, búsqueda acotada a 16 compuertas): cancela pares
    idénticos separados por compuertas en qubits disjuntos.
    Medido: semilla 42 más tras el peephole (164 en total, S
    idéntico, válido, idempotente); DQI 235.386 más (352.078 en
    total, 3× lo del peephole, Toffoli 453.312 intacto,
    instrucciones 64.168.150 → 63.816.072, 2ª pasada 0).
    Ver `notes/v2.10.0.md`.
- **v2.9.0** (2026-11-13): INNOVAR, PROBAR, AUDITAR, cuarta vuelta
  (directiva de Arturo 2026-11-13 18:25 CST, bucle ×5, vuelta 3/5).
  Una pieza:
  - **FAN-OUT EN EL BENCHMARK** (`auto_mvp/benchmark.py`): el
    detector de v2.8 es el cuarto operador de la comparación (no
    reescribe, mide su potencial junto a los demás). Tabla de la
    semilla en `notes/v2.9.0-benchmark-invsqrt.md`: peephole 122
    Clifford ΔS 0, rotation_merge 0 fusiones ΔS 0, fanout 6 grupos
    0 válidos 0 T, sa_windows saltado. Ningún operador mejora el S
    de la semilla: todos están en su punto fijo (ver `notes/v2.9.0.md`).
- **v2.8.0** (2026-11-13): INNOVAR, PROBAR, AUDITAR, cuarta vuelta
  (directiva de Arturo 2026-11-13 18:25 CST, bucle ×5, vuelta 2/5).
  Una pieza:
  - **DETECTOR DE FAN-OUT** (`auto_mvp/circuits/operators/fanout.py`,
    streaming, una pasada): rachas de CCX con el mismo AND (c1 & c2)
    y objetivos distintos, con comprobación de validez (ninguna
    compuerta entre los CCX puede tocar c1, c2 o los objetivos).
    Medido: semilla 6 grupos por subflujo, **0 válidos, 0 T**; DQI
    33.575 grupos, **0 válidos, 0 T** (93.1 s). El ~33 T del estudio
    de reescritura NO sobrevive a la validez (ver `notes/v2.8.0.md`).
    La reescritura queda sin nada que reescribir.
- **v2.7.0** (2026-11-13): INNOVAR, PROBAR, AUDITAR, tercera vuelta
  (directiva de Arturo 2026-11-13 18:25 CST, bucle ×5). Tres piezas:
  - **PEEPHOLE CON PILA**: la pasada con una sola compuerta
    pendiente NO era idempotente (en la semilla hacían falta más
    de 15 pasadas para llegar al punto fijo). Con pila, una sola
    pasada encuentra TODAS las cancelaciones: en la semilla quita
    **122 Clifford (56 CX + 5 X)** en vez de 44, S idéntico, y la
    2ª pasada quita 0 (idempotente de verdad). En el DQI quita
    **116.692 (58.346 pares)** en vez de 46.610, Toffoli 453.312
    intacto (ver `notes/v2.7.0-benchmark-dqi.md`).
  - **BENCHMARK para DQI**: la comparación ya no es solo de
    invsqrt (`task="dqi"` mide cargar en kickmix + conteo de
    Toffolis; el SA se salta con su razón). Tabla DQI en
    `notes/v2.7.0-benchmark-dqi.md`.
  - **BM+FORNEY refutado como materializador**: el diseño pierde
    ~10× contra el híbrido público (S≈3.23e12, 6.57× vs 64.76×)
    y la construcción a mano está incompleta (paso 51/53, sin
    Chien completo ni .kmb). No es practicidad: queda como nota
    para v2.8 (el materializador DQI tendrá que ser otro diseño).
- **v2.6.0** (2026-11-13): INNOVAR, PROBAR, AUDITAR, segunda vuelta
  (directiva de Arturo 2026-11-13 01:06 CST). Tres piezas:
  - **DQI .kmb → .kmx**: el .kmb público SÍ se convierte a .kmx en
    sandbox (893 MB, 64.222.295 líneas, 11.9 s). La versión en
    memoria de los operadores se moría por OOM a esa escala, así
    que **peephole y rotation_merge ahora procesan en STREAMING**
    (línea a línea, sin cargar el circuito entero) y el DQI sí
    pasa. El SA no es práctico a esa escala (64M de instrucciones).
  - **CONEXIÓN**: rotation_merge ya es pre-paso optativo del
    corredor (`propose_sa_windows` y `run_llm_auto`,
    `--rotation-merge`) y la receta lo guarda para reconstruir la
    cadena igual. Corrida de prueba con la fusión encendida: 2
    propuestas, 2 válidas, ganancia 0, fusión 0 (ver
    `notes/v2.6.0-run.md`).
  - **BENCHMARK** (`auto_mvp/benchmark.py`): cada operador medido
    en el mismo circuito, en una tabla (válido, S, ΔS). En la
    semilla invsqrt los tres dan ΔS = 0.0 (ver
    `notes/v2.6.0-benchmark-invsqrt.md`). Y lo reportado como
    óptimo se probó con ventana mayor: **sa_windows K=8, ganancia
    0, válido, S idéntico** — la semilla sigue óptima para esas
    ventanas.
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

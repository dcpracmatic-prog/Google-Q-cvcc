# AUTO_MVP — auto-optimizador para VQCC

Optimización de circuitos para la competencia Google Quantum AI —
Verifiable Quantum Circuit Compilation (VQCC). El sistema busca
combinaciones de las tres tareas (invsqrt, DQI, química) que sumen
el puntaje pedido, y exporta la base para auditarla y diseñar el
submission real.

> **Repo privado mientras la competencia esté abierta.**

## Qué hace

- **Auto-reparación (harness VQCC):** vigila el costo S de cada
  tarea, detecta cuando un candidato empeora o rompe el contrato,
  calibra el margen con una sonda parecida a la carga, y baja la
  autonomía (AUTO → PROPOSE → SHADOW) cuando la compilación falla
  3 veces seguidas. El mejor verificado vive separado del mejor
  proyectado.
- **Optimización:** el mutador autónomo genera las variantes
  (morph, ventana SA, salto Lévy, MWIS) y las criba por metadatos
  (proxy), tunela bloques con reglas MORPH medidas (Qualtran:
  grafo de llamadas, T/Q de primera clase), lee directivas JSON,
  y promueve lo que bate el mejor envío.
- **La guía:** guarda el mejor componente por tarea ENTRE corridas
  (la corrida 1 puede traer el mejor invsqrt y la corrida 2 el
  mejor DQI) y, dado un objetivo, dice si la combinación llega y
  cuánto le falta a cada tarea. Cuando llega, exporta los tres
  componentes en un ZIP de auditoría y en un Notebook .ipynb
  ejecutable, listos para la compilación pesada.
- **Orquestación en serie:** corre las tres tareas en serie con el
  mismo ledger y acepta el balance global cuando la GM combinada
  llega al objetivo, aunque una tarea se rezague y las otras dos
  compensen.
- **El formato del submission:** arma el ZIP con la estructura
  oficial y lo valida; si no pasa, lo borra.

El mérito es siempre el **S oficial**: DQI `R·Q²·T`, invsqrt
`Q·C` (con la síntesis de rotaciones incluida), química
`λ_eff·T·Q`. El puntaje es la media geométrica de los ratios
(referencia / propio) en las tres tareas.

## Cómo funciona

```
candidato
  → proxy (criba por metadatos, en milisegundos)
  → puerta de promoción (GM estimada contra el mejor envío)
  → artefacto i<iter>-<score> + export al dataset (estructura + código)
  → compilación pesada (solo lo promovido)
  → ledger del mejor por tarea (entre corridas)
  → combinación contra el objetivo → ZIP de auditoría
```

El filtro de integridad revisa sigma, C/B, dreg, alpha y
temporales por candidato: ninguna reducción de recursos puede
romper la equivalencia lógica (la lección del paso 51). La
bitácora CVV es una cadena de hashes de los récords. El
checkpoint guarda cada mejor verificado al instante.

## Los números

- **Mejor envío: 23.94667** (ref 58076483): invsqrt propio
  certificado S 100,568.5 (20.65x), DQI público híbrido S 3.7676e11
  (64.76x, Q=892), química pública S 326,800,029.87 (10.27x).
- **Objetivo 30.00:** el producto debe ser 27,000 (30³) contra
  13,732 actual. Solo por DQI, S 1.9162e11 (127.3x, T −49.1%).
- **Mejores propios medidos:** DQI Montgomery b=17 S 3.2331e12
  (Q=1,414, T=1,315,731); química baseline λ_eff 49.254686,
  error_2 16.1332 mHa.

## Gobernanza (directiva de Arturo, 2026-11-11 — máxima autoridad)

**La misión de este chat es crear LA HERRAMIENTA, no la
competencia ni su solución.** La arquitectura del repo debe
exportar, generar, modificar y optimizar todo lo referente a la
competencia. El flujo es el del **Solucionador Morfológico**:

```
config JSON (decodificador)
  → ciclo morfológico por tarea, en serie (Qualtran + MORPH + estrategias)
  → filtro y validación (meta_mvp + integridad formal)
  → ranking dinámico + dataset (structure.json, module.py)
  → al cruzar la meta global: Notebook .ipynb ejecutable con los tres
    módulos ganadores, listos para la compilación pesada
```

Las seis familias de la materia prima, y dónde vive cada una:

- **K — MORPH, Qualtran, registro cuántico:** el núcleo
  morfológico y la materia prima. Qualtran da los Bloqs y las
  métricas T/Q; MORPH reordena y muta la topología.
  (`qualtran_bridge.py`, `morph_tunnel.py`)
- **D — Operadores de mutación y búsqueda:** ventanas SA de
  Toffoli, tunelamiento Lévy, MWIS (LOGIC_CORE) y registro
  dinámico de transformaciones. Son las estrategias de mutación
  del orquestador. (`mutator.py`, `mwis.py`, `maxcut.py`)
- **E & J — Lab y Tres Pilares / DQI:** el evaluador. Calcula
  el S y la GM oficiales con las fórmulas de la competencia.
  (`numeric_lab.py`, `proxy.py`, `vqcc/`)
- **A & H — Auto-reparación y verificación formal:** los
  guardianes del fail-closed. Ningún módulo promovido pasa sin
  que el lazo compruebe que el contrato lógico sigue intacto.
  (`healing/`, `integrity.py`, `vqcc/verify.py`)
- **C & I — Observer / Centinela y EQG:** telemetría y
  causalidad. Registran la fricción y la salud de la búsqueda
  para ajustar la agresividad del orquestador.
  (`observer.py`, `cvv.py`, `checkpoint.py`)
- **B, F & G — DSP, FIELD, SpMM, SIMD:** aceleradores
  bare-metal. Las operaciones matemáticas intensivas corren en
  C/C++ nativo cuando está disponible, con fallback en Python
  puro. (`accel.py`)

## Componentes

```
auto_mvp/
  healing/        auto-reparación genérica v0.1.0
  vqcc/           harness: contratos, costos, detector, verificador,
                  ledger, búsqueda, calibración
  integrity.py    filtro de integridad (sigma, C/B, dreg, alpha)
  cvv.py          cadena de hashes de los récords
  checkpoint.py   checkpoint atómico
  goal.py         meta (meta_mvp) y regla de paro
  proxy.py        proxy de metadatos (con la síntesis de rotaciones)
  pipeline.py     pipeline por fases (6 h / 24 h)
  qualtran_bridge.py  Bloqs reales → grafo de llamadas, T/Q
  morph_tunnel.py     túnel MORPH (reglas con evidencia medida)
  json_directive.py   directivas JSON en lenguaje natural
  step_plan.py        plan de pasos reprogramable en caliente
  orchestrator.py     orquestador adaptativo
  numeric_lab.py      prefiltro Chebyshev invsqrt + puerta fail-closed
  mwis.py             selección MWIS (LOGIC_CORE v4)
  maxcut.py           partición MaxCut del grafo de conflictos
  observer.py         observador (solo observa, nunca veta)
  dataset.py          dataset de trabajo (estructura + código)
  packaging.py        formato del submission.zip y su validador
  combiner.py         la guía (mejor por tarea, entre corridas)
  mutator.py          mutador autónomo (morph, ventana SA, salto Lévy, MWIS)
  serial.py           orquestación en serie con compensación global
  notebook.py         exporta los ganadores a un .ipynb ejecutable
  accel.py            aceleración nativa opcional (SpMM, FIELD, SWAR)
  operations.py       punto de entrada único (12 operaciones)
  cli.py              CLI: python -m auto_mvp.cli <op>
skills/auto-mvp-vqcc/
  mcp_server.py     servidor MCP (stdio, solo stdlib) para Claude
  tools.py          las operaciones como funciones (ChatGPT, Grok)
  functions.json    esquema de function calling (OpenAI)
tests/            suite completa (110 tests)
examples/         maxcut_reference.cpp (el C++ de Arturo, verbatim)
```

## Uso

El comando único (instalar, decir cuánto quieres, ejecutar):

```bash
# Busca la base para la meta que digas (1.5, 25, 10000...). Rondas
# 1-2-3-1-2-3; al llegar entrega runs/audit-base-<gm>.zip con las
# configuraciones y las métricas de cada tarea. Sin .kmb: esto NO es
# la solución de la competencia, es la base para crearla.
# Fuerza bruta: si lo real no llega, las variables de costo se bajan
# con operaciones aritméticas (restar, multiplicar, dividir...),
# LAS TRES TAREAS A LA VEZ (la meta es el producto cruzado: cada una
# mejora por el mismo factor, no una sola cargando todo). Cerca del
# objetivo solo pasos finos, para no pasar de largo. Los conteos son
# enteros y cada propuesta pasa los límites físicos del contrato
# (DQI eps+ < 1/16, química Lambda > 49, Angles_k <= 128 cúbits).
# Nunca se para por estancamiento: solo paran los límites que pongas
# (--max-rounds, --time-budget) o llegar a la meta. Lo de fuerza
# bruta va marcado como proyectado en el manifest. Si hay .kmb/.kmx
# en runs, se validan con Kickmix y el resultado va en el JSON.
python -m auto_mvp.auto --target 25
```

El resto de operaciones sueltas:

```bash
# La guía: ¿llega la mejor combinación a 30.00?
python -m auto_mvp.cli combine --target 30 --runs-dir runs --export

# Evaluar un candidato (proxy + puerta)
python -m auto_mvp.cli evaluate --in candidato.json --meta-mvp 30

# Tunelar un grafo (Chien → Montgomery b=17)
python -m auto_mvp.cli tunnel --in grafo.json

# Validar el formato de un submission.zip
python -m auto_mvp.cli validate --path submission.zip

# La puerta de promoción
python -m auto_mvp.cli gate --meta-mvp 30

# El mutador autónomo (genera candidatos desde una semilla)
python -m auto_mvp.cli mutate --in semilla.json --n 10 --seed 42

# La orquestación en serie (las tres tareas, compensación global)
python -m auto_mvp.cli serial --in trabajos.json --target 30 --runs-dir runs

# Los ganadores a un Notebook ejecutable
python -m auto_mvp.cli notebook --runs-dir runs --out ganadores.ipynb
```

Las 12 operaciones (`evaluate_candidate`, `apply_morph_tunnel`,
`decode_json_config`, `run_orchestrator`, `check_integrity`,
`export_module`, `validate_submission`, `combine_best`,
`promotion_gate`, `mutate`, `run_serial`, `export_notebook`) están en
`auto_mvp/operations.py` y se invocan igual por CLI, MCP y `tools.py`.

## Correr los tests

```bash
python3 -m pytest tests/ -q
```

Solo stdlib: no hay dependencias. El venv con Qualtran 0.7.0 y
kickmix 0.1 (lo que usan los verificadores oficiales) está en
`~/workspace/sandbox-run/venv/bin/python`.

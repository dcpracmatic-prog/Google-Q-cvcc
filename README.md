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
- **Optimización:** criba variantes por metadatos (proxy), tunela
  bloques con reglas MORPH medidas (Qualtran: grafo de llamadas,
  T/Q de primera clase), lee directivas JSON, y promueve lo que
  bate el mejor envío.
- **La guía:** guarda el mejor componente por tarea ENTRE corridas
  (la corrida 1 puede traer el mejor invsqrt y la corrida 2 el
  mejor DQI) y, dado un objetivo, dice si la combinación llega y
  cuánto le falta a cada tarea. Cuando llega, exporta los tres
  componentes en un ZIP de auditoría.
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
  operations.py       punto de entrada único (9 operaciones)
  cli.py              CLI: python -m auto_mvp.cli <op>
skills/auto-mvp-vqcc/
  mcp_server.py     servidor MCP (stdio, solo stdlib) para Claude
  tools.py          las operaciones como funciones (ChatGPT, Grok)
  functions.json    esquema de function calling (OpenAI)
tests/            suite completa (110 tests)
examples/         maxcut_reference.cpp (el C++ de Arturo, verbatim)
```

## Uso

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
```

Las 9 operaciones (`evaluate_candidate`, `apply_morph_tunnel`,
`decode_json_config`, `run_orchestrator`, `check_integrity`,
`export_module`, `validate_submission`, `combine_best`,
`promotion_gate`) están en `auto_mvp/operations.py` y se invocan
igual por CLI, MCP y `tools.py`.

## Correr los tests

```bash
python3 -m pytest tests/ -q
```

Solo stdlib: no hay dependencias. El venv con Qualtran 0.7.0 y
kickmix 0.1 (lo que usan los verificadores oficiales) está en
`~/workspace/sandbox-run/venv/bin/python`.

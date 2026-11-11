# PIPELINE.md — pipeline asíncrono por fases (6 h / 24 h)

El diseño de Arturo para pelear el primer lugar antes del cierre
(20 de enero de 2027). Un pipeline por fases, reanudable, con una
puerta de promoción y artefactos con nombre.

## La separación (inmutable / código / trabajo)

| Capa | Qué es | Dónde vive | Permiso |
|---|---|---|---|
| Inmutable | Datos de la competencia: starter kit, verificadores, kickmix | `/kaggle/input` (Kaggle) o el sandbox (local) | Solo lectura, nunca se escribe |
| Código | El optimizador AUTO_MVP (este repo) | Clon del repo, o snapshot vendido con su SHA | Solo lectura, nunca se modifica en el run |
| Trabajo | Todo lo que el pipeline produce | `<working>/runs/` | Escritura |

El repo NO es el dataset de entrada: el dataset inmutable es
`/kaggle/input`. El repo es la capa de optimización. La separación
se mantiene porque el notebook nunca escribe ni en el input ni en
la copia del código: todo va a `<working>/runs/`. Como el repo es
privado, Kaggle no puede clonarlo sin credenciales (y jamás se mete
un token en el notebook): el notebook lleva el snapshot del código
con el SHA del commit grabado en el manifiesto, byte-idéntico al
repo en ese commit.

## Las 3 fases

### Fase 1 — Filtro rápido (espacio de metadatos)

El proxy (`auto_mvp/proxy.py`) evalúa variantes paramétricas
(anchos de registro, densidades de compuertas, estructuras de
bloques) en milisegundos. Se descartan millones de combinaciones
inviables sin instanciar objetos pesados ni compilar nada. La
variante que viola un tope duro o el contrato oficial muere aquí,
y el verificador nunca se entera de que existió.

### Fase 2 — Promoción por beneficio real

Solo si la estimación matemática alcanza la meta se da luz verde.
La meta es un parámetro ABSOLUTO (**`meta_mvp`**): el puntaje que
se le exige al sistema (ej. 30.00), no lo que dictó un envío
anterior. Sin directiva, la meta por defecto es **GM estimada >
23.94667** (el mejor envío 58076483). Con directiva, el pipeline
quema ciclos de búsqueda y prefiltrado hasta alcanzar ese umbral
o agotar el presupuesto, y para limpio cuando un candidato REAL lo
alcanza (un target es una hipótesis, no el circuito que entrega el
puntaje: su promoción no para la búsqueda).

La ventaja pura es la mejora real (Toffolis, cúbits, profundidad
T) frente al baseline oficial, traducida de forma directa al
puntaje con la fórmula de la competencia: por tarea, el ratio =
costo de referencia / costo propio; el puntaje es la media
geométrica de los tres ratios (`pure_advantage`). La promoción
significa "vale la pena gastar compilación aquí", no "esto va a
puntuar 23.95": la estimación es una proyección.

La puerta mide contra los componentes del mejor envío (invsqrt
propio 20.65x, DQI público 64.76x, química pública 10.27x;
producto 13,732), no contra los propios. El invsqrt propio
100,568.5 es medido por el verificador oficial, que ya cobra la
síntesis de rotaciones; el costo del proxy también la cobra desde
v0.9.1 (`rotation_t_count(eps) = 0.56*log2(1/eps) + 5.3` con eps
sacado del margen que deja el rel_error). Batir el envío exige
DQI ~64.76x, es decir, batir el DQI público (S < 3.7676e11).

La meta 30.00 NO es alcanzable con el enfoque actual (veredicto
2026-11-11, verificado): para 30 el producto debe ser 27,000
(30^3) contra 13,732 actual (x1.966); solo por DQI habría que
bajar T un 49.1% (DQI 127.3x con química pública). El mayor peso
de T está en unextract/unconvert (~43%): ese es el bloque que
vale la pena atacar. La puerta promueve mejoras pequeñas por
encima de 23.94667, y solo se envía lo que pasa los tres
verificadores oficiales (puerta fail-closed:
`numeric_lab.fail_closed_gate`).

### Fase 3 — Compilación pesada, artefactos y dataset de trabajo

Solo lo promovido llega aquí. Se invierten las horas de cómputo
(4, 6 o las que permita el ciclo de Kaggle) y, si el verificador
oficial lo confirma, el artefacto queda guardado con el número de
iteración y la calificación estimada:

```
runs/i120549-34.16/
  manifest.json    (iteración, GM estimada, SHA del código, fase)
  structure.json   (v0.8.0: grafo de llamadas completo, métricas, evidencia)
  module.py        (v0.8.0: código ejecutable, solo stdlib; python module.py)
  source/...       (v0.8.0: el código del constructor, cuando el candidato lo trae)
```

El fail-closed está perfecto para el submission.zip final, pero un
módulo promovido no se queda en un manifiesto con métricas frías:
cada promoción EXPORTA e INYECTA su estructura completa y su código
ejecutable al dataset de trabajo (`<runs_dir>/dataset/<nombre>/`,
con el mismo contenido que el artefacto) y el índice
`dataset/index.json` lista los módulos inyectados. El cargador
(`WorkingDataset.load`) los carga por nombre: grafo, métricas y
ruta del código ejecutable. La fase 3 (compilación a .kmb) consume
el dataset, no un manifiesto pelado. La compilación a .kmb
(kickmix) NO es parte del export: el dataset da la estructura y el
código que la compilación necesita. Un módulo sin grafo se exporta
con sus métricas y su module.py, y lo dice en el export. El grafo
que se exporta es el TUNELADO (no el base).

La fase del manifiesto es `PROMOTED` al guardar, `PASS` o `FAIL`
tras la compilación pesada. Al terminar, el submission.zip se arma
solo desde los artefactos `PASS` (fail-closed: solo los tres
verificadores en modo full lo arman).

### Empaquetado y validación del ZIP (v0.9.0)

El formato oficial vive en el repo (`auto_mvp/packaging.py` y
SPEC_AUTO_MVP.md), no solo en memoria. `build_submission_zip`
arma el ZIP con la estructura correcta y lo valida; si no pasa, lo
borra. `validate_submission_zip` / `validate_submission_dir`
comprueban: rutas exactas, sin directorio raíz extra, sin
duplicados, un solo invsqrt y un solo dqi, angle_k consecutivos
desde 0 sin huecos, y submission.npz con las 6 claves (U, W,
H2_I, H1_I, Hsym_lower, tree_edges). `submission_ready` da READY
solo si la puerta fail-closed Y el formato pasan. El validador
revisa el FORMATO, no el contenido.

## El ciclo asíncrono (6 h / 24 h)

Kaggle limita la duración de una corrida de notebook, así que el
pipeline corre en bloques con presupuesto de tiempo
(`time_budget_seconds`, por ejemplo 6 h = 21,600 s). Al agotarse el
presupuesto, guarda el estado en `runs/state.json` y para limpio.
La siguiente corrida retoma desde ahí: el contador de iteraciones
no se reinicia, el mejor GM se conserva y las promociones ya
guardadas no se repiten. El ciclo de 24 h son varias corridas de
6 h encadenadas por el estado.

## Qué es un artefacto promovido

Hay dos clases, y el manifiesto las distingue:

- `kind: "candidate"` — un módulo real construido (por ejemplo una
  combinación del SearchLoop con sus Q/T medidos por el cost_model).
- `kind: "target"` — un punto paramétrico hipotético del espacio de
  metadatos (por ejemplo Q=400/T=90,000). No es un circuito: es la
  región que la puerta dice que vale la pena buscar. La compilación
  pesada es la que convierte un target en un candidato real o lo
  descarta.

## Uso

```python
from auto_mvp import MetadataProxy, Pipeline, PromotionGate
from auto_mvp.vqcc import dqi_spec

proxy = MetadataProxy(dqi_spec(), hard_caps={"max_qubits": 2000}, margin=0.10)
pipe = Pipeline(proxy, PromotionGate(), runs_dir="runs",
                time_budget_seconds=6 * 3600, source_commit="abc123")
res = pipe.run(mi_flujo_de_candidatos)
print(res.promoted, res.best_gm, res.artifacts, res.stopped)
```

El flujo de candidatos lo da el proponente (el lazo no inventa
mutaciones). Para reanudar, basta construir otro `Pipeline` con el
mismo `runs_dir`: lee `state.json` y sigue.

## Capa de adaptación dinámica (v0.6.0)

El pipeline no se limita a pruebas fijas y paramétricas. La
formalización algorítmica es Qualtran (Bloqs, grafo de llamadas,
T/Q como cantidades de primera clase), y sobre ella opera la capa
adaptativa:

- **Tunelamiento MORPH** (`morph_tunnel`): reordena y reemplaza
  BLOQUES del grafo de llamadas, no solo números. Un túnel es un
  salto en el paisaje de costo (ej. Chien → Montgomery b=17:
  T 1,511,522 → 1,315,731, medido). Cada regla trae su evidencia
  medida; una regla sin evidencia no se aplica.
- **Decodificador JSON** (`json_directive`): lee configuraciones
  JSON con directivas en lenguaje natural ("sube la meta a 30",
  "ataca unextract", "reordena tunnel antes que gate") y las
  traduce a operaciones. Vocabulario controlado y determinista;
  lo que no encaja se reporta, nunca se tira en silencio.
- **Plan de pasos** (`step_plan`): la lista ordenada de pasos
  (tunnel, proxy, gate, compile, observe, calibrate, search,
  verify), reprogramable en caliente con log de cada cambio.
- **Orquestador adaptativo** (`orchestrator`): ejecuta el plan por
  candidato y aplica las directivas JSON entre iteraciones. El
  orden importa: con túnel antes del proxy, un candidato que el
  proxy rechazaría se tunela primero y pasa; con túnel después,
  solo se tunelan los promovidos.

```python
from auto_mvp import (AdaptiveOrchestrator, MetadataProxy, Pipeline,
                      PromotionGate, StepPlan, load_plan)
from auto_mvp.vqcc import dqi_spec

cfg = load_plan({"meta_mvp": 30.0,
                 "directives": ["ataca unextract",
                                "reordena tunnel antes que gate"]})
pipe = Pipeline(MetadataProxy(dqi_spec(), margin=0.10),
                PromotionGate(cfg["meta_mvp"]), runs_dir="runs")
orch = AdaptiveOrchestrator(pipe, StepPlan())
res = orch.run(mi_flujo, directives=cfg["directives"])
print(res.promoted, res.best_gm, res.tunneled, res.reprogrammings)
```

La gobernanza no cambia: el modo AUTO→PROPOSE→SHADOW y el
Observer (solo observa) viven en el Pipeline; el orquestador no
veta nada, solo reordena y adapta. Ver STATUS.md para lo que
Qualtran NO cubre (equivalencia entre Bloqs, DQI kickmix como
Bloq) y lo que quedó sin cablear (`search`).

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

Solo si la estimación matemática alcanza la meta definida se da luz
verde. La meta por defecto es **GM estimada >= 30.00** (frente al
baseline 1.00 = la referencia), con la fórmula de ponderación de la
competencia: media geométrica de (referencia / propio) en las 3
tareas. La promoción significa "vale la pena gastar compilación
aquí", no "esto va a puntuar 30": la estimación es una proyección.

Qué exige la meta 30.00 (medido):

| Caso | DQI necesario | Ejemplo que lo logra |
|---|---|---|
| Química propia (1.0x) | ~1307x | Q=400, T=90,000 (GM ~30.5) |
| Química pública (10.27x) | ~127x | Q=892, T=195,000 (GM ~30.0) |

El filo es afilado a propósito: Q=400/T=95,000 da GM 29.99 y NO
promueve; Q=892/T=196,000 da 29.9977 y NO promueve. Por eso "400
cúbits" y "30.00" son la misma meta dicha dos veces (con química
propia): bajar de ~1,900 a ~400 cúbits es lo que pide la puerta.

### Fase 3 — Compilación pesada y artefactos

Solo lo promovido llega aquí. Se invierten las horas de cómputo
(4, 6 o las que permita el ciclo de Kaggle) y, si el verificador
oficial lo confirma, el artefacto queda guardado en un dataset con
el número de iteración y la calificación estimada:

```
runs/i120549-34.16/
  candidate.json   (el candidato: tarea, S, ratios, métricas)
  manifest.json    (iteración, GM estimada, SHA del código, fase)
```

La fase del manifiesto es `PROMOTED` al guardar, `PASS` o `FAIL`
tras la compilación pesada. Al terminar, el submission.zip se arma
solo desde los artefactos `PASS`.

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
pipe = Pipeline(proxy, PromotionGate(30.0), runs_dir="runs",
                time_budget_seconds=6 * 3600, source_commit="abc123")
res = pipe.run(mi_flujo_de_candidatos)
print(res.promoted, res.best_gm, res.artifacts, res.stopped)
```

El flujo de candidatos lo da el proponente (el lazo no inventa
mutaciones). Para reanudar, basta construir otro `Pipeline` con el
mismo `runs_dir`: lee `state.json` y sigue.

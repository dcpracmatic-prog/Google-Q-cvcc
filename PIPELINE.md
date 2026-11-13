# PIPELINE.md — cómo se orquestan los flujos (v2.5.0)

Guía para quien (o lo que) tenga que correr o modificar el repo sin
leer todo el código. Todo lo que dice aquí se puede comprobar en
`auto_mvp/` y en los tests de `tests/`.

## El comando único (v2.5: el modelo propone un lote, el prefilter ordena,
el peephole limpia, y cada corrida deja su reporte en `notes/`)

```bash
python -m auto_mvp.llm_auto --target-S 90000 --max-proposals 10
```

DIRECTIVA v2.0 de Arturo (2026-11-11 23:47 CST): fuerza bruta sobre
CIRCUITOS. El corredor propone circuitos reales, los valida con el
protocolo oficial (si no es válido, no cuenta), los mide simulando,
y repite hasta la meta o hasta el límite que ponga quien ejecuta.
Necesita kickmix + numpy (vienen del dataset de la competencia y
del entorno). El corredor v1.x (`python -m auto_mvp.auto --target
30`, solo stdlib) se mantiene por compatibilidad, superado.

Arturo (2026-11-12): el modelo de lenguaje GRATIS (Gemini por
defecto, Groq de respaldo) es el ESTRATEGA: lee la mejor semilla y
propone un LOTE de movimientos (K y seed) como JSON chico. Y NO se
construye .kmx en el Notebook: no cabe. Lo que sale son NADA MÁS
LAS SEMILLAS (JSON de kilobytes con la receta para reconstruir el
circuito). Directiva v2.3 (2026-11-12 00:56 CST): el prefilter
(`auto_mvp/prefilter.py`) ordena el lote en milisegundos (proxy +
MWIS) y solo los 1-2 mejores ganan el paso caro. El proxy es la
puerta, no el producto: el S que cuenta es el MEDIDO. Directiva
v2.4 (2026-11-12 01:56 CST): el operador lleva el PEEPHOLE
(`auto_mvp/circuits/operators/peephole.py`, la ruta Fast de GUOQ
bien hecha) como pre-paso determinista: limpia el .kmx antes del
SA (44 Clifford menos en la semilla invsqrt, S idéntico). Y el
DIALOG (`auto_mvp/circuits/dialog.py`) es la traza algebraica
correcta (cocientes del EEA + playback), verificada 200/200 contra
el EEA explícito.
circuito después). La llave va en el entorno (`GEMINI_API_KEY` o
`GROQ_API_KEY`; en Kaggle, como secreto del notebook); sin llave el
corredor sigue con sa_windows.

## El flujo del corredor con modelo (`auto_mvp/llm_auto.py`)

1. **Semilla medida.** El ledger (`runs/seed_ledger.json`) parte de
   la mejor semilla guardada en `runs/seeds/invsqrt/` (o de la base
   vendida, medida: S ≈ 100,568.5). La semilla es solo un JSON con
   su receta; el circuito se reconstruye desde su cadena de padres
   y se MIDE al arrancar (si no mide como la semilla, se vuelve a
   la base).
2. **Propuesta del modelo.** El estratega recibe la mejor semilla +
   lo ya probado y devuelve `{"K": 5|6|7, "seed": N, "reason": ...}`.
   Sin llave, con 429 o con JSON malo: sa_windows con K rotando.
3. **Construcción en temporal.** sa_windows construye el candidato
   en un directorio temporal, que se BORRA al terminar la ronda.
4. **Validación y medición.** Como en v2.0/v2.1: el verificador
   oficial vendido, con menos shots. Si es inválido, no cuenta.
5. **Solo sale la semilla.** Si mejora, se guarda SOLO su semilla
   (`runs/seeds/invsqrt/<id>.json`, kilobytes) con la receta
   (base + K + seed + budget). Ningún .kmx sale del Notebook.
6. **Repetición.** Solo paran la meta, el límite de propuestas o
   el presupuesto de tiempo. Nunca por estancamiento.

## El flujo del corredor de circuitos (`auto_mvp/circuit_auto.py`)

1. **Semilla medida.** El ledger (`runs/circuit_ledger.json`) parte
   de la semilla vendida (`auto_mvp/circuits/seeds/invsqrt_pub.kmx`),
   VERIFICADA RÁPIDA con el protocolo oficial: S ≈ 100,568.5
   (certificado 100,568.5). El mejor vive CON SU CIRCUITO
   (`runs/best/invsqrt.kmx`), no con números sueltos.
2. **Propuesta.** sa_windows (el operador real de Arturo,
   `auto_mvp/circuits/operators/sa_windows.py`) reescribe ventanas
   del mejor circuito con menos Toffolis, solo si la permutación es
   idéntica sobre los 2^k estados. K rota (5, 6, 7) y la semilla
   cambia por propuesta. Cada propuesta tarda ~30 s o más.
3. **Validación.** La verificación rápida (`auto_mvp/circuit.py`)
   usa el verificador oficial vendido de cada tarea, con menos
   shots: invsqrt (`fast_verify_invsqrt`, max_x=1024, ~0.1 s);
   DQI (`fast_verify_dqi`, 2,048 shots, ~37 s: registro S
   restaurado, ancillas a |0>, fase correcta, eps+ < 1/16);
   química (`fast_verify_dfthcsos`, 1 shot por dirección, ~28 s:
   los ANGLE_k simulados + métricas de la factorización). Si
   falla, el candidato es INVÁLIDO: no cuenta, se registra el
   motivo y se sigue. DQI hashea desde el archivo .kmb (el
   `to_file` del verificador falla en sandbox para circuitos
   tamaño DQI); química enlaza el fcidump desde el dataset en
   runtime.
4. **Medición.** El S sale de simular el circuito (Toffolis medios
   por shot + síntesis de rotaciones), no de una fórmula sobre
   números. Si el S medido es menor que el mejor, el candidato
   pasa a ser el mejor (con su .kmx copiado a `runs/best/`).
5. **Repetición.** Solo paran la meta (S <= target-S), el límite
   de propuestas o el presupuesto de tiempo que ponga quien
   ejecuta. Nunca se para por estancamiento.

## El comando v1.x (números, superado)

```bash
python -m auto_mvp.auto --target 30
```

Instalar: nada (solo stdlib; `dependencies = []`). Tests: `pytest`
(`pip install -e ".[dev]"`). El corredor no crea .kmb, no compila,
no envía nada a Kaggle. Encuentra la base (configuraciones y
métricas por tarea) que llega a la meta, y la entrega.

## El flujo del corredor (`auto_mvp/auto.py`, `run_auto`)

1. **Ronda 0.** El ledger (`runs/best_per_task.json`) parte del
   mejor envío conocido (semillas medidas en `seeds.py`). Si su
   combinación ya llega a la meta, se entrega sin correr nada.
2. **Rondas 1, 2, 3, ...** En cada ronda, por tarea (dqi, invsqrt,
   dfthcsos):
   - **(a) Mutador real** (`mutator.py`): propone candidatos mutando
     el grafo de costos de la semilla (reglas MORPH con evidencia
     medida, ventana SA, salto Lévy, MWIS). Cada candidato pasa por
     el **pipeline** (`pipeline.py`): proxy (S estimado por la
     fórmula oficial), puerta de promoción y filtro de integridad.
     Lo que mejora el S medido queda en el ledger.
   - **(b) Fuerza bruta** (`brute.py`): baja las variables de costo
     con operaciones aritméticas (restar 1/10/100, ×0.999...×0.5),
     **las tres tareas a la vez**, cada una por el mismo factor
     (la meta es el producto cruzado). Cerca del objetivo solo
     pasos finos. Conteos enteros; cada propuesta pasa los límites
     físicos del contrato oficial. Nunca entra al ledger: va
     marcada como proyectado.
   - Después de cada tarea se recalcula la combinación (lo mejor
     real o de fuerza bruta). Si la GM llega a la meta, se para.
3. **Entrega.** ZIP `runs/audit-base-<gm>.zip` (component.json +
   manifest.json por tarea, sin .kmb) + Notebook
   `runs/winners-gm-<gm>.ipynb` (los tres módulos ganadores, listos
   para la compilación pesada) + compensación global (qué tarea va
   rezagada y cuál compensa; la aceptación es la GM combinada).
   Si en `runs/` hay .kmb/.kmx, se cargan con Kickmix y el resultado
   va en `kmb_validation`.
4. **Paro.** Solo paran los límites que ponga quien ejecuta
   (`--max-rounds`, `--time-budget`) o llegar a la meta. Nunca se
   para por estancamiento. La única otra parada es la frontera
   aritmética (pisos T=1, Q=1): un hecho matemático, no rendirse.

## Orquestación en serie (`auto_mvp/serial.py`, `run_serial`)

Corre las tres tareas **en serie con el mismo ledger** y acepta el
balance global de forma automática: si una tarea va rezagada pero
las otras dos compensan, la combinación se acepta y queda registrado
quién va rezagado y quién compensa (`compensation_record`, usado
también por `run_auto`). Una sola pasada, sin rondas ni fuerza
bruta. El Notebook se exporta si se pide (`export_notebook=True`).

## El pipeline por candidato (`auto_mvp/pipeline.py`)

`Pipeline.run(stream)`: proxy → puerta → integridad → ledger.
El proxy estima el S con la fórmula oficial (`vqcc/costs.py`).
La puerta exige mejora real del S. El filtro de integridad
(`integrity.py`) rechaza módulos que rompen el contrato. El
Observer (`observer.py`, solo observa, nunca veta) lee los trials
del ledger y reporta el régimen (ESTABLE/MODERADO/RUIDOSO/
CONFLICTO/INSUFICIENTE); el corredor no lo instancia por defecto.

## El combiner (`auto_mvp/combiner.py`)

`BestLedger`: mejor componente por tarea entre corridas.
`combine(ledger, target)`: GM, si llega, y lo que falta por tarea
(`required_S`). `export_base_zip` / `export_audit_zip`: el ZIP de
la base. `export_winner_notebook` (`notebook.py`): el .ipynb.

## Verificación (`auto_mvp/vqcc/verify.py`, `auto_mvp/packaging.py`)

- `verify.py`: verificación OFICIAL de un .kmb/.kmx con kickmix
  (invsqrt o DQI) y de la química con sus verificadores. Cara: solo
  se corre cuando hay un circuito real que verificar.
- `packaging.py`: valida la ESTRUCTURA de un submission
  (nombres exactos, un solo invsqrt/dqi, angles consecutivos, claves
  del .npz). No verifica circuitos.

## Aceleración nativa (`auto_mvp/accel.py`)

SpMM SIMD, Dijkstra FIELD y fricción SWAR. Fuentes vendidas en el
repo (`auto_mvp/native/`). Se compilan con cc/c++ si hay
compilador; si no, fallback en Python puro con la misma semántica.
`available()` dice qué cargó y por qué. El corredor no la usa en
su lazo actual (no hay trabajo pesado ahí: el proxy y la caminata
son aritmética trivial); está disponible para el trabajo de grafos
cuando el motor opere sobre circuitos reales.

## Qué NO hace el corredor (límite honesto, v1.5.0)

No construye circuitos ni los simula: optimiza métricas y grafos
de costos, no .kmb. El S de un candidato sale de la fórmula sobre
sus métricas, no de simular un circuito. La reorientación a
optimización a nivel circuito (operadores reales como sa_windows
sobre .kmx, con verificación oficial por candidato) es trabajo
pendiente, dirigido por Arturo. Ver `STATUS.md`.

# PIPELINE.md — cómo se orquestan los flujos (v2.0.0)

Guía para quien (o lo que) tenga que correr o modificar el repo sin
leer todo el código. Todo lo que dice aquí se puede comprobar en
`auto_mvp/` y en los tests de `tests/`.

## El comando único (v2.0: circuitos)

```bash
python -m auto_mvp.circuit_auto --target-S 90000 --max-proposals 10
```

DIRECTIVA v2.0 de Arturo (2026-11-11 23:47 CST): fuerza bruta sobre
CIRCUITOS. El corredor propone circuitos reales, los valida con el
protocolo oficial (si no es válido, no cuenta), los mide simulando,
y repite hasta la meta o hasta el límite que ponga quien ejecuta.
Necesita kickmix + numpy (vienen del dataset de la competencia y
del entorno). El corredor v1.x (`python -m auto_mvp.auto --target
30`, solo stdlib) se mantiene por compatibilidad, superado.

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
3. **Validación.** La verificación rápida (`auto_mvp/circuit.py`,
   `fast_verify_invsqrt`) usa el verificador oficial vendido
   (`auto_mvp/circuits/verifiers/verify_submission_invsqrt.py`)
   con menos shots (max_x=1024, 1 shot por x, ~0.1 s): registro x
   de 22 cúbits, scratch a |0>, x restaurado, error de fase dentro
   de tolerancia. Si falla, el candidato es INVÁLIDO: no cuenta,
   se registra el motivo y se sigue.
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

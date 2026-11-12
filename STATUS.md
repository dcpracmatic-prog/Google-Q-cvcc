# STATUS.md — estado del repo (v2.0.0)

Última actualización: 2026-11-11. Todo lo que dice aquí está
verificado en sandbox y/o en Kaggle; lo que no, dice que no.

## Versión

- **v2.0.0** (DIRECTIVA v2.0 de Arturo, 2026-11-11 23:47 CST):
  fuerza bruta sobre CIRCUITOS. `auto_mvp/circuit.py` (cargar,
  contar, verificación rápida con el protocolo oficial, proponer
  con sa_windows) + `auto_mvp/circuit_auto.py` (corredor:
  proponer → validar → medir → repetir). Semilla, operador y
  verificador vendidos en `auto_mvp/circuits/`.
- Suite de tests: ver la última corrida en sandbox
  (`pytest tests/`). La v1.5.0 pasó 154/154.

## Verificado (v2.0)

- La verificación rápida reproduce el S certificado de la semilla
  invsqrt: S=100,556.7 (max_x=256) y S=100,585.4 (max_x=1024) vs
  certificado 100,568.5 (0.01–0.02% de error), en ~0.1 s, con el
  protocolo oficial (mismo chequeo, menos shots).
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

## Límite honesto (lo que NO es, v2.0)

- v2.0 cubre **invsqrt** de punta a punta. DQI y química usan la
  misma forma, pero sus semillas viven en el dataset (dqi_ref.kmx
  pesa 1.5 GB y no cabe en el repo; los angle_k .kmb también) y
  sus verificadores rápidos están pendientes.
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

- La DIRECTIVA v2.0 (2026-11-11 23:47 CST) reorientó el corredor a
  circuitos: v2.0 la cumple para invsqrt. Pendientes DQI y química
  con la misma forma (sus semillas viven en el dataset: dqi_ref.kmx
  1.5 GB, angle_k .kmb; sus verificadores rápidos pendientes).
- La decisión pendiente de 2026-11-11 sobre los 2 PDFs borrados
  por el commit c7dbb058 sigue abierta.

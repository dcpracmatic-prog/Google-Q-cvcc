# STATUS.md — estado del repo (v1.5.0)

Última actualización: 2026-11-11. Todo lo que dice aquí está
verificado en sandbox y/o en Kaggle; lo que no, dice que no.

## Versión

- **v1.5.0** en main (pyproject `1.5.0`). Cambios: Notebook de
  ganadores + compensación global en `run_auto`; aceleradores
  nativos vendidos en el repo; `PIPELINE.md` y este archivo.
- Suite de tests: ver la última corrida en sandbox
  (`pytest tests/`). La v1.4.0 pasó 148/148.

## Verificado

- `python -m auto_mvp.auto --target 30` da GM 30.005566491649372
  (8 rondas, bit a bit igual en sandbox y en Kaggle, kernel
  144519117 v2, 2026-11-11). ZIP + Notebook de la entrega.
- Las tres tareas mejoran a la vez (reparto equilibrado): invsqrt
  Q=52 S=79,447; DQI Q=740 T=429,936 S=2.893e11; química Qtot=546
  Ttot=25,901 λ_eff=19.361. Conteos enteros; λ_eff sobre el piso
  de Lambda implicada (19.31).
- Los verificadores oficiales importan y dan los números exactos
  (rotation_t_count(2^-24)=18.74, DQI R(0.001188)=1.22901).
  Kickmix simula un circuito real.
- Aceleradores nativos: spmm, field, swar cargan desde
  `auto_mvp/native/` (gcc presente). Fallback en Python puro si
  no hay compilador.
- La Skill tiene 12 operaciones y `functions.json` tiene 12
  entradas: coinciden. `auto_mvp/__init__.py` no tiene nombres
  duplicados en `__all__` (119 entradas, sin repetidos).

## Límite honesto (lo que NO es)

- El corredor optimiza **métricas y grafos de costos**, no
  circuitos. El S de un candidato sale de la fórmula oficial
  sobre sus métricas, no de simular un circuito construido. El
  éxito del corredor es tautológico por diseño: pone los números
  para que lleguen a la meta, así que llegan. **No mide nada real.**
- La base que entrega son **presupuestos de costo** (números),
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

- Reorientar el corredor a optimizar CIRCUITOS (o su receta
  completa de construcción), con el S medido del circuito
  construido: integrar los operadores reales (sa_windows sobre
  .kmx, reglas MORPH sobre Qualtran, verificación oficial por
  candidato) y decidir qué se vende en el repo (Qualtran,
  kickmix) y qué viene del dataset de la competencia.
- La documentación legible (STATUS.md, PIPELINE.md) se restauró
  en v1.5.0. La decisión pendiente de 2026-11-11 sobre los 2 PDFs
  borrados por el commit c7dbb058 sigue abierta.

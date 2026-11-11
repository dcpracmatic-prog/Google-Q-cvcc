# SPEC_AUTO_MVP.md — especificación v0.0.1 y qué se implementó

La especificación AUTO_MVP v0.0.1 de Arturo (2026-11-11) está
reproducida aquí en su forma original y con la revisión que se hizo
de ella. Este archivo es el contrato entre la spec y la v0.3.0.

## La especificación (resumen fiel)

Ciclo de vida: `[Ingesta] → [Evaluación Multiobjetivo] → [Auditoría
TERM_U] → [Mutación JSONln + CVV] → [Convergencia / MVP]`.

1. **Ingesta y Despliegue.** El orquestador recibe el estado inicial,
   configura el presupuesto de tiempo/intentos según la meta
   porcentual (ej. +50%) y carga el baseline verificado más reciente
   (ej. Estado del Paso 49, Q=5,630, C/B 180/180).
2. **Evaluación Multiobjetivo.** Mérito compuesto
   α·Q² + β·N_Toffoli + γ·T frente al rendimiento lógico. Filtro de
   integridad obligatorio: equivalencia estructural (sigma, dreg,
   alpha, slots C/B); si un candidato reduce Q pero desincroniza el
   primer shot o rompe el invariante, se rechaza de inmediato.
3. **Auditoría y Veto Bicameral (Tensor TERM_U).** El motor
   morfogenético y el tensor de estabilidad analizan la telemetría;
   si hay deriva de fase, ruido excesivo o anomalías en el working
   set transitorio, veto drástico y re-apuntamiento al atractor
   seguro de memoria.
4. **Mutación y Registro (JSONln + CVV).** Si el candidato supera el
   puntaje histórico y cumple el contrato, se genera un registro
   estructurado; cada hito se sella con un CVV (hash del estado
   anterior, checksum actual, firma del validador bicameral).
5. **Convergencia y Entrenamiento Algebraico Implícito (MVP).**
   Escalado temporal adaptativo según la meta; entrenamiento
   algebraico implícito que ajusta matrices internas y andamios;
   salva asíncrona de récords: cada mejor se congela de inmediato
   como MVP temporal certificado.

Registros de ejemplo (JSONln): baseline con `score: 5630.0`
(INGEST_BASELINE, LOCKED_BASE); mejora con `score: 3420.2`
(delta −39.2%, CVV con prev_hash/checksum); regresión con
`score: 1990.0` (REJECTED_REGRESSION, veto
SIGMA_DIVERGENCE_STEP_51_SIMULATION, ROLLED_BACK); convergencia con
`score: 1414.1` (delta −74.8%, MVP_CONVERGENCE, certified).

## Revisión: qué estaba bien, qué estaba mal

**Acierta y se implementó tal cual:**

- El filtro de integridad obligatorio (sigma/dreg/alpha/C/B por
  candidato) — `auto_mvp/integrity.py`.
- La bitácora con cadena de hashes (CVV) — `auto_mvp/cvv.py`.
- El checkpoint inmediato de cada mejor — `auto_mvp/checkpoint.py`.

**Corregido antes de construir:**

- El "score" de los ejemplos es **Q, no S**. 5630.0 → 1414.1 con
  delta −74.8% es reducción de qubits, no mejora de puntaje. El S
  oficial DQI es R·Q²·T: con Q=1,414 sería ~3.24e12, no 1414.1.
  En la v0.3.0 `score` es siempre el S oficial.
- El mérito α·Q²+β·Toffoli+γ·T **no es el S oficial**: una suma
  ponderada ordena los candidatos distinto que S. En la v0.3.0 esa
  suma solo existe como `proxy_merit` (ranking en el proxy), nunca
  como criterio de aceptación.
- El CVV sin clave es **cadena de hashes, no firma**: detecta
  alteraciones, no prueba autoría. La v0.3.0 lo dice así en el
  código y en el README. El hash `dead...beef` del ejemplo era un
  placeholder; aquí todos los hashes son sha256 reales.
- El filtro de integridad solo atrapa un paso 51 si **envuelve la
  construcción del circuito**, no solo al mutador. La v0.3.0 tiene
  `CircuitConstructionGuard` para eso, y el costo de verificar el
  sigma por candidato (una simulación n=70 completa) se cuenta en
  el presupuesto de la meta.

**No definido, no implementado (queda fuera a propósito):**

- Fase 3: "motor morfogenético", "tensor TERM_U", "atractor seguro".
  Sin fórmula ni umbral, no es implementable. El veto que sí existe
  es el de la v0.2.1 con números: salud < 0.5 o 3 fallos seguidos.
  Además MORPH, por regla de Arturo, solo lee después de que todo
  corrió y nunca gobierna: el veto vive en el lazo.
- Fase 5: "entrenamiento algebraico implícito". Sin algoritmo (qué
  matrices, con qué regla), no se construye. La búsqueda neuronal en
  química ya se cerró como negativo medido; un entrenamiento nuevo
  necesita su algoritmo escrito antes de prometer nada.
- El "escalado temporal" de la fase 5 sí se implementó en forma
  concreta (`goal.py`): el presupuesto crece solo con mejoras reales
  y tiene techo duro.

## Qué se implementó de la propuesta proxy (2026-11-11)

La propuesta de "evaluación proxy en el espacio de metadatos / poda
temprana" se solapa con la v0.3.0 y se implementó junta en
`auto_mvp/proxy.py`: el validador como filtro de entrada (topes
duros de qubits/Toffolis y contrato oficial sobre las métricas),
estimación de S desde metadatos antes de construir, y calibración
del margen con sonda parecida a la carga (p95 acotado a 0.25, la
misma regla de v0.2.1). Condiciones respetadas: el proxy incluye
integridad lógica (la criba por costo sola no detectó el paso 51) y
el proxy nunca acepta, solo rechaza y ordena.

## Correspondencia fases → código

| Fase spec | Implementación v0.3.0 |
|---|---|
| 1. Ingesta | `AutoMvp.run`: baseline sellado (INGEST_BASELINE, LOCKED_BASE) |
| 2. Evaluación | `proxy.evaluate` (antes de construir) + `LocalVerifier` (S oficial) |
| 3. Auditoría | `IntegrityFilter` + veto de salud v0.2.1 |
| 4. Mutación + CVV | `CvvChain.append` en cada aceptación y cada veto |
| 5. Convergencia | `Goal`/`GoalTracker` + `Checkpoint.save` en cada mejor verificado |

## Formato del submission.zip (v0.9.0)

El formato oficial (guía VQCC 2026-11-06 + verificadores en disco;
la v0.3.0 falló por duplicados en otras rutas, así que el formato
ahora vive en el repo, no solo en memoria). El ZIP lleva,
directamente en la raíz (sin directorio raíz extra):

```
invsqrt.kmb  (o invsqrt.kmx, UNO solo)
dqi.kmb      (o dqi.kmx, UNO solo)
dfthcsos/
    angle_k_0.kmb  (o .kmx)
    angle_k_1.kmb
    ...            (consecutivos desde 0, SIN huecos)
    submission.npz (claves: U, W, H2_I, H1_I, Hsym_lower, tree_edges)
```

Reglas (fail-closed, en `auto_mvp/packaging.py`):
- Sin directorio raíz extra ni archivos fuera del formato.
- Sin duplicados (ni el mismo archivo en dos rutas, ni dos entradas
  con el mismo nombre dentro del ZIP).
- Exactamente un invsqrt y un dqi (.kmb o .kmx, no los dos).
- angle_k consecutivos desde 0, sin huecos, uno por índice.
- submission.npz con las 6 claves (las extra se avisan, no fallan).
- `build_submission_zip` arma el ZIP con la estructura correcta y
  lo valida; si no pasa, lo BORRA (no queda un ZIP malo que se
  pueda enviar por error).
- `submission_ready` da READY solo si la puerta fail-closed (los
  tres verificadores en modo full) Y el formato pasan.

El validador revisa el FORMATO, no el contenido: que un circuito
sea correcto, que la química cumpla sus umbrales o que el S sea
bueno es trabajo de los verificadores oficiales.

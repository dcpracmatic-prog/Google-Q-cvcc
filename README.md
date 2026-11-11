# AUTO_MVP — núcleo autónomo de optimización para VQCC

Optimización de circuitos para la competencia Google Quantum AI —
Verifiable Quantum Circuit Compilation (VQCC), con la lección del
paso 51 como regla: **ninguna reducción de recursos puede romper la
equivalencia lógica**.

> **Repo privado mientras la competencia esté abierta.** El trabajo
> VQCC no se publica hasta que Arturo decida el momento estratégico.

## Qué es

AUTO_MVP v0.3.0 es el corrector v0.2.1-vqcc con tres piezas nuevas
que la especificación AUTO_MVP v0.0.1 pedía y que sí se pueden
construir:

| Pieza | Qué hace | Módulo |
|---|---|---|
| Filtro de integridad | Revisa sigma, C/B, dreg, alpha y temporales por candidato; veta la regresión con forma de paso 51 aunque tenga mejor S | `auto_mvp/integrity.py` |
| Bitácora CVV | Cadena de hashes de los récords (tamper-evident, no firma) | `auto_mvp/cvv.py` |
| Checkpoint | Guarda de inmediato cada mejor verificado (escritura atómica) | `auto_mvp/checkpoint.py` |
| Meta con regla de paro | Meta en S o en %, presupuesto que crece solo con mejoras, paro con motivo | `auto_mvp/goal.py` |
| Proxy de metadatos | Criba variantes por anchos, densidades y topes antes de construir | `auto_mvp/proxy.py` |
| Orquestador | El ciclo de 5 fases sobre los componentes v0.2.1 | `auto_mvp/mvp.py` |
| GF(2^12) y sigma con escala | El sigma del circuito es k × mónico: se compara en forma mónica | `auto_mvp/gf212.py`, `auto_mvp/integrity.py` |
| Caché de verificación | Un candidato idéntico no se vuelve a verificar | `auto_mvp/cache.py` |
| Rotación del ledger | El ledger en disco rota a 1 MB | `auto_mvp/healing/ledger.py` |

El mérito de aceptación es siempre el **S oficial** (DQI: R·Q²·T;
invsqrt: Q·C; química: λ_eff·T·Q). La suma ponderada de la
especificación (α·Q²+β·Toffoli+γ·T) solo existe como `proxy_merit`:
ordena, nunca decide.

## Estructura

```
auto_mvp/
  healing/        paquete genérico de auto-reparación v0.1.0 (intacto)
  vqcc/           harness v0.2.1: contratos, costos, detector,
                  verificador local, ledger, búsqueda, calibración
  integrity.py    filtro + guardia de construcción (NUEVO v0.3.0)
  cvv.py          cadena de hashes CVV (NUEVO)
  checkpoint.py   checkpoint atómico (NUEVO)
  goal.py         meta y regla de paro (NUEVO)
  proxy.py        proxy de metadatos (NUEVO)
  mvp.py          orquestador AUTO_MVP (NUEVO)
tests/            4/4 humo + 5/5 harness + 9/9 v0.2.1 + nuevos v0.3.0
examples/         ejemplo_searchloop_v021.py, ejemplo_auto_mvp_v030.py
SPEC_AUTO_MVP.md  la especificación v0.0.1 y qué se implementó de ella
```

## Pipeline por fases (6 h / 24 h)

Ver `PIPELINE.md` y `auto_mvp/pipeline.py`. Tres fases:

1. **Filtro rápido:** el proxy evalúa variantes paramétricas en
   milisegundos y descarta lo inviable sin compilar nada.
2. **Promoción por beneficio real:** solo si la GM estimada bate el
   mejor envío (por defecto **> 23.94667**) se da luz verde. La
   puerta mide contra los componentes del mejor envío (invsqrt
   20.65x, DQI público 64.76x, química pública 10.27x): batirlo
   exige DQI ~64.76x. La meta 30.00 no es alcanzable con el enfoque
   actual (producto 27,000 vs 13,732; solo por DQI, T −49.1%).
3. **Compilación pesada y artefactos:** lo promovido se guarda como
   `i<iteración>-<puntaje>` (ej. `i120549-34.16`) y solo el
   verificador oficial lo confirma.

El pipeline corre en bloques con presupuesto de tiempo y se reanuda
desde `runs/state.json`. El notebook lo inicializa con
`auto_mvp/kaggle_init.py`: los datos de la competencia son de solo
lectura (`/kaggle/input`), el código viene del repo (clon o snapshot
con su SHA), y todo lo producido va a `<working>/runs/`.

## Uso rápido

```python
from auto_mvp import AutoMvp, Goal, MetadataProxy
from auto_mvp.vqcc import dqi_spec

spec = dqi_spec()
goal = Goal(baseline_S=spec.baseline_S, improvement_pct=50.0,
            base_trials=10, max_trials=20, patience=5)
proxy = MetadataProxy(spec, hard_caps={"max_qubits": 2000}, margin=0.10)
mvp = AutoMvp(spec, mi_proponente, goal, proxy=proxy, workdir="./run1")
res = mvp.run()
print(res.best_S, res.integrity_vetoes, res.proxy_rejected, res.stop_reason)
```

El proponente es un protocolo: recibe el spec, el mejor candidato y
la evidencia, y devuelve un candidato (dict con `metrics`, y
opcionalmente `integrity` y `meta`). El lazo no inventa mutaciones.

## Correr los tests

```bash
python3 -m pytest tests/ -q
# o sin pytest:
python3 tests/test_auto_mvp_v030.py
python3 examples/ejemplo_auto_mvp_v030.py
```

Solo stdlib: no hay dependencias.

## Reglas honestas

- **Proyectado no es medido.** El cribado por costo guía la
  búsqueda; solo el verificador oficial corona un mejor verificado.
  `best_S` y `best_verified_S` viven por separado.
- **Sin evidencia no hay verificación.** Un candidato con circuito
  real debe traer evidencia de integridad; sin ella solo puede ser
  mejor proyectado.
- **El CVV no es una firma.** Es una cadena de hashes: detecta que
  alguien alteró un récord, no prueba quién lo escribió.
- **El proxy no acepta.** Rechaza lo inviable y ordena el resto;
  la aceptación la deciden el verificador y el filtro de integridad.
- **El filtro envuelve la construcción.** El paso 51 nunca pasó por
  el lazo de búsqueda; por eso la guardia vive en el constructor.

## Qué NO está implementado (a propósito)

Ver `SPEC_AUTO_MVP.md`: motor morfogenético, tensor TERM_U con
atractor y entrenamiento algebraico implícito no tienen fórmula ni
algoritmo en la especificación, así que no se construyeron. Tampoco
se inventó nada para tapar el hueco.

## Versiones

- **v0.1.0** — paquete genérico de auto-reparación (detect/spec/
  validate/ledger/verify/heal).
- **v0.2.0-vqcc** — reorientación a VQCC (contratos, costos, detector,
  verificador local, ledger, búsqueda).
- **v0.2.1-vqcc** — calibración por sonda estilo DSP, veto de salud,
  `best_verified_S` separado.
- **v0.3.0** — AUTO_MVP: filtro de integridad, CVV, checkpoint,
  meta con regla de paro, proxy de metadatos, orquestador.
- **v0.3.1** — Mejoras: sigma consciente de escala (GF(2^12) mod
  0x1053, el campo del DQI; k=2314 en el shot 0 del paso 51), caché
  de verificación por hash de parámetros, rotación del ledger a
  1 MB, y el orquestador guarda la cadena CVV y el ledger en el
  directorio del run.
- **v0.3.2** — Pipeline por fases (6 h / 24 h): filtro rápido por
  proxy, puerta de promoción por GM estimada (bate el mejor envío
  23.94667), artefactos `i<iter>-<score>`, reanudación por estado, y
  `kaggle_init` con la separación inmutable / código / trabajo.
- **v0.5.0** — **meta_mvp (parámetro absoluto) + ventaja pura:**
  la lógica de metas acepta `meta_mvp` (el puntaje que se le exige
  al sistema, ej. 30.00); la barra de parada la dicta ese umbral,
  no un envío anterior (`Goal.for_meta_mvp`, `PromotionGate(meta_mvp)`,
  `Pipeline(meta_mvp=...)`, parada por meta solo cuando un candidato
  REAL alcanza la meta — un target es una hipótesis, no el circuito).
  `pure_advantage` evalúa la mejora real (Toffolis, cúbits, T) frente
  al baseline oficial y la traduce al puntaje con la fórmula de la
  competencia. **Lab incorporado:** `numeric_lab` (port stdlib del
  prefiltro Chebyshev del Lab: 28 candidatos, 17 factibles, mejor
  grado 7 / 1 segmento, verificado contra el original numpy) con
  gancho en el proxy, y `fail_closed_gate` (solo los tres
  verificadores en modo full arman el submission.zip). **LOGIC_CORE
  MWIS incorporado** (`mwis.py`, port fiel del núcleo v4): la
  selección por lado es MWIS con peso = ganancia en S (la unión
  D, I, G, L, M gana más que el MIS voraz; incluye G_b17). Sin
  directiva, la puerta sigue promoviendo lo que bate 23.94667.
- **v0.4.0** — MaxCut (port fiel del C++ de Arturo) partiendo el
  grafo de conflictos; calibración DCP en el pipeline (margen,
  paciencia y presupuesto de la sonda); Observer con régimen
  derivado de la bitácora (sin parámetro condition, sin veto);
  modo AUTO→PROPOSE→SHADOW en el pipeline. **Constantes
  corregidas:** la puerta mide contra el mejor envío
  (BEST_SUBMISSION_S: DQI público 3.7676e11, química pública
  3.268e8) y promueve lo que bate 23.94667; 30.00 no es alcanzable
  con el enfoque actual (producto 27,000 vs 13,732).
- **v0.3.3** — Corrección del init: la copia vendida puede ser el
  paquete mismo o el directorio que lo contiene (el notebook lleva
  `auto-mvp-vendored/auto_mvp/`); el test del init usa el layout del
  notebook.

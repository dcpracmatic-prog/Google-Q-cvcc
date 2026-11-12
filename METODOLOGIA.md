# METODOLOGÍA — Circuitos y protocolo de cada métrica de rendimiento

Cómo se saca cada número de rendimiento del repo, con qué circuito,
con qué fórmula y con qué evidencia. Nada se afirma sin decir de dónde
salió ni cómo se calculó. La versión ejecutable está en
`auto_mvp/vqcc/metrics.py` (`trace()`, `trace_all()`, `report()`).

**Regla:** una métrica es **medida** solo si viene de una medición
(verificador oficial o kickmix) con su evidencia (kernel, shots,
fallos). Si viene de un diseño sin verificar, es una **proyección** y
se marca como tal. Una proyección nunca entra al submission.zip: la
puerta fail-closed solo arma el zip con los tres verificadores
oficiales en PASS.

## 0. El puntaje total (las tres tareas juntas)

```
GM = (ratio_invsqrt * ratio_dqi * ratio_quimica)^(1/3)
ratio_tarea = S_ref / S_propio
```

La referencia puntúa 1.0. El mejor envío (ref 58076483) puntúa
**23.94667** = (20.65 × 64.76 × 10.27)^(1/3) = (13,732)^(1/3).
La meta absoluta del sistema es **30.00** (producto 27,000).

| Tarea | S_ref (puntúa 1.0) |
|---|---|
| invsqrt | 2,076,774 |
| DQI | 2.44e13 |
| dfthcsos (química) | 3,355,599,588.32 |

## 1. invsqrt — S = Q × C, C = Toffoli + T/4

### Circuito (mejor envío, propio y certificado)

| Campo | Valor |
|---|---|
| Archivo | `sandbox-run/invsqrt/invsqrt_final_v1.kmb` |
| sha256 | `45825861…` |
| Q | 62 (registro `x` exactamente 22 qubits, 40 scratch) |
| Toffolis | 1,495 |
| S medido | **100,568.5** (ratio **20.65×**) |

### Protocolo (cómo se midió)

1. **Verificador oficial** en Kaggle: kernel
   `dcpracmatic/official-verifier-invsqrt`, id **144153668**.
2. **Cobertura:** todos los x de 1 a 3,133,452 × 64 shots =
   **200,540,928 shots**, **0 fallos** dentro de
   tol(x) = 2^-24 · β/√x.
3. **El S que se reporta es el puntaje oficial** (Toffolis medios por
   shot, 1,325.48 de media), no el Q×C estático (110,931). Por eso
   100,568.5 < 110,931: el verificador cuenta lo que realmente se
   ejecuta por shot, no el máximo.

### Fórmula (con síntesis de rotaciones, v0.9.1)

```
S = Q * C,  C = Toffoli + T/4
T incluye la síntesis de rotaciones Z_POW finas:
  rotation_t_count(eps) = 0.56*log2(1/eps) + 5.3   (por rotación)
  eps sale del margen que deja el rel_error:
  margen >= (2^-24 - rel_error) / sqrt(3,133,452)
```

El verificador oficial cobra esa síntesis. Ignorarla subestima el
costo: con 37 rotaciones, la referencia da S 2,077,168.5 (a 0.019%
del S oficial 2,076,774); sin la síntesis daría 2,011,100 (3.2% por
debajo: ese era el hueco). Rotaciones sin `rel_error`, o con
`rel_error >= 2^-24`, se rechazan (fail-closed). Sin rotaciones, la
fórmula es la de siempre (`auto_mvp/vqcc/costs.py::s_invsqrt`).

## 2. DQI — S = R(eps+) × Q² × T

### Circuito (mejor envío, público híbrido)

| Campo | Valor |
|---|---|
| Archivo | `sandbox-run/public-dqi/dqi.kmb` |
| Autor | jday96314/QuantumAI (público) |
| Q | 892 (840 síndrome + 52 trabajo) |
| T media | 398,176 por shot (T estática 453,312) |
| eps+ | 0.000866 (piso, 0 fallos) |
| R | 1.19126 |
| S medido | **3.7676e11** (ratio **64.76×**) |

### Protocolo (cómo se midió)

1. **Mejor envío** (ref 58076483), puntaje público 23.94667.
2. **Verificación:** 102,400 shots, **0 fallos** (eps+ en el piso).
3. **El circuito es un híbrido clásico-cuántico**, no un circuito
   puro: trabaja in situ sobre el síndrome S, descarga intermedios
   a 104,140 bits clásicos, usa 114,752 HMR (Hadamard+Measure+Reset)
   y solo 82 inversiones (contra 4,095 de Forney en la referencia).
   Por eso su Q es 892 y no 1,893.

### Fórmula

```
S = R(eps+) * Q^2 * T_media
R(eps) = ln2 / -ln(1/2 + 2*sqrt(eps))
eps+ = Clopper-Pearson con confianza 1 - 2^-128
```

**Verificación de la traza** (`metrics.trace("dqi", "publico")`):
R recalculado desde eps+=0.000866 da 1.19125 (reportado 1.19126) y
S recalculado da 3.774e11 (reportado 3.768e11). La diferencia (0.17%)
es redondeo en T_media (398,176 es una media por shot).

### Mapa de fases (medido del .kmb, INFORME_MEJORA_30.md)

El costo T del DQI público, contado fase por fase del `.kmb`
(CCX+CCZ+CSWAP+CCZ_IF por intervalo de `tags.json`, cierre exacto
453,312; script `medir_T_fases.py`):

| Fase | T estática | % |
|---|---|---|
| unextract | 121,039 | 26.70 |
| unconvert | 76,105 | 16.79 |
| padded_unsynthesis | 58,645 | 12.94 |
| extract | 61,855 | 13.65 |
| convert | 59,489 | 13.12 |
| scan | 44,275 | 9.77 |
| synthesis | 31,904 | 7.04 |

**Los espejos** (unextract + unconvert + padded_unsynthesis, las fases
que restauran el síndrome S) son **255,789 T = 56.43%** del total.
Dentro de unextract, el bloque mayor es **companion: 50,984 T
(11.25%)**. Para 30.00 hay que bajar la T media de 398,176 a 202,200
(−49.2%), o sea, eliminar el 87.2% del espejo. Ver la traza completa
en `INFORME_MEJORA_30.md`.

### Otros módulos DQI (para comparar, no para el mejor envío)

| Módulo | Q | T | S | Estado |
|---|---|---|---|---|
| Propio Toom-4+V1+E2 | 1,899 | 4,477,394 | 1.923348e13 (1.269×) | Medido, verificador oficial 102,400 shots, 0 fallos (kernel 144398281) |
| Propio Toom-3+V1+E2 | 1,899 | 4,652,027 | 1.99836e13 (1.223×) | Medido, verificador oficial 102,400 shots, 0 fallos (kernel 144307906) |
| BM+Forney Montgomery b=17 | 1,414 | 1,315,731 | 3.2331e12 (7.55×) | **Proyección**: Chien completo medido en kickmix; el .kmb completo y el verificador oficial están pendientes |
| BM+Forney base (diseño) | 1,414 | 1,511,522 | 3.714e12 (6.57×) | **Proyección** (cost_model exacto; R=1.22901 medido a 20,000 shots, Gate 0) |

## 3. Química (dfthcsos) — S = λ_eff × Ttot × Qtot

### Circuito (mejor envío, pública)

| Campo | Valor |
|---|---|
| Factorización | pública (9,143,40) |
| λ_eff | 47.037 |
| S medido | **326,800,029.87** (ratio **10.27×**) |

### Protocolo (cómo se midió)

1. **Mejor envío** (ref 58076483).
2. **Advertencia: margen CERO.** Su error_2 y su E_gap están
   exactamente en el límite del contrato. Si el conjunto privado
   la saca de los límites, todo el envío se rechaza.

### Fórmula y contrato

```
S = lambda_eff * Ttot * Qtot
lambda_eff = sqrt(E_gap * (2*Lambda - E_gap))
Contrato: error_1 <= 20 mHa, error_2 <= 20 mHa, Lambda > 49.0,
          E_gap > 3.914898 Ha, cada Angles_k <= 128 qubits
```

### Baseline propia (para comparar)

| Campo | Valor |
|---|---|
| Factorización | baseline (65,60,60), starter kit |
| λ_eff | 49.301369 |
| error_2 | 18.6396 mHa (margen 1.36 mHa al límite de 20 mHa) |
| S medido | **3,355,599,588.32** (ratio **1.0×**, igual a la referencia) |
| Verificación | verificador del starter kit, sandbox y Kaggle con el mismo puntaje y el mismo sha256 (kernel `dcpracmatic/dfthc-sos-baseline`, id 144333524, 254,464 shots) |

La química propia **no mejora** la referencia (ratio 1.0×). Para
llegar a 30.00 solo por química harían falta 20.19× (S=166M), y el
techo del pipeline starter es ~1,041M.

## 4. Cómo se combinan (la guía, v1.0.0)

`auto_mvp/combiner.py` (BestLedger + combine): guarda el mejor
componente por tarea **entre corridas** (sembrado con el mejor envío
medido, GM 23.94676; solo mejora; cada reemplazo queda en el historial
con su procedencia: corrida, iteración, medido o proyectado).
`combine(ledger, target_gm)` junta el mejor de cada tarea y dice si
la combinación llega al objetivo y, si no, cuánto le falta a **cada**
tarea (el S que cada una necesitaría con las otras dos fijas).

Para 30.00, con las otras dos en su mejor envío:
- DQI necesitaría S 1.9162e11 (127.3×).
- invsqrt necesitaría S 51,149.
- Química necesitaría S 166M (20.19×).

Cuando la combinación alcanza el objetivo, `export_audit_zip`
exporta los tres componentes en un ZIP de auditoría (estructura +
código ejecutable + manifiesto con procedencia). Ese ZIP es la base
para auditar y diseñar el submission real; **no** es el
submission.zip de la competencia (ese lo arma la puerta fail-closed
con los .kmb y el .npz, solo con los tres verificadores en PASS).

## 5. Qué es medido y qué es proyección (resumen)

| Métrica | Estado | Evidencia |
|---|---|---|
| invsqrt S 100,568.5 | Medido | Verificador oficial, 200,540,928 shots, 0 fallos (kernel 144153668) |
| DQI público S 3.7676e11 | Medido | Mejor envío 58076483, 102,400 shots, 0 fallos |
| DQI propio Toom-4 S 1.923348e13 | Medido | Verificador oficial, 102,400 shots, 0 fallos (kernel 144398281) |
| DQI BM+Forney S 3.2331e12 | **Proyección** | Chien medido en kickmix; .kmb completo y verificador pendientes |
| Química pública S 326,800,029.87 | Medido | Mejor envío 58076483 (margen cero) |
| Química propia S 3,355,599,588.32 | Medido | Starter kit, sandbox y Kaggle idénticos (kernel 144333524) |
| Mapa de fases DQI (espejos 56.43%) | Medido | Conteo directo del .kmb, cierre exacto 453,312 |
| GM 23.94667 | Medido | Media geométrica de los tres S medidos del mejor envío |
| GM 30.00 (objetivo) | Objetivo | No alcanzado con módulos medidos (mejor real 23.95) |

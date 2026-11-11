# Operaciones de la skill auto-mvp-vqcc

Las 6 operaciones reales del repo (`auto_mvp/operations.py`). Todas
reciben y devuelven JSON. El punto de entrada es el mismo por CLI
(`python -m auto_mvp.cli <op>`), MCP (`tools/call`) y funciones
(`tools.py` / `functions.json`).

## evaluate_candidate

Evalúa un candidato: proxy (prefiltro por metadatos + contrato
oficial + margen) y puerta de promoción (GM con la fórmula de la
competencia).

Entrada:
```json
{"name": "montgomery-b17", "kind": "candidate",
 "meta": {"task": "dqi", "metrics": {"Q": 1414, "T": 1315731, "eps_plus": 0.001188}},
 "metrics": {"Q": 1414, "T": 1315731, "eps_plus": 0.001188}}
```
Parámetros: `meta_mvp` (30.0), `margin` (0.10), `best_S` (por
defecto, el del mejor envío: DQI 3.7676e11).

Salida (medida):
```json
{"task": "dqi", "proxy_ok": true, "reasons": [], "S": 3.2331e12,
 "gm": 11.697, "ratios": {"invsqrt": 20.65, "dqi": 7.55, "dfthcsos": 10.27},
 "promote": true, "meta_mvp": 2.0}
```
Límites: el proxy rechaza si el S no baja del mejor más que el
margen (el BM+Forney, S 3.714e12, no pasa con best_S 3.714e12 y
margen 0.10). No guarda artefactos; no verifica por simulación
(eso es la fase 3, `run` con `compile_fn`).

## apply_morph_tunnel

Tunela un grafo de llamadas con las reglas MORPH (reemplaza y
reordena BLOQUES, no solo números). Entrada: el grafo (dict de
CallGraph) y, opcionalmente, reglas y método (greedy | beam). Sin
reglas, usa el registro (con evidencia medida).

Salida (medida, grafo BM+Forney):
```json
{"baseline_T": 1511522.0, "final_T": 1315731.0, "baseline_Q": 1414,
 "final_Q": 1414,
 "moves": [{"rule": "chien-montgomery-b17", "target": "chien",
            "replacement": "montgomery-b17", "old_T": 1511522.0,
            "new_T": 1315731.0, "kind": "replace",
            "evidence": "cost_model exacto + montgomery-v4 INFORME_V4.md..."}],
 "stopped": "sin reglas que mejoren"}
```
Límites: una regla sin evidencia no se aplica (ValueError). La
equivalencia del reemplazo viene de la verificación medida que
nombra la evidencia; Qualtran no demuestra que dos Bloqs sean
iguales. El circuito DQI kickmix no es un Bloq de Qualtran.

## decode_json_config

Decodifica una configuración JSON con directivas en lenguaje
natural (vocabulario controlado, determinista).

Entrada:
```json
{"meta_mvp": 2.0,
 "directives": ["ataca chien", "reordena tunnel antes que gate"]}
```
Salida: `meta_mvp`, `steps`, `budget`, `directives` (cada una con
verb, params, raw, parsed, reason) y `unparsed` (las que no
encajan, con su motivo). Nada se descarta en silencio.

## run_orchestrator

Corre el orquestador adaptativo sobre un flujo de candidatos con
una config JSON. Los artefactos van a un directorio temporal (o a
`runs_dir`). Entrada: `candidates` (lista) y `config` (meta_mvp,
directives, budget); opcional `best_S` por tarea.

Salida (medida, BM+Forney con grafo, best_S 3.714e12, meta 2.0):
```json
{"screened": 1, "proxy_rejected": 0, "gate_rejected": 0, "promoted": 1,
 "tunneled": 1, "best_gm": 11.697, "goal_reached": true,
 "artifacts": [".../runs/i1-11.70/manifest.json"],
 "stopped": "meta alcanzada: GM 11.70 >= meta_mvp 2.00", "meta_mvp": 2.0}
```
Límites: la meta solo la alcanza un candidato REAL (kind
"candidate"); un target promueve pero no para la búsqueda. El paso
"search" del plan está reconocido pero sin cablear (la búsqueda de
mutaciones vive en `vqcc/search.py`); el orquestador lo reporta
en el log de pasos.

## check_integrity

Pasa el filtro de integridad obligatorio sobre una evidencia.
Entrada: la evidencia (kind, sigma, sigma_ref_hash, c_restored,
b_restored, total_coef, dreg_zero, alpha_zero, temporaries_zero,
temporaries_total, allowed_dirty, shots, verified_by). Salida:
`{"ok": true/false, "reasons": [...]}`. Un kind "projection"
(solo números, sin circuito) NUNCA pasa.

## promotion_gate

Lo que exige `meta_mvp`. Sin S: `{"meta_mvp": 30.0,
"required_dqi_ratio": 127.335, "target_S_dqi": 1.916e11}`. Con S
(`{"dqi": 3.7e11}`): además `gm` y `promote`.

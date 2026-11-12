---
name: auto-mvp-vqcc
description: Optimiza candidatos de la competencia Google Quantum AI Verifiable Quantum Circuit Compilation (VQCC): evalúa mejoras (proxy + puerta de promoción), corre el corrector y el pipeline por fases, aplica tunelamiento MORPH sobre el grafo de llamadas de Qualtran, decodifica configuraciones JSON con directivas en lenguaje natural y corre el orquestador adaptativo. Úsala cuando el usuario pida evaluar, optimizar o auditar un candidato VQCC (invsqrt, DQI o química DFTHC-SOS), tunelar un circuito, o correr el pipeline AUTO_MVP. No la uses para otras competencias ni para circuitos fuera de VQCC.
license: Apache-2.0
compatibility: Python >=3.10, solo stdlib (el paquete auto_mvp no tiene dependencias). Qualtran es opcional (solo para extraer Bloqs reales). Funciona en Kaggle Code (snapshot vendido), Claude con terminal (MCP o CLI), ChatGPT Code Interpreter y Grok (functions.json + tools.py).
metadata:
  version: "1.0.0"
  repo: dcpracmatic-prog/Google-Q-cvcc (PRIVADO)
  author: Arturo Salvador Balderas Hernández
---

# AUTO_MVP VQCC — optimizador de circuitos para la competencia

El sistema AUTO_MVP es el núcleo autónomo de optimización para la
competencia Google Quantum AI — Verifiable Quantum Circuit
Compilation (VQCC). El puntaje es la media geométrica de
(costo de referencia / costo propio) en 3 tareas (invsqrt, DQI,
química DFTHC-SOS). El mejor envío vigente es **23.94667**; la meta
absoluta que se le exige al sistema es el parámetro `meta_mvp`
(por ejemplo 30.00). Todo número que el sistema reporta es medido
(baseline vs optimizado); nada se afirma sin medir.

## Cuándo usar esta skill

- Evaluar si una mejora (Q, T, eps_plus, errores) bate el mejor
  envío o la meta.
- Correr el corrector / pipeline por fases sobre un flujo de
  candidatos y ver qué promueve.
- Tunelar un circuito: reemplazar o reordenar BLOQUES del grafo de
  llamadas (Qualtran) para bajar T/Q.
- Decodificar una configuración JSON con directivas en lenguaje
  natural ("sube la meta a 30", "ataca unextract").
- Pasar el filtro de integridad obligatorio a una evidencia de
  circuito (un "projection" nunca pasa).
- Calcular lo que exige una meta (DQI necesario, S objetivo).

No la uses fuera de VQCC, ni para inventar circuitos, ni para
afirmar un puntaje sin el verificador oficial.

## Cómo se invoca (el punto de entrada es el mismo en todos lados)

Las operaciones reales viven en `auto_mvp/operations.py` y se
exponen por igual por CLI, MCP y funciones. La CLI es la forma
más directa (ver `references/operations.md` para los detalles de
cada operación, entradas y salidas):

```bash
python -m auto_mvp.cli version
python -m auto_mvp.cli evaluate --in candidato.json --meta-mvp 2 --best-S 3.714e12
python -m auto_mvp.cli tunnel --in grafo.json
python -m auto_mvp.cli decode --in config.json
python -m auto_mvp.cli run --in config.json --candidates cands.json --best-S '{"dqi": 3.714e12}'
python -m auto_mvp.cli integrity --in evidencia.json
python -m auto_mvp.cli export --in record.json --runs-dir runs
python -m auto_mvp.cli validate --path submission.zip
python -m auto_mvp.cli combine --target 30 --runs-dir runs --export
python -m auto_mvp.cli gate --meta-mvp 30
```

## La guía: el mejor por tarea, entre corridas (v1.0.0)

El auto-optimizador es una **guía**, no un compilador ni un
validador. Su trabajo es juntar la base de las tres tareas que
sumen el puntaje pedido, y exportarla para auditarla:

- El mejor por tarea se guarda en `runs/best_per_task.json`,
  ENTRE corridas. La corrida 1 puede traer el mejor invsqrt y la
  corrida 2 el mejor DQI: la combinación toma el mejor de cada
  tarea, venga de la corrida que venga. Solo mejora: un S peor no
  borra el mejor, y cada reemplazo queda en el historial con su
  procedencia (corrida, iteración, medido o proyectado).
- Dado un objetivo (ej. 30.00), `combine_best` dice si la
  combinación llega, y si no, cuánto le falta a CADA tarea (el S
  que cada una necesitaría, con las otras dos fijas). Ese es el
  mapa: qué hay que mejorar y cuánto.
- Cuando la combinación llega al objetivo, se exporta la base de
  auditoría en un ZIP (`audit-base-<gm>.zip`): los tres
  componentes (estructura + código ejecutable cuando existen en
  el dataset, o sus métricas y procedencia) y un manifest.json con
  el objetivo, la GM y de dónde salió cada componente. El ZIP es
  para auditar y diseñar el submission real, NO el submission.zip
  de la competencia (ese lo arma la puerta fail-closed).

## Formato del submission.zip (v0.9.0)

El formato oficial vive en el repo (antes solo estaba en memoria;
la v0.3.0 falló por duplicados). El ZIP lleva, directamente en la
raíz (sin directorio raíz extra):

```
invsqrt.kmb  (o invsqrt.kmx, UNO solo)
dqi.kmb      (o dqi.kmx, UNO solo)
dfthcsos/
    angle_k_0.kmb  (o .kmx)
    angle_k_1.kmb
    ...            (consecutivos desde 0, SIN huecos)
    submission.npz (claves: U, W, H2_I, H1_I, Hsym_lower, tree_edges)
```

`validate_submission` comprueba el formato (fail-closed: cualquier
fallo bloquea el envío): sin duplicados, sin archivos extra, un
solo invsqrt y un solo dqi, angle_k consecutivos, y el NPZ con las
6 claves. Con los estados de los tres verificadores, además da
READY solo si la puerta fail-closed Y el formato pasan. El
validador revisa el FORMATO, no el contenido: que un circuito sea
correcto es trabajo de los verificadores oficiales.

Toda entrada y salida es JSON (por archivo con `--in`, o por
stdin/stdout). Cada operación devuelve sus números y sus motivos;
si algo no aplica, lo dice (no se inventa).

## Dataset de trabajo (v0.8.0)

El fail-closed está perfecto para el submission.zip final, pero un
módulo promovido no se queda en un manifiesto con métricas frías:
cada promoción exporta e inyecta su estructura completa y su código
ejecutable al dataset de trabajo (`<runs_dir>/dataset/<nombre>/`):
`structure.json` (grafo de llamadas completo, métricas, evidencia),
`module.py` (código ejecutable, solo stdlib: rebuild la estructura
y recomputa S y GM; `python module.py` lo verifica) y `source/...`
(el código del constructor, cuando el candidato lo trae). El índice
`dataset/index.json` lista los módulos inyectados. La fase 3
(compilación) consume el dataset, no un manifiesto pelado. La
compilación a .kmb (kickmix) sigue siendo la fase 3, no parte del
export.

## Operaciones (resumen; el detalle está en references/operations.md)

| Operación | Qué hace | Entrada | Salida clave |
|---|---|---|---|
| `evaluate_candidate` | proxy + puerta sobre un candidato | candidato JSON | S, GM, ratios, promote, motivos |
| `apply_morph_tunnel` | tunela un grafo de llamadas (MORPH) | grafo JSON | T/Q antes y después, movimientos |
| `decode_json_config` | decodifica config JSON + directivas | config JSON | meta_mvp, pasos, directivas, no parseadas |
| `run_orchestrator` | corre el orquestador adaptativo | candidatos + config | promovidos, tunelados, mejor GM, meta |
| `check_integrity` | filtro de integridad obligatorio | evidencia JSON | ok, motivos |
| `export_module` | exporta e inyecta un módulo al dataset | record promovido | rutas, grafo, código (structure.json + module.py) |
| `validate_submission` | valida el formato del submission.zip | ruta del ZIP o directorio | ok, motivos, ángulos, claves del NPZ, READY/NOT_CREATED |
| `combine_best` | la guía: el mejor por tarea, entre corridas, contra el objetivo | objetivo (+ runs_dir) | GM, si llega, qué trae cada tarea, cuánto falta, ZIP de auditoría |
| `promotion_gate` | lo que exige meta_mvp | meta_mvp (+ S) | ratio DQI necesario, S objetivo, GM |

## Reglas honestas (no negociables)

- **El mérito es el S oficial.** La suma ponderada solo ordena
  (proxy), nunca acepta. Un target es una hipótesis paramétrica,
  no el circuito: la meta solo la alcanza un candidato REAL.
- **Una regla de tunelamiento sin evidencia medida no se aplica.**
  La equivalencia de un reemplazo viene de la verificación medida
  (cost_model exacto, verificador oficial), nunca de Qualtran:
  Qualtran no demuestra que dos Bloqs sean iguales.
- **El circuito DQI es kickmix, no un Bloq de Qualtran.** El
  puente opera sobre Bloqs de Qualtran y sobre grafos construidos
  desde el cost_model.
- **El "lenguaje natural" es un vocabulario controlado** (reglas
  deterministas). Lo que no encaja se reporta como no parseado,
  nunca se descarta en silencio.
- **MORPH solo lee bitstrings DESPUÉS del flujo** (MIS sobre la
  salida). La gobernanza y los vetos viven en el lazo, no en MORPH.
- **El repo es PRIVADO y el trabajo VQCC stays oculto** mientras
  la competencia esté abierta. Nada se sube a Kaggle ni se publica
  sin que Arturo lo pida. La instalación usa acceso autenticado
  (ver references/install.md); nunca se pone un token en un archivo.

## Instalación por entorno

Ver `references/install.md`: Kaggle Code (snapshot vendido, sin
clonar el repo privado), Claude con terminal (git clone + pip
install, o servidor MCP), ChatGPT Code Interpreter (subir el
repo/skill + pip install, functions.json para function calling) y
Grok (igual que ChatGPT, esquema compatible con OpenAI).

## Archivos de la skill

- `SKILL.md` — esta skill.
- `mcp_server.py` — servidor MCP (stdio, solo stdlib) para Claude.
- `tools.py` — las 6 operaciones como funciones Python (Code
  Interpreter / Grok).
- `functions.json` — esquema de function calling (OpenAI/Grok).
- `references/operations.md` — cada operación: entradas, salidas,
  límites y ejemplos con números.
- `references/install.md` — instalación y uso por entorno.

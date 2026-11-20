# AUTO_MVP — auto-optimizador para VQCC

Auto-optimizador para la competencia Google Verifiable Quantum Circuit
Compilation (VQCC). El LLM propone circuitos; el verificador oficial
solo los verifica. La herramienta vive en el repo y se ejecuta en
Kaggle (notebooks privados, salida visible); el sandbox no es un
entregable.

## La skill auto-mvp-vqcc

La skill (`skills/auto-mvp-vqcc/`) expone 12 operaciones por MCP
(`mcp_server.py`, `tools.py`, `functions.json`):

- **evaluate_candidate** — Evalúa un candidato VQCC (proxy + puerta de promoción): S estimado, GM, ratios, si promueve y los motivos. El proxy compara contra el mejor S conocido (por defecto, el del mejor envío).
- **apply_morph_tunnel** — Tunela un grafo de llamadas con las reglas MORPH (reemplaza/reordena bloques): T/Q antes y después, movimientos con su evidencia medida. Una regla sin evidencia no se aplica.
- **decode_json_config** — Decodifica una configuración JSON con directivas en lenguaje natural (vocabulario controlado): meta_mvp, pasos, directivas decodificadas y las no parseadas (con su motivo). Nada se descarta en silencio.
- **run_orchestrator** — Corre el orquestador adaptativo sobre un flujo de candidatos con una config JSON: cribados, promovidos, tunelados, mejor GM, si la meta se alcanzó y los artefactos. La meta solo la alcanza un candidato REAL (un target es una hipótesis).
- **check_integrity** — Pasa el filtro de integridad obligatorio sobre una evidencia de circuito (sigma, C/B restaurados, dreg/alpha en cero, temporales, shots). Un 'projection' (solo números, sin circuito) NUNCA pasa este filtro.
- **export_module** — Exporta e inyecta un módulo promovido al dataset de trabajo: su estructura completa (grafo de llamadas) y su código ejecutable (module.py), para evaluarlo y compilarlo. No es el submission.zip (ese sigue fail-closed).
- **validate_submission** — Valida el formato de un submission.zip (o su directorio): rutas exactas, sin duplicados ni directorio raíz extra, angle_k consecutivos sin huecos, submission.npz con las 6 claves (U, W, H2_I, H1_I, Hsym_lower, tree_edges). Fail-closed: cualquier fallo bloquea el envío.
- **combine_best** — La guía: junta el mejor componente por tarea (entre corridas) y dice si la combinación llega al puntaje objetivo, cuánto le falta a cada tarea y, si llega, exporta los tres en un ZIP de auditoría para auditarlos.
- **promotion_gate** — La puerta de promoción: lo que exige meta_mvp (ratio DQI necesario, S objetivo) y, si se pasa S, la GM y si promueve.
- **mutate** — El mutador autónomo: genera candidatos mutando la semilla con las cuatro estrategias (morph, ventana SA, salto Lévy, MWIS).
- **run_serial** — La orquestación en serie con compensación global: corre las tareas en serie con el mismo ledger y acepta el balance global cuando la GM combinada llega al objetivo.
- **export_notebook** — Exporta los tres módulos ganadores a un Notebook .ipynb ejecutable.

## Reglas

- La vara es GM medido mayor a 28.23162 con 3 PASS (verificadores
  oficiales, dataset oficial de la competencia, sin starter kit).
- Nada se envía a la competencia sin orden explícita de Arturo.
- No se usan datasets de otros: todo se crea desde cero, salvo el
  portfolio GM 28.23163 que sirve de base para mejorarlo.
- El LLM crea circuitos, no valida. Corre solo en Kaggle, dentro
  del notebook, nunca en el sandbox ni en el repo.

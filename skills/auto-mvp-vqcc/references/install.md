# Instalación y uso por entorno — skill auto-mvp-vqcc

El repo es **PRIVADO** (dcpracmatic-prog/Google-Q-cvcc) y el trabajo
VQCC stays oculto mientras la competencia esté abierta. La
instalación usa acceso autenticado (tu propio token o SSH); **nunca
se pone un token en un archivo del repo ni en la skill**. Los
comandos de abajo usan `<TU_TOKEN>` como marcador: lo pones tú en
el momento, sin guardarlo.

## Kaggle Code (sandbox)

En Kaggle NO se clona el repo privado (Kaggle no puede clonarlo sin
credenciales, y un token nunca vive en un notebook). La vía es el
**snapshot vendido**: el notebook lleva el paquete `auto_mvp` con
el SHA grabado (como hace el notebook `vqcc-auto-mvp-pipeline`,
versión 2, kernel 144474964). En la celda de setup del notebook:

```python
# El notebook ya vende el paquete (30 archivos, commit grabado).
# Desde ahí, la skill se usa importando el paquete vendido:
from auto_mvp.operations import evaluate_candidate, apply_morph_tunnel
from auto_mvp.cli import main as cli_main

# O por CLI dentro del notebook:
# !python -m auto_mvp.cli evaluate --in candidato.json --meta-mvp 2
```

Los artefactos van a `/kaggle/working/runs/`; `/kaggle/input` es
solo lectura (el dataset es intocable). El notebook debe ser
**privado**. Nada se sube a Kaggle sin que Arturo lo pida.

## Claude con terminal

```bash
# 1. Clona (con tu token, sin guardarlo en archivos):
git clone https://<TU_TOKEN>@github.com/dcpracmatic-prog/Google-Q-cvcc.git
cd Google-Q-cvcc
# O con SSH: git clone git@github.com:dcpracmatic-prog/Google-Q-cvcc.git

# 2. Instala (solo stdlib, Python >=3.10):
pip install .

# 3. Usa la CLI:
python -m auto_mvp.cli version
python -m auto_mvp.cli evaluate --in candidato.json --meta-mvp 2
```

**Servidor MCP (Claude Code o Claude Desktop).** En `.mcp.json`
(Claude Code) o `claude_desktop_config.json` (Claude Desktop):

```json
{"mcpServers": {"auto-mvp-vqcc": {
  "command": "python",
  "args": ["/ruta/al/repo/skills/auto-mvp-vqcc/mcp_server.py"]}}}
```

El servidor es stdio y solo stdlib; si `auto_mvp` no está
instalado, añade la raíz del repo al path solo. Para probar el
servidor a mano:

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0"}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | python skills/auto-mvp-vqcc/mcp_server.py
```

## ChatGPT con Code Interpreter

1. Sube el repo (o la carpeta `skills/auto-mvp-vqcc/` + el
   paquete `auto_mvp/`) a la sesión de Code Interpreter.
2. En una celda de la sesión:
```python
# Instala desde el repo subido (o añade la ruta al path):
# !pip install -e /mnt/data/Google-Q-cvcc
import sys
sys.path.insert(0, "/mnt/data/Google-Q-cvcc")
from tools import evaluate_candidate  # desde skills/auto-mvp-vqcc/tools.py
# o desde el paquete:
from auto_mvp.operations import evaluate_candidate
```
3. Para function calling (API / Assistants), carga
   `skills/auto-mvp-vqcc/functions.json` como definiciones de
   funciones (formato OpenAI) y ejecuta las llamadas con `tools.py`.

## Grok

Igual que ChatGPT: sube el repo/skill a la sesión, instala o añade
la ruta al path, e importa `tools.py`. La API de xAI acepta el
mismo esquema de function calling de OpenAI, así que
`functions.json` se usa tal cual (mismos nombres y parámetros).

## Verificación (que la skill reproduzca los números del repo)

Desde un entorno limpio, la skill debe dar los mismos números que
el repo (ver `tests/test_auto_mvp_v070.py`):

- `gate --meta-mvp 30` -> required_dqi_ratio 127.335, target_S_dqi 1.916e11.
- `evaluate` (Montgomery b=17, best_S 3.714e12, meta 2) -> S 3.2331e12,
  GM 11.697, promote true.
- `tunnel` (grafo BM+Forney) -> T 1,511,522 -> 1,315,731.
- `run` (BM+Forney con grafo, best_S 3.714e12, meta 2) -> promovido 1,
  tunelado 1, mejor GM 11.697, meta alcanzada.

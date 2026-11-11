"""AUTO_MVP v0.7.0 — servidor MCP (stdio, solo stdlib) para Claude.

Expone las 6 operaciones reales del repo (auto_mvp/operations.py)
como herramientas MCP. Transporte: JSON-RPC 2.0 por stdio (una
línea JSON por mensaje), el transporte estándar de MCP. No usa el
SDK de MCP (el paquete es solo stdlib): implementa el mínimo del
protocolo que un cliente MCP necesita (initialize, tools/list,
tools/call, ping).

Uso con Claude Code (en .mcp.json):
    {"mcpServers": {"auto-mvp-vqcc": {
        "command": "python",
        "args": ["/ruta/al/repo/skills/auto-mvp-vqcc/mcp_server.py"]}}}

Uso con Claude Desktop (en claude_desktop_config.json, misma
estructura "mcpServers"). Uso directo para probar:
    echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python mcp_server.py

El servidor busca auto_mvp en el Python actual; si no está
instalado, añade la raíz del repo (el padre de skills/) al path,
así funciona desde un git clone sin pip install.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# El paquete auto_mvp: instalado, o la raíz del repo (dos niveles arriba).
try:
    import auto_mvp  # noqa: F401
except ImportError:
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from auto_mvp import __version__ as PKG_VERSION  # noqa: E402
from auto_mvp.operations import OPERATIONS  # noqa: E402

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "auto-mvp-vqcc"

TOOLS = [
    {
        "name": "evaluate_candidate",
        "description": ("Evalúa un candidato VQCC (proxy + puerta de "
                        "promoción): S estimado, GM, ratios, si promueve."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "candidate": {"type": "object",
                              "description": "candidato: name, kind, meta {task, metrics}, metrics"},
                "meta_mvp": {"type": "number", "default": 30.0},
                "margin": {"type": "number", "default": 0.10},
                "best_S": {"type": "number"},
            },
            "required": ["candidate"],
        },
    },
    {
        "name": "apply_morph_tunnel",
        "description": ("Tunela un grafo de llamadas con las reglas MORPH "
                        "(reemplaza/reordena bloques): T/Q antes y después."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "call_graph": {"type": "object",
                               "description": "grafo (dict de CallGraph)"},
                "rules": {"type": "array",
                          "description": "reglas (si no, las del registro, con evidencia medida)"},
                "method": {"type": "string", "enum": ["greedy", "beam"],
                           "default": "greedy"},
            },
            "required": ["call_graph"],
        },
    },
    {
        "name": "decode_json_config",
        "description": ("Decodifica una configuración JSON con directivas "
                        "en lenguaje natural: meta_mvp, pasos, directivas, "
                        "no parseadas."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "config": {"type": "object",
                           "description": "config: meta_mvp, steps, directives, budget"},
            },
            "required": ["config"],
        },
    },
    {
        "name": "run_orchestrator",
        "description": ("Corre el orquestador adaptativo sobre un flujo de "
                        "candidatos con una config JSON: promovidos, "
                        "tunelados, mejor GM, meta alcanzada."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "candidates": {"type": "array",
                               "description": "lista de candidatos"},
                "config": {"type": "object",
                           "description": "config: meta_mvp, directives, budget"},
                "best_S": {"type": "object",
                           "description": "mejor S por tarea, ej. {\"dqi\": 3.714e12}"},
            },
            "required": ["candidates"],
        },
    },
    {
        "name": "check_integrity",
        "description": ("Pasa el filtro de integridad obligatorio sobre "
                        "una evidencia de circuito. Un 'projection' nunca pasa."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "evidence": {"type": "object",
                             "description": "evidencia: kind, sigma, C/B, dreg/alpha, temporales, shots"},
            },
            "required": ["evidence"],
        },
    },
    {
        "name": "promotion_gate",
        "description": ("La puerta de promoción: lo que exige meta_mvp "
                        "(ratio DQI necesario, S objetivo) y, con S, la GM."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "meta_mvp": {"type": "number", "default": 30.0},
                "S": {"type": "object",
                      "description": "S por tarea, ej. {\"dqi\": 3.7e11}"},
            },
        },
    },
]


def _result(msg_id, result):
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id, code, message):
    return {"jsonrpc": "2.0", "id": msg_id,
            "error": {"code": code, "message": message}}


def handle(msg: dict) -> dict | None:
    """Un mensaje JSON-RPC -> su respuesta (None = notificación, sin respuesta)."""
    method = msg.get("method", "")
    msg_id = msg.get("id")
    params = msg.get("params") or {}
    if method == "initialize":
        return _result(msg_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": PKG_VERSION}})
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return _result(msg_id, {})
    if method == "tools/list":
        return _result(msg_id, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments") or {}
        fn = OPERATIONS.get(name)
        if fn is None:
            return _error(msg_id, -32602, f"herramienta desconocida: {name!r}")
        try:
            out = fn(**args)
        except Exception as exc:  # la operación falló: se reporta, no se muere
            return _result(msg_id, {
                "content": [{"type": "text",
                             "text": json.dumps({"error": str(exc)})}],
                "isError": True})
        return _result(msg_id, {
            "content": [{"type": "text",
                         "text": json.dumps(out, ensure_ascii=False)}]})
    if method.startswith("notifications/"):
        return None
    return _error(msg_id, -32601, f"método desconocido: {method!r}")


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            resp = handle(msg)
        except Exception as exc:  # nunca se muere por un mensaje malo
            resp = _error(msg.get("id"), -32603, str(exc))
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

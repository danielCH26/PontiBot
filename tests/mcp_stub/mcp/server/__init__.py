"""
Implementacion minima del protocolo MCP (stdio) para poder probar el servidor
sin instalar el SDK oficial.

Solo sirve para tests: implementa `initialize`, `tools/list`, `tools/call` y
`ping` con JSON-RPC 2.0 sobre stdio delimitado por saltos de linea, que es
justo lo que necesita `server.py` para funcionar.

    PYTHONPATH=tests/mcp_stub:. python server.py
"""

from __future__ import annotations

import inspect
import json
import sys
from typing import Any, Callable

PROTOCOL_VERSION = "2025-06-18"

_TYPES = {
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "list": "array",
    "dict": "object",
}


def _schema_for(fn: Callable) -> dict[str, Any]:
    """Esquema JSON a partir de la firma de la funcion."""
    signature = inspect.signature(fn)
    try:
        hints = fn.__annotations__ or {}
    except Exception:
        hints = {}
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, parameter in signature.parameters.items():
        if name in ("self", "ctx", "context"):
            continue
        annotation = hints.get(name, parameter.annotation)
        kind = "string"
        if annotation is not None:
            key = annotation if isinstance(annotation, str) else getattr(annotation, "__name__", "")
            kind = _TYPES.get(str(key).lower(), "string")
        properties[name] = {"type": kind}
        if parameter.default is inspect.Parameter.empty:
            required.append(name)
    return {"type": "object", "properties": properties, "required": required}


class MCPServer:
    """Servidor MCP minimo sobre stdio."""

    def __init__(self, name: str, **_: Any) -> None:
        self.name = name
        self._tools: dict[str, dict[str, Any]] = {}

    def tool(self, *args: Any, **kwargs: Any):
        """Decorador: @mcp.tool() o @mcp.tool"""
        def decorator(fn: Callable) -> Callable:
            self._tools[fn.__name__] = {
                "name": fn.__name__,
                "description": (fn.__doc__ or "").strip(),
                "inputSchema": _schema_for(fn),
                "fn": fn,
            }
            return fn

        if args and callable(args[0]):
            return decorator(args[0])
        return decorator

    # -------------------------------------------------------------- #
    def _handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method", "")
        message_id = message.get("id")

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": message_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": self.name, "version": "0.1.0"},
                },
            }

        if method == "ping":
            return {"jsonrpc": "2.0", "id": message_id, "result": {}}

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": message_id,
                "result": {
                    "tools": [
                        {
                            "name": tool["name"],
                            "description": tool["description"],
                            "inputSchema": tool["inputSchema"],
                        }
                        for tool in self._tools.values()
                    ]
                },
            }

        if method == "tools/call":
            params = message.get("params") or {}
            name = params.get("name", "")
            arguments = params.get("arguments") or {}
            tool = self._tools.get(name)
            if tool is None:
                return {
                    "jsonrpc": "2.0",
                    "id": message_id,
                    "error": {"code": -32602, "message": f"Unknown tool: {name}"},
                }
            try:
                output = tool["fn"](**arguments)
                text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
                return {
                    "jsonrpc": "2.0",
                    "id": message_id,
                    "result": {"content": [{"type": "text", "text": text}], "isError": False},
                }
            except Exception as exc:  # noqa: BLE001
                return {
                    "jsonrpc": "2.0",
                    "id": message_id,
                    "result": {
                        "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}],
                        "isError": True,
                    },
                }

        if message_id is None:
            return None  # es una notificacion: no se responde
        return {
            "jsonrpc": "2.0",
            "id": message_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    def run(self, transport: str = "stdio", **_: Any) -> None:
        """Bucle de servicio por stdin/stdout."""
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            response = self._handle(message)
            if response is not None:
                sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                sys.stdout.flush()

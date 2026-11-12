"""
Puente hacia el servidor MCP.

Permite que el agente de voz (que corre DENTRO del robot) use el mismo
catalogo de herramientas que expone `server.py`, sin duplicar codigo:
el LLM recibe los schemas tal cual los publica el servidor MCP y las llamadas
se ejecutan a traves del protocolo MCP.

Requiere el paquete `fastmcp` (viene con `pip install mcp`).
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

DEFAULT_SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.py")


class MCPBridge:
    """Cliente MCP en modo stdio contra `server.py`."""

    def __init__(self, server_path: str = DEFAULT_SERVER, env: dict[str, str] | None = None) -> None:
        self.server_path = server_path
        self.env = env or {}

    def _run(self, coro):
        """Ejecuta una corrutina sin bloquear el hilo principal."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            # ya hay un loop activo (p.ej. dentro de un servidor async)
            return asyncio.run_coroutine_threadsafe(coro, loop).result()
        return asyncio.run(coro)

    async def _list_tools(self) -> list[dict[str, Any]]:
        from fastmcp import Client  # import local: solo hace falta con este backend

        async with Client(self.server_path, env=self.env or None) as client:
            tools = await client.list_tools()
            result = []
            for tool in tools:
                schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", {}) or {}
                result.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": getattr(tool, "description", "") or "",
                        "parameters": schema,
                    },
                })
            return result

    async def _call(self, name: str, arguments: dict[str, Any]) -> str:
        from fastmcp import Client

        async with Client(self.server_path, env=self.env or None) as client:
            outcome = await client.call_tool(name, arguments)
            content = getattr(outcome, "content", None)
            if content:
                texts = []
                for item in content:
                    text = getattr(item, "text", None)
                    if text:
                        texts.append(text)
                    else:
                        texts.append(str(item))
                return "\n".join(texts)
            structured = getattr(outcome, "structured_content", None) or getattr(outcome, "data", None)
            if structured is not None:
                return json.dumps(structured, ensure_ascii=False)
            return str(outcome)

    def list_tools(self) -> list[dict[str, Any]]:
        """Herramientas del servidor MCP, en formato OpenAI function-calling."""
        return self._run(self._list_tools())

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        """Ejecuta una herramienta MCP y devuelve su resultado como texto."""
        return self._run(self._call(name, arguments or {}))


if __name__ == "__main__":  # pragma: no cover
    bridge = MCPBridge()
    for tool in bridge.list_tools():
        function = tool["function"]
        print(f"- {function['name']}: {function['description'][:80]}")

"""
Prueba de humo de la integracion con NVIDIA NIM.

No necesita robot. Comprueba, en este orden:

  1. la clave es valida
  2. el catalogo responde
  3. el modelo elegido habla, llama a herramientas y ve imagenes
  4. CRITICO: los esquemas DE HERRAMIENTAS REALES del servidor MCP (las 26
     herramientas de server.py) se aceptan y el modelo elige una correctamente

El punto 4 es donde fallan las integraciones: cada proveedor tiene su propio
formato de tool calling y no todos aceptan el mismo JSON Schema.

    export NVIDIA_API_KEY=nvapi-...
    python nvidia_smoke_test.py
    python nvidia_smoke_test.py --model minimaxai/minimax-m3.1-flash
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import types
from typing import Any

# --- rutas del proyecto (añade ../pc, ../patches y ../tools al sys.path) ---
import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
for _p in (_os.path.join(_ROOT, "pc"),
           _os.path.join(_ROOT, "patches", "robot_patch"),
           _os.path.join(_ROOT, "tools")):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)
# --- fin rutas del proyecto ---

from nvidia_models import NvidiaError, fetch_catalog, model_ids, probe_all
from prompts import SYSTEM_PROMPT
from tool_parse import extract_inline_tool_calls, strip_inline_calls

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

DEFAULT_MODEL = os.environ.get("LLM_MODEL", "nvidia/nemotron-3.5-bolt-e4b")


_TOOL_CACHE: tuple[list[dict[str, Any]], dict[str, Any]] | None = None


def _load_tool_schemas() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Importa server.py con un stub del SDK de MCP y devuelve sus esquemas.

    El resultado se cachea: `import server` queda cacheado en sys.modules, asi
    que en la segunda llamada el decorador stub no volveria a ejecutarse y
    devolveriamos una lista de herramientas VACIA (y el modelo, sin tools).
    """
    global _TOOL_CACHE
    if _TOOL_CACHE is not None:
        return _TOOL_CACHE

    registered: dict[str, Any] = {}

    class _StubServer:
        def __init__(self, name: str) -> None:
            self.name = name

        def tool(self, *args: Any, **kwargs: Any):
            def decorator(fn):
                registered[fn.__name__] = fn
                return fn
            return decorator

        def run(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError

    fake_mcp = types.ModuleType("mcp")
    fake_mcp_server = types.ModuleType("mcp.server")
    fake_mcp_server.MCPServer = _StubServer  # type: ignore[attr-defined]
    fake_mcp.server = fake_mcp_server  # type: ignore[attr-defined]
    sys.modules.setdefault("mcp", fake_mcp)
    sys.modules.setdefault("mcp.server", fake_mcp_server)

    import server as server_module  # noqa: WPS433

    schemas = []
    for name, fn in registered.items():
        schemas.append({
            "type": "function",
            "function": {
                "name": name,
                "description": (fn.__doc__ or "").strip(),
                "parameters": _schema_from(fn),
            },
        })
    _TOOL_CACHE = (schemas, registered)
    return _TOOL_CACHE


def _schema_from(fn: Any) -> dict[str, Any]:
    """Esquema minimo a partir de la firma (lo que hace FastMCP de verdad)."""
    import inspect

    signature = inspect.signature(fn)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, parameter in signature.parameters.items():
        annotation = parameter.annotation
        kind = "string"
        if annotation is int:
            kind = "integer"
        elif annotation is float:
            kind = "number"
        elif annotation is bool:
            kind = "boolean"
        properties[name] = {"type": kind}
        if parameter.default is inspect.Parameter.empty:
            required.append(name)
    return {"type": "object", "properties": properties, "required": required}


def check_real_tools(model_id: str, api_key: str) -> tuple[bool, str]:
    """Manda las herramientas reales y comprueba que el modelo elige una bien."""
    from nvidia_models import _request

    schemas, registered = _load_tool_schemas()
    payload = {
        "model": model_id,
        "messages": [{
            "role": "user",
            "content": "Hola. Saluda a la persona que tienes delante con la mano.",
        }],
        "tools": schemas,
        "tool_choice": "auto",
        "max_tokens": 256,
    }
    try:
        body = _request("/chat/completions", payload)
    except NvidiaError as exc:
        return False, str(exc)[:200]

    message = (body.get("choices") or [{}])[0].get("message") or {}
    calls = message.get("tool_calls") or []
    if not calls:
        return False, f"no llamo a ninguna herramienta (dijo: {(message.get('content') or '')[:80]!r})"

    call = calls[0]
    name = (call.get("function") or {}).get("name", "")
    if name not in registered:
        return False, f"llamo a una herramienta inexistente: {name!r}"
    try:
        arguments = json.loads((call["function"].get("arguments") or "{}"))
    except json.JSONDecodeError:
        return False, "argumentos no son JSON valido"
    return True, f"eligio {name} con {arguments}"


# Cada peticion tiene su herramienta correcta. Asi comprobamos que el modelo
# entiende el catalogo y no elige la primera que le sale.
SEMANTIC_CASES = [
    ("Saluda a la persona que tienes delante con la mano", {"robot_do_action", "robot_walk"}),
    ("Avanza tres pasos hacia delante", {"robot_walk"}),
    ("Para de moverte ahora mismo", {"robot_stop"}),
    ("Que color ves delante de ti?", {"robot_camera_snapshot", "robot_read_camera_rgb"}),
    ("Mira un poco hacia la derecha", {"robot_look"}),
    ("Busca caras con la camara", {"robot_start_vision"}),
]


def check_semantics(model_id: str) -> tuple[int, int, list[str]]:
    """
    Evalua el bucle COMPLETO de herramientas, igual que lo ejecuta el agente:
    si el modelo pide una herramienta, se le devuelve un resultado y se le
    deja volver a decidir. Una herramienta correcta puede llegar en el segundo
    turno (p.ej. 'primero mira que gestos hay, luego saluda').

    Devuelve (aciertos, total, detalle).
    """
    from nvidia_models import _request

    schemas, registered = _load_tool_schemas()
    hits = 0
    detail: list[str] = []

    for prompt, expected in SEMANTIC_CASES:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        chosen: list[str] = []
        answered = False

        for turn in range(4):
            payload = {
                "model": model_id,
                "messages": messages,
                "tools": schemas,
                "tool_choice": "auto",
                "max_tokens": 512,
            }
            try:
                body = _request("/chat/completions", payload)
            except NvidiaError as exc:
                detail.append(f"    {prompt[:34]:<36} ERROR {str(exc)[:80]}")
                break

            message = (body.get("choices") or [{}])[0].get("message") or {}
            calls = message.get("tool_calls") or []
            if not calls:
                # El agente real tambien detecta llamadas escritas como texto.
                inline = extract_inline_tool_calls(message.get("content") or "", set(registered))
                if inline:
                    calls = inline
                    message["content"] = strip_inline_calls(message.get("content") or "", set(registered))
            if not calls:
                break

            messages.append({"role": "assistant", "content": message.get("content") or "",
                             "tool_calls": calls})
            for call in calls:
                name = (call.get("function") or {}).get("name", "")
                chosen.append(name)
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.get("id", ""),
                    "name": name,
                    "content": "ok",
                })
            if any(name in expected for name in chosen):
                answered = True
                break
            time.sleep(6)  # el free tier son ~40/min: no podemos permitirnos spamear

        hits += int(answered)
        mark = "OK  " if answered else "FALL"
        detail.append(f"    {mark} {prompt[:34]:<36} -> {chosen or 'sin herramientas'}")
        time.sleep(8)

    return hits, len(SEMANTIC_CASES), detail


def main() -> int:
    parser = argparse.ArgumentParser(description="Prueba de humo de NVIDIA NIM")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--skip-tools", action="store_true")
    args = parser.parse_args()

    key = os.environ.get("NVIDIA_API_KEY", "") or os.environ.get("LLM_API_KEY", "")
    if not key:
        print("FALTA NVIDIA_API_KEY (o LLM_API_KEY)")
        return 1

    print("=== 1. clave y catalogo ===")
    try:
        catalog = fetch_catalog()
    except NvidiaError as exc:
        print(f"  ERROR: {exc}")
        return 1
    ids = model_ids(catalog)
    print(f"  OK  {len(ids)} modelos disponibles")
    if args.model not in ids:
        print(f"  AVISO  '{args.model}' no aparece en el catalogo; puede estar retirado")

    print(f"\n=== 2. sondeo de {args.model} ===")
    result = probe_all(args.model)
    print(f"  chat   : {'OK' if result['chat_ok'] else 'FALLO'}  {result['chat_latency']}s  {result['chat_msg'][:60]}")
    if "tools_ok" in result:
        print(f"  tools  : {'OK' if result['tools_ok'] else 'FALLO'}  {result.get('tools_latency')}s  {result.get('tools_msg', '')[:60]}")
        print(f"  vision : {'OK' if result['vision_ok'] else 'FALLO'}  {result.get('vision_latency')}s  {result.get('vision_msg', '')[:60]}")
    if not result["chat_ok"]:
        print("\nRESULTADO: el modelo no responde. Prueba otro con --model")
        return 1

    if not args.skip_tools:
        print("\n=== 3. herramientas reales del servidor MCP ===")
        ok, message = check_real_tools(args.model, key)
        print(f"  {'OK' if ok else 'FALLO'}  {message}")

    print("\n=== 4. eleccion semantica de herramienta (bucle completo) ===")
    hits, total, detail = check_semantics(args.model)
    for line in detail:
        print(line)
    print(f"  {hits}/{total} peticiones elicitaron la herramienta correcta")

    print("\n=== resumen ===")
    print(f"  base url : https://integrate.api.nvidia.com/v1")
    print(f"  modelo   : {args.model}")
    print("\nPara usarlo:")
    print(f"  export LLM_API_KEY=$NVIDIA_API_KEY")
    print(f"  export LLM_BASE_URL=https://integrate.api.nvidia.com/v1")
    print(f"  export LLM_MODEL={args.model}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

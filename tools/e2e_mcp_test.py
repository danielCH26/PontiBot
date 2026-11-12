"""
Prueba de extremo a extremo del servidor MCP.

Levanta el robot simulado, arranca `server.py` **sin modificar** como proceso
separado y le habla el protocolo MCP de verdad por stdio:

    initialize  ->  notifications/initialized  ->  tools/list  ->  tools/call

Comprueba que el MCP responde y que las herramientas **ejecutan de verdad**
contra el robot (llegan al JSON-RPC y vuelven con el efecto esperado).

    python e2e_mcp_test.py
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# --- rutas del proyecto (añade ../pc, ../patches y ../tools al sys.path) ---
import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
for _p in (_os.path.join(_ROOT, "pc"),
           _os.path.join(_ROOT, "patches", "robot_patch"),
           _os.path.join(_ROOT, "tools")):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)
# --- fin rutas del proyecto ---

import mock_robot  # noqa: E402

STUB_PATH = os.path.join(os.path.dirname(HERE), "tests", "mcp_stub")
SERVER_PATH = os.path.join(_ROOT, "pc", "server.py")

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(f"{name}: {detail}" if detail else name)
    else:
        FAILED.append((name, detail))


class MCPClient:
    """Cliente MCP minimo por stdio (JSON-RPC delimitado por saltos de linea)."""

    def __init__(self, process: subprocess.Popen) -> None:
        self.process = process
        self._id = 0

    def send(self, method: str, params: dict[str, Any] | None = None,
             expect_reply: bool = True) -> dict[str, Any] | None:
        self._id += 1
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        if expect_reply:
            message["id"] = self._id
        payload = json.dumps(message) + "\n"
        self.process.stdin.write(payload)
        self.process.stdin.flush()
        if not expect_reply:
            return None
        return self._read()

    def _read(self, timeout: float = 30.0) -> dict[str, Any]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = self.process.stdout.readline()
            if not line:
                if self.process.poll() is not None:
                    raise RuntimeError(f"el servidor MCP termino: {self.process.stderr.read()[:400]}")
                continue
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
        raise TimeoutError("el servidor MCP no respondio a tiempo")

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.send("tools/call", {"name": name, "arguments": arguments or {}})


def run_with_real_sdk() -> int:
    """
    La prueba definitiva: el SDK oficial de MCP hablando con server.py.

    Requiere el SDK instalado y un robot (real o simulado) accesible.
        pip install mcp
        python e2e_mcp_test.py --real-sdk
    """
    try:
        from fastmcp import Client  # type: ignore
    except ImportError:
        try:
            from mcp.client.session import ClientSession  # type: ignore
        except ImportError:
            print("Necesitas el SDK oficial: pip install mcp")
            return 2

    host = os.environ.get("TONYPI_HOST", "127.0.0.1")
    rpc_port = os.environ.get("TONYPI_RPC_PORT", "9030")
    mjpg_port = os.environ.get("TONYPI_MJPG_PORT", "8080")

    if host in ("127.0.0.1", "localhost") and rpc_port == "9030":
        print("Aviso: no hay robot en 127.0.0.1:9030. Arranca 'python mock_robot.py' o")
        print("       export TONYPI_HOST=<IP_DEL_ROBOT>")

    import asyncio

    async def run() -> int:
        async with Client(SERVER_PATH, env={
            "TONYPI_HOST": host,
            "TONYPI_RPC_PORT": rpc_port,
            "TONYPI_MJPG_PORT": mjpg_port,
            "PYTHONPATH": HERE,
        }) as client:
            tools = await client.list_tools()
            print(f"herramientas expuestas: {len(tools)}")
            names = [tool.name for tool in tools]
            for required in ("robot_do_action", "robot_walk", "robot_camera_snapshot"):
                check(f"herramienta presente: {required}", required in names)

            outcome = await client.call_tool("robot_ping", {})
            text = ""
            for item in getattr(outcome, "content", []) or []:
                text += getattr(item, "text", "") or ""
            check("robot_ping responde via SDK oficial", "ok" in text.lower(), repr(text[:60]))

            outcome = await client.call_tool("robot_do_action", {"action": "wave", "times": 1})
            text = ""
            for item in getattr(outcome, "content", []) or []:
                text += getattr(item, "text", "") or ""
            check("robot_do_action responde via SDK oficial", "wave" in text, repr(text[:70]))
        return 1 if FAILED else 0

    result = asyncio.run(run())
    print(f"\nOK: {len(PASSED)}   FALLOS: {len(FAILED)}")
    for line in PASSED:
        print(f"  ok   {line}")
    for name, error in FAILED:
        print(f"  FAIL {name}: {error}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Prueba E2E del servidor MCP")
    parser.add_argument("--real-sdk", action="store_true",
                        help="usar el SDK oficial de MCP en vez del stub (requiere 'pip install mcp')")
    args = parser.parse_args()

    if args.real_sdk:
        return run_with_real_sdk()

    # --- robot simulado en este proceso --- #
    rpc_server = mock_robot.ThreadingHTTPServer(("", 0), mock_robot.RPCHandler)
    mjpg_server = mock_robot.ThreadingHTTPServer(("", 0), mock_robot.MJPGHandler)
    rpc_port = rpc_server.server_address[1]
    mjpg_port = mjpg_server.server_address[1]
    threading.Thread(target=rpc_server.serve_forever, daemon=True).start()
    threading.Thread(target=mjpg_server.serve_forever, daemon=True).start()

    env = dict(os.environ)
    env["PYTHONPATH"] = f"{HERE}{os.pathsep}{STUB_PATH}"
    env["TONYPI_HOST"] = "127.0.0.1"
    env["TONYPI_RPC_PORT"] = str(rpc_port)
    env["TONYPI_MJPG_PORT"] = str(mjpg_port)

    process = subprocess.Popen(
        [sys.executable, SERVER_PATH],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1, env=env, cwd=HERE,
    )
    client = MCPClient(process)

    try:
        # --- 1. initialize --- #
        response = client.send("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "e2e-test", "version": "1.0"},
        })
        result = response.get("result") or {}
        check("initialize responde", "result" in response, f"protocol={result.get('protocolVersion')}")
        check("serverInfo correcto", (result.get("serverInfo") or {}).get("name") == "pontibot",
              str(result.get("serverInfo")))

        client.send("notifications/initialized", expect_reply=False)

        # --- 2. tools/list --- #
        response = client.send("tools/list")
        tools = (response.get("result") or {}).get("tools") or []
        names = [tool["name"] for tool in tools]
        check("tools/list devuelve herramientas", len(tools) > 0, f"{len(tools)} herramientas")
        for required in ("robot_do_action", "robot_walk", "robot_look", "robot_camera_snapshot",
                         "robot_start_vision", "robot_stop", "robot_say", "robot_beep"):
            check(f"herramienta presente: {required}", required in names)
        with_schema = [t for t in tools if t.get("inputSchema")]
        check("todas tienen inputSchema", len(with_schema) == len(tools),
              f"{len(with_schema)}/{len(tools)}")
        descriptions = [t for t in tools if t.get("description")]
        check("todas tienen descripcion", len(descriptions) == len(tools),
              f"{len(descriptions)}/{len(tools)}")

        # --- 3. tools/call: el MCP ejecuta de verdad --- #
        response = client.call_tool("robot_ping")
        text = ((response.get("result") or {}).get("content") or [{}])[0].get("text", "")
        check("robot_ping ejecuta", text.strip() == "ok", repr(text[:60]))

        response = client.call_tool("robot_do_action", {"action": "wave", "times": 2})
        text = ((response.get("result") or {}).get("content") or [{}])[0].get("text", "")
        check("robot_do_action ejecuta", "wave" in text and "x2" in text, repr(text[:70]))
        check("el efecto llego al robot", mock_robot.STATE["action"] == ("wave", 2),
              str(mock_robot.STATE["action"]))

        response = client.call_tool("robot_walk", {"direction": "forward", "steps": 3})
        text = ((response.get("result") or {}).get("content") or [{}])[0].get("text", "")
        check("robot_walk ejecuta", "forward" in text, repr(text[:70]))
        check("robot_walk llego al robot", mock_robot.STATE["action"] == ("go_forward", 3),
              str(mock_robot.STATE["action"]))

        response = client.call_tool("robot_look", {"pan": 1700, "tilt": 1400})
        text = ((response.get("result") or {}).get("content") or [{}])[0].get("text", "")
        check("robot_look ejecuta", "pan=1700" in text, repr(text[:70]))
        check("la cabeza se movio", mock_robot.STATE["head"] == {"pan": 1700, "tilt": 1400},
              str(mock_robot.STATE["head"]))

        response = client.call_tool("robot_start_vision", {"mode": "face_detect"})
        text = ((response.get("result") or {}).get("content") or [{}])[0].get("text", "")
        check("robot_start_vision ejecuta", "face_detect" in text, repr(text[:70]))
        check("la vision quedo cargada", mock_robot.STATE["running_func"] == 6,
              str(mock_robot.STATE["running_func"]))

        response = client.call_tool("robot_camera_snapshot")
        content = (response.get("result") or {}).get("content") or []
        text = content[0].get("text", "") if content else ""
        check("robot_camera_snapshot devuelve imagen", len(text) > 100, f"{len(text)} caracteres")

        response = client.call_tool("robot_say", {"text": "hola", "backend": "espeak"})
        text = ((response.get("result") or {}).get("content") or [{}])[0].get("text", "")
        check("robot_say ejecuta", "hola" in text, repr(text[:70]))
        check("el robot recibio el texto", mock_robot.STATE["spoken"] == "hola",
              str(mock_robot.STATE["spoken"]))

        # --- 3b. discos duros: listar y leer --- #
        disco = tempfile.mkdtemp(prefix="disco_")
        try:
            os.makedirs(os.path.join(disco, "canciones"))
            with open(os.path.join(disco, "canciones", "robot.mp3"), "wb") as handle:
                handle.write(b"ID3" + b"\x00" * 64)
            with open(os.path.join(disco, "notas.txt"), "w", encoding="utf-8") as handle:
                handle.write("esto es lo que hay en el disco\n")
            mock_robot._STORAGE_ROOTS = [disco]

            response = client.call_tool("robot_list_files", {"path": disco})
            text = ((response.get("result") or {}).get("content") or [{}])[0].get("text", "")
            check("robot_list_files lista el disco", "notas.txt" in text, repr(text[:90]))
            check("robot_list_files ve las carpetas", "canciones" in text, repr(text[:90]))

            response = client.call_tool("robot_read_file",
                                        {"path": os.path.join(disco, "notas.txt")})
            text = ((response.get("result") or {}).get("content") or [{}])[0].get("text", "")
            check("robot_read_file lee el fichero",
                  "esto es lo que hay en el disco" in text, repr(text[:90]))

            response = client.call_tool("robot_list_files", {"path": "/etc"})
            text = ((response.get("result") or {}).get("content") or [{}])[0].get("text", "")
            check("robot_list_files rechaza rutas fuera",
                  "no se pudo" in text.lower() or "permitida" in text.lower(), repr(text[:90]))

            response = client.call_tool("robot_list_audio", {"path": disco})
            text = ((response.get("result") or {}).get("content") or [{}])[0].get("text", "")
            check("robot_list_audio encuentra el mp3", "robot.mp3" in text, repr(text[:90]))
        finally:
            shutil.rmtree(disco, ignore_errors=True)

        # --- 4. errores controlados --- #
        response = client.call_tool("robot_walk", {"direction": "volando"})
        text = ((response.get("result") or {}).get("content") or [{}])[0].get("text", "")
        check("error controlado sin crash", "error" in text.lower() or "desconocida" in text.lower(),
              repr(text[:70]))

        response = client.call_tool("herramienta_que_no_existe")
        has_error = "error" in response or (response.get("result") or {}).get("isError")
        check("herramienta inexistente gestionada", bool(has_error), str(response)[:80])

        response = client.send("tools/call", {"name": "robot_ping", "arguments": {}})
        check("el servidor sigue vivo tras los errores", "result" in response, str(response)[:60])

    except Exception as exc:  # noqa: BLE001
        FAILED.append(("excepcion en la prueba", f"{type(exc).__name__}: {exc}"))
    finally:
        try:
            process.stdin.close()
            process.terminate()
            process.wait(timeout=5)
        except Exception:
            process.kill()

    print(f"\n{'=' * 58}")
    print(f"  PRUEBA MCP DE EXTREMO A EXTREMO")
    print(f"  OK: {len(PASSED)}   FALLOS: {len(FAILED)}")
    print(f"{'=' * 58}\n")
    for line in PASSED:
        print(f"  ok   {line}")
    for name, error in FAILED:
        print(f"  FAIL {name}: {error}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())

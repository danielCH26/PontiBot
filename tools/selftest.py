"""
Autotest del servidor MCP contra el robot simulado.

Verifica que el cliente RPC habla bien con el protocolo real y que todas las
herramientas MCP responden, sin necesidad del robot ni del SDK de MCP
(el decorador se sustituye por un stub que registra las herramientas).

    python selftest.py
"""

from __future__ import annotations

import os
import sys
import threading
import types
from typing import Any, Callable

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# --- stub del SDK de MCP: registramos las herramientas en vez de servirlo --- #
REGISTERED: dict[str, Callable] = {}


class _StubServer:
    def __init__(self, name: str) -> None:
        self.name = name

    def tool(self, *args: Any, **kwargs: Any):
        def decorator(fn: Callable) -> Callable:
            REGISTERED[fn.__name__] = fn
            return fn

        return decorator

    def run(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
        raise RuntimeError("no debe llamarse en el autotest")


fake_mcp = types.ModuleType("mcp")
fake_mcp_server = types.ModuleType("mcp.server")
fake_mcp_server.MCPServer = _StubServer  # type: ignore[attr-defined]
fake_mcp.server = fake_mcp_server  # type: ignore[attr-defined]
sys.modules.setdefault("mcp", fake_mcp)
sys.modules.setdefault("mcp.server", fake_mcp_server)

# --- Arrancar el robot simulado --- #
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

rpc_server = mock_robot.ThreadingHTTPServer(("", 0), mock_robot.RPCHandler)
mjpg_server = mock_robot.ThreadingHTTPServer(("", 0), mock_robot.MJPGHandler)
rpc_port = rpc_server.server_address[1]
mjpg_port = mjpg_server.server_address[1]
threading.Thread(target=rpc_server.serve_forever, daemon=True).start()
threading.Thread(target=mjpg_server.serve_forever, daemon=True).start()

os.environ["TONYPI_HOST"] = "127.0.0.1"
os.environ["TONYPI_RPC_PORT"] = str(rpc_port)
os.environ["TONYPI_MJPG_PORT"] = str(mjpg_port)

import server as server_module  # noqa: E402

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []


def check(name: str, fn: Callable) -> None:
    try:
        result = fn()
        text = str(result)
        if isinstance(result, bytes):
            text = f"<{len(result)} bytes>"
        PASSED.append(f"{name}: {text[:110]}")
    except Exception as exc:  # noqa: BLE001
        FAILED.append((name, f"{type(exc).__name__}: {exc}"))


def expect_error(name: str, fn: Callable) -> None:
    """El comando debe fallar con un error controlado, no con una excepcion rara."""
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        PASSED.append(f"{name} (error esperado): {type(exc).__name__}: {str(exc)[:80]}")
    else:
        FAILED.append((name, "deberia haber fallado y no fallo"))


def main() -> int:
    check("robot_ping", server_module.robot_ping)
    check("robot_status", server_module.robot_status)
    check("robot_list_actions", server_module.robot_list_actions)
    check("robot_do_action(wave)", lambda: server_module.robot_do_action("wave", 1))
    check("robot_do_action(bucle)", lambda: server_module.robot_do_action("bow", 0))
    # Una accion invalida debe devolver un aviso, no reventar el servidor.
    invalid = server_module.robot_do_action("nadar", 1)
    PASSED.append(f"robot_do_action(invalida): {str(invalid)[:70]}")
    check("robot_walk", lambda: server_module.robot_walk("forward", 2))
    expect_error("robot_walk(invalida)", lambda: server_module.robot_walk("volando", 1))
    check("robot_stop", server_module.robot_stop)
    check("robot_look", lambda: server_module.robot_look(1600, 1400))
    check("robot_read_servos", server_module.robot_read_servos)
    check("robot_set_body_servo", lambda: server_module.robot_set_body_servo(3, 200, 300))
    expect_error("robot_set_body_servo(fuera de rango)",
                 lambda: server_module.robot_set_body_servo(99, 200, 300))
    check("robot_start_vision", lambda: server_module.robot_start_vision("face_detect"))
    check("robot_vision_status", server_module.robot_vision_status)
    check("robot_stop_vision", server_module.robot_stop_vision)
    check("robot_set_color_threshold",
          lambda: server_module.robot_set_color_threshold("rojo", 0, 80, 60, 100, 255, 255))
    check("robot_get_color_thresholds", server_module.robot_get_color_thresholds)
    check("robot_read_camera_rgb", lambda: server_module.robot_read_camera_rgb("color_track"))
    check("robot_set_detection_point", lambda: server_module.robot_set_detection_point("kick_ball", 320, 240))
    check("robot_set_detection_threshold", lambda: server_module.robot_set_detection_threshold("color_track", 25))
    check("robot_stand_up", server_module.robot_stand_up)
    check("robot_camera_snapshot", server_module.robot_camera_snapshot)
    check("robot_power_down_servos", server_module.robot_power_down_servos)
    check("robot_beep", lambda: server_module.robot_beep(2000, 1))
    check("robot_play_audio", lambda: server_module.robot_play_audio("ok"))
    # Un audio inexistente debe devolver un aviso, no reventar el servidor.
    missing = server_module.robot_play_audio("nada")
    PASSED.append(f"robot_play_audio(inexistente): {str(missing)[:70]}")
    check("robot_say", lambda: server_module.robot_say("hola, soy TonyPi"))

    print(f"\nHerramientas registradas: {len(REGISTERED)}")
    for name in sorted(REGISTERED):
        print(f"  - {name}")

    print(f"\nOK: {len(PASSED)}   FALLOS: {len(FAILED)}")
    for line in PASSED:
        print(f"  ok   {line}")
    for name, error in FAILED:
        print(f"  FAIL {name}: {error}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
Comprobacion rapida de que el robot responde y de que el cliente habla bien
con el. No hace movimientos: solo lee estado.

    python test_rpc.py 192.168.1.50
"""

from __future__ import annotations

import sys

# --- rutas del proyecto (añade ../pc, ../patches y ../tools al sys.path) ---
import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
for _p in (_os.path.join(_ROOT, "pc"),
           _os.path.join(_ROOT, "patches", "robot_patch"),
           _os.path.join(_ROOT, "tools")):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)
# --- fin rutas del proyecto ---

from tonypi_client import TonyPiClient, TonyPiError


def main() -> int:
    host = sys.argv[1] if len(sys.argv) > 1 else "192.168.1.100"
    robot = TonyPiClient(host=host)

    print(f"-> conectando con {robot.rpc_url}")
    if not robot.ping():
        print("X  el robot no responde en el puerto 9030")
        print("   revisa: mismo WiFi? ip correcta? servicio tonypi.service activo?")
        return 1
    print("OK ping")

    try:
        print(f"OK vision cargada: {robot.get_running_func()}")
    except TonyPiError as exc:
        print(f".. vision cargada: no disponible ({exc})")

    try:
        positions = robot.read_servo_positions()
        print(f"OK servos: {positions}")
    except TonyPiError as exc:
        print(f".. servos: no disponible ({exc})")

    try:
        print(f"OK umbrales LAB: {robot.get_lab_value()}")
    except TonyPiError as exc:
        print(f".. umbrales LAB: no disponible ({exc})")

    try:
        jpeg = robot.snapshot()
        print(f"OK camara: {len(jpeg)} bytes JPEG")
    except TonyPiError as exc:
        print(f".. camara: no disponible ({exc})")

    print("\nTodo listo para usar el servidor MCP.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

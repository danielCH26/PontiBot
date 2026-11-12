"""
Robot simulado: replica el protocolo real del TonyPi sin necesidad del robot.

Reproduce la semantica exacta del servidor JSON-RPC del repo oficial
(`RPCServer.py` + la libreria `jsonrpc` de Hiwonder):

  * Los metodos devuelven su valor crudo. La libreria `jsonrpc` desenvuelve
    las tuplas de 3 elementos (ok, datos, metodo) y deja intactas las de 2.
  * exito  -> {"jsonrpc": "2.0", "result": <datos>, "id": 1}
  * error  -> {"jsonrpc": "2.0", "error": {"code": -32000, "message": "...",
                "data": "<metodo>"}, "id": 1}

Sirve para:
  * desarrollar el servidor MCP sin el robot encendido
  * probar el agente de voz
  * verificar upgrades del SDK de MCP

    python mock_robot.py          # escucha en 9030 (RPC) y 8080 (camara)
"""

from __future__ import annotations

import base64
import fnmatch
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

RPC_PORT = 9030
MJPG_PORT = 8080

STATE: dict[str, Any] = {
    "running_func": 0,
    "action": None,
    "head": {"pan": 1500, "tilt": 1500},
    "servos": [250] * 16,
    "lab": {
        "red": {"min": [0, 80, 60], "max": [100, 255, 255]},
        "green": {"min": [0, 60, 20], "max": [100, 255, 255]},
        "blue": {"min": [0, 0, 0], "max": [255, 255, 120]},
    },
    "audio_files": {"ok", "ready", "red", "green", "blue", "wave", "dong"},
    "buzzer": None,
    "played": None,
    "spoken": None,
}

ACTION_GROUPS = {
    "go_forward", "back", "left_move", "right_move", "turn_left", "turn_right",
    "wave", "bow", "chest", "squat", "push_ups", "sit_ups", "stepping", "twist",
    "stand", "stand_slow", "wing_chun", "left_uppercut", "right_uppercut",
    "left_kick", "right_kick", "left_shot", "right_shot",
}

# Carpetas donde el bot puede leer (mismas que en el parche del robot real).
_STORAGE_ROOTS = [
    "/media/pi",
    "/mnt",
    "/media/usb0",
    "/media/usb1",
    "/media/usb2",
    "/home/pi/TonyPi/audio",
]


def _storage_safe(path):
    """Normaliza una ruta y devuelve None si no esta en una carpeta permitida."""
    if path is None:
        return None
    path = str(path).strip()
    if not path or "\x00" in path:
        return None
    candidates = []
    if os.path.isabs(path):
        candidates.append(path)
    else:
        for root in _STORAGE_ROOTS:
            candidates.append(os.path.join(root, path))
    for candidate in candidates:
        normalized = os.path.normpath(candidate)
        if ".." in normalized.split(os.sep):
            continue
        for root in _STORAGE_ROOTS:
            root_norm = os.path.normpath(root)
            if not (normalized == root_norm or normalized.startswith(root_norm.rstrip("/") + "/")):
                continue
            try:
                real = os.path.realpath(normalized)
                real_root = os.path.realpath(root_norm)
            except OSError:
                continue
            if real == real_root or real.startswith(real_root.rstrip("/") + "/"):
                return normalized
    return None

VISION_FUNCS = {
    1: "remote_control", 2: "kick_ball", 3: "gesture", 4: "line_follow",
    5: "color_track", 6: "face_detect", 7: "apriltag", 8: "transport",
    9: "lab_adjust", 10: "hurdles", 11: "stairs", 12: "color_classify",
}

# JPEG 1x1 gris valido
_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRof"
    "Hh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAAB"
    "AAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q=="
)


class RpcFailure(Exception):
    """Error de negocio: el robot responde con un JSON-RPC error."""

    def __init__(self, message: str, method: str) -> None:
        super().__init__(message)
        self.message = message
        self.method = method


def _dispatch(method: str, params: list[Any]) -> Any:
    """
    Devuelve el valor CRUDO que devolveria el metodo real del robot.

    Las tuplas de 3 elementos (ok, datos, metodo) son las que usa el repo
    oficial para exito y error. Las de 2 elementos se usan en algunos metodos
    (GetRunningFunc, GetLABValue) y la libreria NO las desenvuelve.
    """
    def fail(message: str) -> None:
        raise RpcFailure(message, method)

    if method == "echo":
        return True, (params[0] if params else "",), method

    if method == "GetRunningFunc":
        # Hardcodeado a 0 en el repo oficial (linea comentada debajo).
        return True, (0,)

    if method == "RunAction":
        if len(params) != 2:
            fail("E01 - Invalid number of parameter!")
        name, times = str(params[0]), int(params[1])
        if name not in ACTION_GROUPS and not name.isdigit():
            fail("E03 - Operation failed!")
        STATE["action"] = (name, times)
        return True, (), method

    if method in ("StopBusServo", "StopActionGroup"):
        STATE["action"] = None
        return True, (), method

    if method == "StandUp":
        return True, (), method

    if method == "SetPWMServo":
        # Convencion real: [duracion_ms, numero_de_servos, servo, pulso, ...]
        if len(params) < 2 or len(params) % 2 != 0:
            fail("E01 - Invalid number of parameter!")
        count = params[1]
        servos = params[2::2]
        pulses = params[3::2]
        if len(servos) != count or len(pulses) != count:
            fail("E01 - Invalid number of parameter!")
        for servo, pulse in zip(servos, pulses):
            if servo not in (1, 2):
                fail("E02 - Invalid parameter!")
            if not 500 <= pulse <= 2500:
                fail("E02 - Invalid parameter!")
            STATE["head"]["pan" if servo == 1 else "tilt"] = pulse
        return True, (), method

    if method == "SetBusServoPulse":
        # Convencion real: [duracion_ms, numero_de_servos, servo, pulso, ...]
        if len(params) < 4 or (params[1] * 2 + 2) != len(params):
            fail("E01 - Invalid number of parameter!")
        for servo, pulse in zip(params[2::2], params[3::2]):
            if not 1 <= servo <= 16:
                fail("E02 - Invalid parameter!")
            STATE["servos"][int(servo) - 1] = int(pulse)
        return True, (), method

    if method == "GetBusServosPulse":
        if not params or params[0] != "angularReadback":
            fail("E01 - Invalid number of parameter!")
        return True, list(STATE["servos"]), method

    if method == "GetBusServosDeviation":
        if not params or params[0] != "readDeviation":
            fail("E01 - Invalid number of parameter!")
        return True, [0] * 16, method

    if method == "SaveBusServosDeviation":
        return True, (), method

    if method == "UnloadBusServo":
        return True, (), method

    if method == "LoadFunc":
        code = params[0][0] if params and isinstance(params[0], (list, tuple)) else None
        if code not in VISION_FUNCS:
            fail("loadFunc: Invalid argument")
        STATE["running_func"] = code
        return True, (code,), method

    if method == "StartFunc":
        return True, (STATE["running_func"],), method

    if method == "StopFunc":
        STATE["running_func"] = 0
        return True, (), method

    if method == "UnloadFunc":
        STATE["running_func"] = 0
        return True, (0,), method

    if method == "Heartbeat":
        return True, (), method

    if method == "GetLABValue":
        # Tupla de 2 elementos: la libreria no la desenvuelve.
        return True, (STATE["lab"],)

    if method == "SetLABValue":
        # Functions/lab_adjust.py espera {"color":..., "min":[l,a,b], "max":[l,a,b]}
        for entry in params:
            if isinstance(entry, dict) and "color" in entry:
                STATE["lab"][entry["color"]] = {
                    "min": list(entry.get("min", [0, 0, 0])),
                    "max": list(entry.get("max", [0, 0, 0])),
                }
        return True, (), method

    if method == "SaveLABValue":
        return True, (), method

    if method == "HaveLABAdjust":
        return True, True, method

    if method == "GetRGBValue":
        return True, (0, 128, 255), method

    if method in ("SetPoint", "SetThreshold"):
        return True, (), method

    # --- metodos que solo existen con el parche opcional del robot --- #
    if method == "SetBuzzer":
        if len(params) != 4:
            fail("E01 - Invalid number of parameter!")
        STATE["buzzer"] = list(params)
        return True, (), method

    if method == "PlayAudio":
        if len(params) != 1:
            fail("E01 - Invalid number of parameter!")
        name = str(params[0])
        # Como en el parche real: nombre suelto (del audio/ del robot) o ruta
        # dentro de las carpetas permitidas (discos externos).
        if "/" in name or "\\" in name:
            resolved = _storage_safe(name)
            if resolved is None:
                fail(f"E02 - ruta no permitida: {name}")
            if not os.path.isfile(resolved):
                fail(f"E03 - audio not found: {resolved}")
            STATE["played"] = resolved
            return True, (), method
        if name not in STATE["audio_files"]:
            fail(f"E03 - audio not found: {name}.wav")
        STATE["played"] = name
        return True, (), method

    if method == "ListFiles":
        raw_path = str(params[0]) if len(params) > 0 else ""
        pattern = str(params[1]) if len(params) > 1 and params[1] else ""
        try:
            max_entries = int(params[2]) if len(params) > 2 and params[2] else 200
        except (TypeError, ValueError):
            max_entries = 200
        max_entries = max(1, min(max_entries, 500))

        if not raw_path.strip():
            roots = [
                {"name": root, "is_dir": True, "size": 0}
                for root in _STORAGE_ROOTS
                if os.path.isdir(root)
            ]
            if not roots:
                fail("E03 - no hay ninguna carpeta montada")
            return True, roots, method

        path = _storage_safe(raw_path)
        if path is None:
            fail(f"E02 - ruta no permitida: {raw_path}")
        if not os.path.isdir(path):
            fail(f"E03 - no es una carpeta: {path}")
        try:
            names = sorted(os.listdir(path))
        except PermissionError:
            fail(f"E03 - sin permiso de lectura en {path}")
        except OSError as exc:
            fail(f"E03 - {exc}")
        entries = []
        for name in names:
            if pattern and not fnmatch.fnmatch(name, pattern):
                continue
            full = os.path.join(path, name)
            is_dir = os.path.isdir(full)
            try:
                size = 0 if is_dir else os.path.getsize(full)
            except OSError:
                size = 0
            entries.append({"name": name, "is_dir": is_dir, "size": size})
            if len(entries) >= max_entries:
                break
        return True, entries, method

    if method == "ReadFile":
        if not params or len(params) > 2:
            fail("E01 - Invalid number of parameter!")
        raw_path = str(params[0])
        try:
            max_bytes = int(params[1]) if len(params) > 1 and params[1] else 4000
        except (TypeError, ValueError):
            max_bytes = 4000
        max_bytes = max(1, min(max_bytes, 20000))
        path = _storage_safe(raw_path)
        if path is None:
            fail(f"E02 - ruta no permitida: {raw_path}")
        if not os.path.isfile(path):
            fail(f"E03 - no existe: {path}")
        try:
            with open(path, "rb") as handle:
                data = handle.read(max_bytes)
        except PermissionError:
            fail(f"E03 - sin permiso de lectura en {path}")
        except OSError as exc:
            fail(f"E03 - {exc}")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("latin-1", "replace")
        return True, (text, len(data) >= max_bytes), method

    if method == "Speak":
        if not params:
            fail("E01 - Invalid number of parameter!")
        STATE["spoken"] = str(params[0])
        return True, (), method

    fail(f"Method not found: {method}")


def _unwrap(raw: Any) -> Any:
    """La libreria `jsonrpc` desenvuelve tuplas de 3 elementos; las de 2 no."""
    if isinstance(raw, tuple) and len(raw) == 3 and isinstance(raw[0], bool):
        ok, data, _method = raw
        if not ok:
            raise RpcFailure(str(data), _method)
        return data
    return raw


class RPCHandler(BaseHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:
        pass

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        try:
            request = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self.send_error(400)
            return

        method = request.get("method", "")
        params = request.get("params", []) or []

        try:
            result = _unwrap(_dispatch(method, params))
        except RpcFailure as exc:
            body = {
                "jsonrpc": "2.0",
                "error": {"code": -32000, "message": exc.message, "data": exc.method},
                "id": request.get("id", 1),
            }
        else:
            body = {"jsonrpc": "2.0", "result": result, "id": request.get("id", 1)}

        payload = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(payload))
        self.end_headers()
        self.wfile.write(payload)


class MJPGHandler(BaseHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:
        pass

    def do_GET(self) -> None:
        jpeg = base64.b64decode(_JPEG_B64)
        if self.path == "/?action=snapshot":
            self.send_response(200)
            self.send_header("Content-type", "image/jpeg")
            self.send_header("Content-length", len(jpeg))
            self.end_headers()
            self.wfile.write(jpeg)
        else:
            self.send_response(200)
            self.send_header("Content-type", "multipart/x-mixed-replace; boundary=--b")
            self.end_headers()
            self.wfile.write(b"----b\r\n")
            self.end_headers()
            self.wfile.write(jpeg)


def main() -> None:
    rpc = ThreadingHTTPServer(("", RPC_PORT), RPCHandler)
    mjpg = ThreadingHTTPServer(("", MJPG_PORT), MJPGHandler)
    threading.Thread(target=rpc.serve_forever, daemon=True).start()
    threading.Thread(target=mjpg.serve_forever, daemon=True).start()
    print(f"[mock-robot] JSON-RPC en :{RPC_PORT} | camara en :{MJPG_PORT}")
    print("Ctrl-C para parar.")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\n[mock-robot] parado")


if __name__ == "__main__":
    main()

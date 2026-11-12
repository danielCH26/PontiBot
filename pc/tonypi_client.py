"""
Cliente JSON-RPC para el TonyPi (Hiwonder).

El robot arranca `TonyPi.py` como servicio systemd (`tonypi.service`), que a su
vez levanta dos servidores:

  * JSON-RPC 2.0 sobre HTTP  ->  puerto 9030   (RPCServer.py)
  * Snapshot / stream MJPEG  ->  puerto 8080   (MjpgServer.py)

Este módulo es una capa fina y legible sobre ese protocolo. No modifica nada del
robot: solo habla el idioma que el robot ya entiende.

Verificado contra el repo oficial:
  https://github.com/Hiwonder/TonyPi/blob/main/RPCServer.py
  https://github.com/Hiwonder/TonyPi/blob/main/MjpgServer.py
  https://github.com/Hiwonder/TonyPi/blob/main/Functions/Running.py
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

DEFAULT_HOST = os.environ.get("TONYPI_HOST", "192.168.1.100")
RPC_PORT = int(os.environ.get("TONYPI_RPC_PORT", "9030"))
MJPG_PORT = int(os.environ.get("TONYPI_MJPG_PORT", "8080"))
DEFAULT_TIMEOUT = float(os.environ.get("TONYPI_TIMEOUT", "10"))

# Codigos de funcion de vision (Functions/Running.py -> FUNCTIONS)
# OJO: los comentarios de Hiwonder estan desalineados; aqui manda el codigo real.
VISION_MODES: dict[str, int] = {
    "remote_control": 1,   # control remoto por joystick
    "kick_ball": 2,        # auto-disparo con vision
    "gesture": 3,          # control por gestos (MediaPipe)
    "line_follow": 4,      # seguimiento de linea (VisualPatrol)
    "color_track": 5,      # tracking de color con PID en la cabeza
    "face_detect": 6,      # deteccion de rostros (MediaPipe)
    "apriltag": 7,         # deteccion de tags AprilTag
    "transport": 8,        # transporte inteligente de objetos
    "lab_adjust": 9,       # ajuste de umbrales LAB
    "hurdles": 10,         # deporte: crossar vallas
    "stairs": 11,          # deporte: subir/bajar escaleras
    "color_classify": 12,  # clasificar bloques de color
}

# Modos que aceptan SetPoint / SetThreshold / GetRGBValue
POINT_MODES: dict[str, int] = {
    "kick_ball": 2,
    "line_follow": 4,
    "color_track": 5,
}

# Acciones de locomocion, mapeadas a sus action groups oficiales
LOCOMOTION: dict[str, str] = {
    "forward": "go_forward",
    "backward": "back",
    "left": "left_move",
    "right": "right_move",
    "turn_left": "turn_left",
    "turn_right": "turn_right",
}

# Gestos rapidos (ActionGroupDict.py)
NAMED_ACTIONS: dict[str, str] = {
    "stand": "立正 / quedarse quieto",
    "wave": "saludar con la mano",
    "bow": "hacer una reverencia",
    "chest": "celebrar",
    "squat": "agacharse",
    "push_ups": "flexiones",
    "sit_ups": "abdominales",
    "wing_chun": "wing chun",
    "left_uppercut": "gancho izquierdo",
    "right_uppercut": "gancho derecho",
    "left_kick": "patada izquierda",
    "right_kick": "patada derecha",
    "left_shot": "golpe izquierdo",
    "right_shot": "golpe derecho",
    "stepping": "caminar en el sitio",
    "twist": "girar la cintura",
    "stand_up_front": "levantarse tras caida frontal",
    "stand_up_back": "levantarse tras caida trasera",
}


class TonyPiError(RuntimeError):
    """Error devuelto por el robot (JSON-RPC error) o de transporte."""


class TonyPiClient:
    """Cliente del servidor JSON-RPC del TonyPi."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        rpc_port: int = RPC_PORT,
        mjpg_port: int = MJPG_PORT,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.host = host
        self.rpc_port = rpc_port
        self.mjpg_port = mjpg_port
        self.timeout = timeout
        # El GetRunningFunc del repo oficial esta hardcodeado a 0, asi que
        # llevamos our own registro de que vision hemos lanzado.
        self._vision_mode: str | None = None

    # ------------------------------------------------------------------ #
    # Transporte
    # ------------------------------------------------------------------ #
    @property
    def rpc_url(self) -> str:
        return f"http://{self.host}:{self.rpc_port}/"

    @property
    def snapshot_url(self) -> str:
        return f"http://{self.host}:{self.mjpg_port}/?action=snapshot"

    @property
    def stream_url(self) -> str:
        return f"http://{self.host}:{self.mjpg_port}/"

    def call(self, method: str, *params: Any) -> Any:
        """Invoca un metodo JSON-RPC del robot y devuelve el payload de `result`."""
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": list(params),
            "id": 1,
        }
        request = urllib.request.Request(
            self.rpc_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # el server devolvio 4xx/5xx
            detail = exc.read().decode("utf-8", "replace")
            raise TonyPiError(f"{method}: HTTP {exc.code} - {detail}") from exc
        except urllib.error.URLError as exc:
            raise TonyPiError(
                f"{method}: no se pudo contactar al robot en {self.rpc_url} ({exc.reason})"
            ) from exc
        except json.JSONDecodeError as exc:
            raise TonyPiError(f"{method}: respuesta no JSON del robot") from exc

        if "error" in body:
            error = body["error"]
            raise TonyPiError(
                f"{method}: {error.get('message')} [origen: {error.get('data')}]"
            )
        return self._normalize(body.get("result"))

    @staticmethod
    def _normalize(result: Any) -> Any:
        """
        El dispatcher de Hiwonder usa la convencion (ok, datos, metodo).

        - Si la libreria `jsonrpc` desenvuelve las tuplas de 3 elementos,
          `result` llega ya como los datos.
        - Si las devuelve tal cual, `result` es [ok, datos, metodo].
        - Varios metodos del repo devuelven una tupla de 2 elementos
          (ok, datos), que el servidor serializa como [[ok, datos]].

        Normalizamos las tres formas para no depender de ese detalle.
        """
        if not isinstance(result, (list, tuple)):
            return result
        # [[ok, datos]]  (tupla de 2 elementos sin desenvolver)
        if (
            len(result) == 1
            and isinstance(result[0], (list, tuple))
            and len(result[0]) == 2
            and isinstance(result[0][0], bool)
        ):
            return result[0][1]
        # [ok, datos] o [ok, datos, metodo]
        if len(result) in (2, 3) and isinstance(result[0], bool):
            return result[1]
        return result

    @staticmethod
    def _find_int(value: Any) -> int | None:
        """Primer entero dentro de una estructura anidada de listas y booleanos."""
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, (list, tuple)):
            for item in value:
                found = TonyPiClient._find_int(item)
                if found is not None:
                    return found
        return None

    # ------------------------------------------------------------------ #
    # Estado
    # ------------------------------------------------------------------ #
    def ping(self) -> bool:
        """True si el robot contesta."""
        try:
            self.call("echo", "ping")
            return True
        except TonyPiError:
            return False

    def get_running_func(self) -> int:
        """
        Codigo de la funcion de vision que el robot reporta.

        OJO: en el repo oficial este metodo esta hardcodeado a 0
        (`return (True, (0,))`), asi que devuelve 0 siempre. Para saber que
        vision esta corriendo de verdad, usa `last_vision_mode`.
        """
        return self._find_int(self.call("GetRunningFunc")) or 0

    def last_vision_mode(self) -> str | None:
        """Ultimo modo de vision que lanzo este cliente (None si no hay)."""
        return self._vision_mode

    # ------------------------------------------------------------------ #
    # Acciones
    # ------------------------------------------------------------------ #
    def run_action(self, action: str, times: int = 1) -> None:
        """
        Ejecuta un action group por nombre (o por su numero del app).

        times=0 significa "en bucle hasta que se detenga".
        """
        self.call("RunAction", str(action), int(times))

    def stop_action(self) -> None:
        self.call("StopBusServo", "stopAction")

    def stop_action_group(self) -> None:
        self.call("StopActionGroup", "stopActionGroup")

    def stand_up(self) -> None:
        """Recuperacion tras caida, usando el IMU."""
        self.call("StandUp")

    # ------------------------------------------------------------------ #
    # Locomocion
    # ------------------------------------------------------------------ #
    def walk(self, direction: str, steps: int = 1) -> None:
        """forward | backward | left | right | turn_left | turn_right."""
        try:
            action = LOCOMOTION[direction]
        except KeyError:
            raise TonyPiError(
                f"direccion desconocida: {direction!r}. "
                f"Opciones: {', '.join(LOCOMOTION)}"
            ) from None
        self.run_action(action, steps)

    # ------------------------------------------------------------------ #
    # Cabeza (servos PWM 1 y 2)
    # ------------------------------------------------------------------ #
    def set_head(self, pan: int | None = None, tilt: int | None = None, duration: int = 500) -> None:
        """
        Mueve la cabeza. pan/tilt van de 500 a 2500; 1500 es el centro.
        El servo 2 (tilt) recibe la calibracion del robot automaticamente.

        El robot espera la convencion [duracion_ms, numero_de_servos, servo, pulso, ...]
        (asi lo comprueba `SetBusServoPulse`/`SetPWMServo` del repo oficial).
        """
        if pan is None and tilt is None:
            raise TonyPiError("indica pan, tilt o ambos")
        pairs: list[int] = []
        if pan is not None:
            if not 500 <= pan <= 2500:
                raise TonyPiError("pan fuera de rango (500-2500)")
            pairs += [1, int(pan)]
        if tilt is not None:
            if not 500 <= tilt <= 2500:
                raise TonyPiError("tilt fuera de rango (500-2500)")
            pairs += [2, int(tilt)]
        self.call("SetPWMServo", int(duration), len(pairs) // 2, *pairs)

    def read_servo_positions(self) -> list[int]:
        """Posicion actual de los 16 servos del cuerpo."""
        return list(self.call("GetBusServosPulse", "angularReadback") or [])

    def set_body_servo(self, servo_id: int, pulse: int, duration: int = 500) -> None:
        """
        Control de bajo nivel de un servo del cuerpo (1-16, pulso 0-500, 250 = centro).
        Convencion del robot: [duracion_ms, numero_de_servos, servo, pulso].
        """
        if not 1 <= servo_id <= 16:
            raise TonyPiError("servo_id debe estar entre 1 y 16")
        if not 0 <= pulse <= 500:
            raise TonyPiError("pulse debe estar entre 0 y 500")
        self.call("SetBusServoPulse", int(duration), 1, int(servo_id), int(pulse))

    def get_deviations(self) -> list[int]:
        return list(self.call("GetBusServosDeviation", "readDeviation") or [])

    def save_deviations(self) -> None:
        self.call("SaveBusServosDeviation", "downloadDeviation")

    def power_down_servos(self) -> None:
        """Apaga los servos (el robot se queda sin fuerza)."""
        self.call("UnloadBusServo", "servoPowerDown")

    # ------------------------------------------------------------------ #
    # Sonido (requiere el parche opcional del robot)
    # ------------------------------------------------------------------ #
    def beep(self, freq: int = 2000, on_time: float = 0.1, off_time: float = 0.1, repeat: int = 1) -> None:
        """
        Pitido en el buzzer de la placa de expansion.

        NO viene en el firmware oficial: requiere el parche opcional de
        `robot_patch/apply_patch.py`.
        """
        self.call("SetBuzzer", int(freq), float(on_time), float(off_time), int(repeat))

    def play_audio(self, name: str) -> None:
        """
        Reproduce un sonido.

        Acepta un nombre suelto (del directorio audio/ del robot) o una ruta
        dentro de las carpetas montadas, por ejemplo "canciones/robot.mp3".

        NO viene en el firmware oficial: requiere el parche opcional.
        """
        self.call("PlayAudio", name)

    # ------------------------------------------------------------------ #
    # Almacenamiento (discos duros y carpetas montadas)
    # ------------------------------------------------------------------ #
    def list_files(self, path: str = "", pattern: str = "",
                   max_entries: int = 200) -> list[dict[str, Any]]:
        """
        Lista los ficheros de una carpeta montada en el robot.

        Con path="" devuelve las carpetas montadas que existen.
        Solo se ven las rutas permitidas (/media/pi, /mnt, /media/usb*...).

        NO viene en el firmware oficial: requiere el parche opcional.
        """
        result = self.call("ListFiles", path, pattern, int(max_entries))
        if isinstance(result, list):
            return result
        return []

    def read_file(self, path: str, max_bytes: int = 4000) -> tuple[str, bool]:
        """
        Lee un fichero de texto del robot. Devuelve (texto, truncado).

        NO viene en el firmware oficial: requiere el parche opcional.
        """
        result = self.call("ReadFile", path, int(max_bytes))
        if isinstance(result, (list, tuple)) and len(result) >= 2:
            return str(result[0]), bool(result[1])
        if isinstance(result, str):
            return result, False
        return "", False

    def say(self, text: str, backend: str = "espeak") -> None:
        """
        Sintetiza el texto y lo reproduce (piper o espeak).

        NO viene en el firmware oficial: requiere el parche opcional.
        """
        self.call("Speak", text, backend)

    # ------------------------------------------------------------------ #
    # Vision
    # ------------------------------------------------------------------ #
    def start_vision(self, mode: str) -> None:
        """Carga y arranca una funcion de vision (ver VISION_MODES)."""
        try:
            code = VISION_MODES[mode]
        except KeyError:
            raise TonyPiError(
                f"modo de vision desconocido: {mode!r}. "
                f"Opciones: {', '.join(VISION_MODES)}"
            ) from None
        self.call("LoadFunc", [code])
        self.call("StartFunc")
        self._vision_mode = mode

    def stop_vision(self) -> None:
        self.call("StopFunc")
        self.call("UnloadFunc")
        self._vision_mode = None

    def heartbeat(self) -> None:
        """Mantiene viva la funcion de vision cargada (caduca a los ~7 s)."""
        self.call("Heartbeat")

    def set_lab_value(self, color: str, min_lab: tuple[int, int, int], max_lab: tuple[int, int, int]) -> None:
        """
        Ajusta el umbral LAB de un color. Debe estar cargado 'lab_adjust'.

        El formato que espera el robot es:
            {"color": "red", "min": [l, a, b], "max": [l, a, b]}
        (asi lo lee Functions/lab_adjust.py -> setLABValue)
        """
        self.call("SetLABValue", {
            "color": color,
            "min": [int(v) for v in min_lab],
            "max": [int(v) for v in max_lab],
        })

    def get_lab_value(self) -> Any:
        """Umbrales LAB actuales: {color: {"min": [l,a,b], "max": [l,a,b]}}."""
        raw = self.call("GetLABValue")
        return self._unwrap_single(raw)

    @staticmethod
    def _unwrap_single(value: Any) -> Any:
        """Quita envoltorios de un solo elemento: [x] -> x, [[x]] -> x."""
        while isinstance(value, (list, tuple)) and len(value) == 1:
            value = value[0]
        return value

    def save_lab_value(self, color: str = "") -> None:
        self.call("SaveLABValue", color)

    def get_rgb_value(self, mode: str) -> Any:
        """Lee el color que la camara esta viendo en el modo indicado."""
        try:
            code = POINT_MODES[mode]
        except KeyError:
            raise TonyPiError(
                f"modo sin lectura RGB: {mode!r}. Opciones: {', '.join(POINT_MODES)}"
            ) from None
        return self.call("GetRGBValue", code)

    def set_point(self, mode: str, point: Any) -> None:
        """Fija el punto objetivo de deteccion (coordenadas x/y del objetivo)."""
        try:
            code = POINT_MODES[mode]
        except KeyError:
            raise TonyPiError(
                f"modo sin SetPoint: {mode!r}. Opciones: {', '.join(POINT_MODES)}"
            ) from None
        self.call("SetPoint", [code, point])

    def set_threshold(self, mode: str, value: Any) -> None:
        """Fija el umbral de deteccion del modo indicado."""
        try:
            code = POINT_MODES[mode]
        except KeyError:
            raise TonyPiError(
                f"modo sin SetThreshold: {mode!r}. Opciones: {', '.join(POINT_MODES)}"
            ) from None
        self.call("SetThreshold", [code, value])

    # ------------------------------------------------------------------ #
    # Camara
    # ------------------------------------------------------------------ #
    def snapshot(self) -> bytes:
        """Devuelve un JPEG con lo que ve la camara del robot."""
        try:
            with urllib.request.urlopen(self.snapshot_url, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.URLError as exc:
            raise TonyPiError(
                f"no se pudo capturar la camara en {self.snapshot_url} ({exc.reason})"
            ) from exc

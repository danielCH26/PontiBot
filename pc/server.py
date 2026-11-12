"""
Servidor MCP de PontiBot (el TonyPi de Hiwonder).

Expone el robot como herramientas MCP. Debajo no hay ninguna sdk propietaria:
se habla directamente el JSON-RPC que el robot ya publica en el puerto 9030
(ver `tonypi_client.py` y el repo oficial).

El servidor MCP corre donde quieras (PC, servidor, o la propia Raspberry Pi).
El robot solo tiene que estar encendido y en la misma red.

Arranque:
    python server.py                    # stdio (por defecto)
    TONYPI_HOST=192.168.1.50 python server.py

Configuracion de cliente MCP (Claude Desktop / Claude Code): ver
`mcp-config.example.json`.
"""

from __future__ import annotations

import base64
import os
import sys
from typing import Any

from tonypi_client import (
    LOCOMOTION,
    NAMED_ACTIONS,
    POINT_MODES,
    VISION_MODES,
    TonyPiClient,
    TonyPiError,
)

# --- Arranque del servidor MCP, compatible con varias versiones del SDK ---- #
try:  # SDK oficial >= 2.0  (la clase se renombro de FastMCP a MCPServer)
    from mcp.server import MCPServer as _Server  # type: ignore

    _SERVER_FLAVOR = "mcp>=2.0 (MCPServer)"
except ImportError:  # pragma: no cover
    try:  # SDK oficial 1.x
        from mcp.server.fastmcp import FastMCP as _Server  # type: ignore

        _SERVER_FLAVOR = "mcp 1.x (FastMCP)"
    except ImportError:  # pragma: no cover
        from fastmcp import FastMCP as _Server  # type: ignore

        _SERVER_FLAVOR = "fastmcp standalone"

# --- Imagen: helper de FastMCP si existe, si no base64 en texto ----------- #
try:  # pragma: no cover
    from fastmcp import Image as _Image  # type: ignore
except ImportError:  # pragma: no cover
    try:
        from mcp.server.fastmcp.utilities.types import Image as _Image  # type: ignore
    except ImportError:
        _Image = None  # type: ignore

mcp = _Server("pontibot")

robot = TonyPiClient(
    host=os.environ.get("TONYPI_HOST", "192.168.1.100"),
    rpc_port=int(os.environ.get("TONYPI_RPC_PORT", "9030")),
    mjpg_port=int(os.environ.get("TONYPI_MJPG_PORT", "8080")),
)

# Action groups presentes en /home/pi/TonyPi/ActionGroups del robot
ACTION_GROUPS: list[str] = [
    "0", "16", "17", "18", "19", "20", "21", "22", "23", "24",
    "back", "back_end", "back_fast", "back_one_step", "back_start",
    "bow", "catch_ball", "catch_ball_0", "catch_ball_go", "catch_ball_go_slow",
    "catch_ball_go_up", "catch_ball_left_move", "catch_ball_left_move_up",
    "catch_ball_right_move", "catch_ball_right_move_up", "catch_ball_up",
    "chest", "climb_stairs", "climb_stairs_1", "creep_forward", "down_floor",
    "down_floor_1", "down_objec", "go", "go_forward", "go_forward_end",
    "go_forward_fast", "go_forward_one_small_step", "go_forward_one_step",
    "go_forward_start", "go_forward_start_fast", "go_hand_up", "go_hand_up1",
    "grab_left", "grab_right", "grab_squat_left", "grab_squat_right",
    "grab_squat_up_left", "grab_squat_up_right", "grab_stand_left",
    "grab_stand_right", "huibi", "hurdles", "left_hand", "left_kick",
    "left_move", "left_move_10", "left_move_20", "left_move_30",
    "left_move_40", "left_move_fast", "left_shot", "left_shot_fast",
    "left_uppercut", "lie_down", "lift_down", "lift_left_hand", "lift_up",
    "move_up", "put_down", "put_down2", "put_down3", "put_down_object",
    "put_up_object", "right", "right_hand", "right_kick", "right_move",
    "right_move_10", "right_move_20", "right_move_30", "right_move_40",
    "right_move_fast", "right_shot", "right_shot_fast", "right_uppercut",
    "seize_down_right", "seize_right", "sit_ups", "squat", "squat_down",
    "squat_up", "stand", "stand_slow", "stand_up_back", "stand_up_front",
    "stepping", "temp1", "toulan_0", "toulan_a", "toulan_b", "turn_left",
    "turn_left_fast", "turn_left_small_step", "turn_left_small_step_a",
    "turn_right", "turn_right_fast", "turn_right_small_step",
    "turn_right_small_step_a", "twist", "wave", "wing_chun",
]

# Description helper: keep the tool list legible for the model
def _ok(payload: Any) -> str:
    return str(payload)


@mcp.tool()
def robot_ping() -> str:
    """Comprueba que el robot TonyPi esta encendido y responde. Devuelve 'ok' o el error."""
    return "ok" if robot.ping() else "sin respuesta"


@mcp.tool()
def robot_status() -> str:
    """
    Estado del robot: connectivity, que funcion de vision esta cargada y el
    numero de action groups disponibles.
    """
    alive = robot.ping()
    official = robot.get_running_func()
    last = robot.last_vision_mode()
    return (
        f"conectado={alive} | vision_oficial={official} | "
        f"ultimo_modo_lanzado={last or 'ninguno'} | "
        f"cuerpo_18dof | servo_cabeza=2 | acciones_disponibles={len(ACTION_GROUPS)}"
    )


@mcp.tool()
def robot_list_actions() -> str:
    """
    Lista los action groups disponibles para `robot_do_action`, agrupados por
    tipo (gestos, locomocio, Experts).
    """
    gestos = ", ".join(sorted(NAMED_ACTIONS))
    locomocion = ", ".join(f"{k}->{v}" for k, v in LOCOMOTION.items())
    return (
        f"GESTOS Y POSTURAS: {gestos}\n\n"
        f"LOCOMOCION: {locomocion}\n\n"
        f"TODOS LOS ACTION GROUPS ({len(ACTION_GROUPS)}): {', '.join(ACTION_GROUPS)}"
    )


@mcp.tool()
def robot_do_action(action: str, times: int = 1) -> str:
    """
    Ejecuta un action group del robot por su nombre.

    `action` debe ser uno de los nombres devueltos por `robot_list_actions`
    (por ejemplo: "wave", "bow", "chest", "push_ups", "squat", "stepping").
    `times` es el numero de repeticiones; usa 0 para repetir en bucle hasta
    llamar a `robot_stop`.
    """
    if action not in ACTION_GROUPS:
        return f"accion desconocida: {action!r}. Usa robot_list_actions para ver las validas."
    robot.run_action(action, times)
    return f"ejecutando {action} x{times}" + (" (en bucle)" if times == 0 else "")


@mcp.tool()
def robot_walk(direction: str, steps: int = 1) -> str:
    """
    Mueve al robot. `direction` puede ser: forward, backward, left, right,
    turn_left, turn_right. `steps` es el numero de repeticiones de la accion.
    """
    robot.walk(direction, steps)
    return f"robot caminando {direction} x{steps}"


@mcp.tool()
def robot_stop() -> str:
    """Detiene la accion en curso y para el movimiento."""
    robot.stop_action_group()
    robot.stop_action()
    return "robot detenido"


@mcp.tool()
def robot_look(pan: int = 1500, tilt: int = 1500, duration: int = 500) -> str:
    """
    Orienta la cabeza (camara de 2 grados de libertad). pan y tilt van de 500
    a 2500, donde 1500 es el centro. Valores altos miran a la derecha/arriba.
    """
    robot.set_head(pan, tilt, duration)
    return f"cabeza en pan={pan} tilt={tilt}"


@mcp.tool()
def robot_read_servos() -> str:
    """Lee la posicion actual (0-500) de los 16 servos del cuerpo."""
    positions = robot.read_servo_positions()
    return f"posiciones de servos: {positions}"


@mcp.tool()
def robot_set_body_servo(servo_id: int, pulse: int, duration: int = 500) -> str:
    """
    Control de bajo nivel de un servo del cuerpo (1-16, pulso 0-500, 250 = centro).
    Usar con precaution: puede dejar al robot en poses invalidas.
    """
    robot.set_body_servo(servo_id, pulse, duration)
    return f"servo {servo_id} -> {pulse}"


@mcp.tool()
def robot_start_vision(mode: str) -> str:
    """
    Arranca una funcion de vision del robot. `mode` puede ser:
    face_detect (detecta rostros y saluda), color_track (sigue un color),
    line_follow (sigue una linea), kick_ball (chatea solo), apriltag,
    transport (mueve objetos), gesture (responde a gestos), hurdles,
    stairs, color_classify, remote_control, lab_adjust.
    """
    robot.start_vision(mode)
    return f"vision '{mode}' cargada y en marcha"


@mcp.tool()
def robot_stop_vision() -> str:
    """Detiene y descarga la funcion de vision activa."""
    robot.stop_vision()
    return "vision detenida"


@mcp.tool()
def robot_vision_status() -> str:
    """
    Que funcion de vision esta corriendo. El GetRunningFunc del firmware oficial
    esta hardcodeado a 0, asi que el dato fiable es el ultimo modo lanzado
    desde este cliente.
    """
    official = robot.get_running_func()
    last = robot.last_vision_mode()
    return f"vision oficial={official} | ultimo modo lanzado={last or 'ninguno'}"


@mcp.tool()
def robot_set_color_threshold(
    color: str,
    l_min: int,
    a_min: int,
    b_min: int,
    l_max: int,
    a_max: int,
    b_max: int,
) -> str:
    """
    Ajusta el umbral LAB con el que el robot reconoce un color.
    Debe estar cargado el modo 'lab_adjust' (ver robot_start_vision).
    `color` por ejemplo: red, green, blue, yellow, black, white.
    Los valores son del espacio LAB: L (0-255), a y b (0-255).
    """
    robot.set_lab_value(color, (l_min, a_min, b_min), (l_max, a_max, b_max))
    return f"umbral de {color} actualizado"


@mcp.tool()
def robot_get_color_thresholds() -> str:
    """Devuelve los umbrales LAB que el robot tiene memorizados para cada color."""
    return str(robot.get_lab_value())


@mcp.tool()
def robot_read_camera_rgb(mode: str) -> str:
    """
    Lee el color que la camara del robot esta viendo ahora mismo.
    `mode` puede ser: kick_ball, line_follow, color_track.
    """
    return f"{mode}: {robot.get_rgb_value(mode)}"


@mcp.tool()
def robot_set_detection_point(mode: str, x: int, y: int) -> str:
    """
    Fija el punto objetivo de la deteccion (coordenadas de imagen) para
    kick_ball, line_follow o color_track.
    """
    robot.set_point(mode, [x, y])
    return f"punto de deteccion de {mode} -> ({x}, {y})"


@mcp.tool()
def robot_set_detection_threshold(mode: str, value: int) -> str:
    """
    Ajusta el umbral de deteccion de area/color para kick_ball, line_follow
    o color_track. Valores tipicos: 0-255 segun el modo.
    """
    robot.set_threshold(mode, value)
    return f"umbral de {mode} -> {value}"


@mcp.tool()
def robot_stand_up() -> str:
    """Levanta al robot si esta caido, usando el sensor IMU."""
    robot.stand_up()
    return "robot levantandose"


@mcp.tool()
def robot_camera_snapshot() -> Any:
    """
    Captura lo que ve la camara del robot y lo devuelve como imagen, para que
    puedas analizarlo. Perfecto para un modelo multimodal: el bot te muestra
    lo que tiene delante.
    """
    jpeg = robot.snapshot()
    if _Image is not None:
        return _Image(data=jpeg, format="jpeg")
    return "imagen JPEG en base64:\n" + base64.b64encode(jpeg).decode("ascii")


@mcp.tool()
def robot_power_down_servos() -> str:
    """
    Corta la alimentacion de los servos. El robot se queda sin fuerza.
    Usar solo para guardar o manipulation de bateria.
    """
    robot.power_down_servos()
    return "servos sin alimentacion"


@mcp.tool()
def robot_beep(frequency: int = 2000, repeat: int = 1) -> str:
    """
    Emite un pitido en el buzzer del robot. frequency en Hz (1000-3000),
    repeat numero de pitidos. Util como 'estoy pensando' o confirmacion.

    Requiere el parche opcional del robot (robot_patch/apply_patch.py).
    """
    try:
        robot.beep(frequency, 0.1, 0.1, repeat)
    except TonyPiError as exc:
        return f"no se pudo pitar: {exc} (aplica el parche opcional en el robot)"
    return f"pitido {frequency}Hz x{repeat}"


@mcp.tool()
def robot_play_audio(name: str) -> str:
    """
    Reproduce un archivo de sonido del robot.

    Acepta un nombre del directorio audio/ del robot (por ejemplo: "ok",
    "ready", "red", "green", "wave") o una ruta dentro de las carpetas
    montadas (por ejemplo: "canciones/robot.mp3" si el disco duro esta
    montado en /media/pi).

    Requiere el parche opcional del robot (robot_patch/apply_patch.py).
    """
    try:
        robot.play_audio(name)
    except TonyPiError as exc:
        return f"no se pudo reproducir {name!r}: {exc} (aplica el parche opcional en el robot)"
    return f"reproduciendo {name}"


@mcp.tool()
def robot_list_files(path: str = "", pattern: str = "", limit: int = 200) -> str:
    """
    Lista los ficheros de un disco duro o carpeta montada en el robot.

    Con path="" devuelve las carpetas montadas que hay ahora mismo.
    pattern es opcional (por ejemplo "*.mp3"). limit es el maximo de
    entradas (200 por defecto).

    Solo se ven las carpetas permitidas: /media/pi, /mnt, /media/usb* y la
    carpeta audio/ del robot.

    Requiere el parche opcional del robot (robot_patch/apply_patch.py).
    """
    try:
        entries = robot.list_files(path, pattern, int(limit))
    except TonyPiError as exc:
        return f"no se pudo listar {path or 'las carpetas montadas'!r}: {exc}"
    if not entries:
        return f"{path or 'raiz'}: sin entradas"
    lines = []
    for entry in entries:
        kind = "dir " if entry.get("is_dir") else "file"
        size = "" if entry.get("is_dir") else f"  {int(entry.get('size', 0))} B"
        lines.append(f"{kind}  {entry.get('name', '?')}{size}")
    header = f"{path or 'carpetas montadas'} ({len(entries)} entradas):"
    return header + "\n" + "\n".join(lines)


@mcp.tool()
def robot_read_file(path: str, max_bytes: int = 4000) -> str:
    """
    Lee el contenido de un fichero de texto del robot (del disco duro o de
    una carpeta montada). Por ejemplo, un .txt, .md o .csv.

    max_bytes limita lo que se lee (4000 por defecto, 20000 maximo).

    Requiere el parche opcional del robot (robot_patch/apply_patch.py).
    """
    try:
        text, truncated = robot.read_file(path, int(max_bytes))
    except TonyPiError as exc:
        return f"no se pudo leer {path!r}: {exc}"
    if not text:
        return f"{path}: vacio"
    return text + ("\n[...truncado...]" if truncated else "")


@mcp.tool()
def robot_list_audio(path: str = "") -> str:
    """
    Lista los ficheros de audio que el robot puede reproducir (wav, mp3, ogg...)
    de un disco duro o carpeta montada. Con path="" busca en todas las
    carpetas permitidas del robot.

    OJO: el listado ocurre EN EL ROBOT (por RPC), porque el disco esta
    conectado al robot, no a la maquina donde corre este servidor.

    Requiere el parche opcional del robot (robot_patch/apply_patch.py).
    """
    audio_extensions = (".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac", ".opus")
    found: list[str] = []

    def walk(folder: str, depth: int = 0) -> None:
        if len(found) >= 100 or depth > 3:
            return
        try:
            entries = robot.list_files(folder, "", 200)
        except TonyPiError:
            return
        for entry in entries:
            name = str(entry.get("name", ""))
            if entry.get("is_dir"):
                child = f"{folder.rstrip('/')}/{name}"
                walk(child, depth + 1)
            elif name.lower().endswith(audio_extensions):
                found.append(f"{folder.rstrip('/')}/{name}")

    if path:
        roots = [path]
    else:
        # Primero, las carpetas montadas que el robot tenga ahora mismo.
        try:
            roots = [str(entry.get("name", "")) for entry in robot.list_files("", "", 50)
                      if entry.get("is_dir")]
        except TonyPiError:
            roots = []
        roots += ["/media/pi", "/mnt", "/media/usb0", "/media/usb1",
                  "/home/pi/TonyPi/audio"]

    visited: set[str] = set()
    for root in roots:
        if not root or root in visited:
            continue
        visited.add(root)
        walk(root)

    if not found:
        return ("no hay ficheros de audio. Comprueba con storage_doctor.py "
                "si el disco esta montado y es legible")
    return "audio disponible:\n" + "\n".join(found[:100])


@mcp.tool()
def robot_say(text: str, backend: str = "espeak") -> str:
    """
    Hace que el robot diga un texto en voz alta. backend: piper (natural,
    local) o espeak (robotica, local).

    Requiere el parche opcional del robot (robot_patch/apply_patch.py).
    """
    try:
        robot.say(text, backend)
    except TonyPiError as exc:
        return f"no se pudo hablar: {exc} (aplica el parche opcional en el robot)"
    return f"dicho: {text}"


def main() -> None:
    print(f"[tonypi-mcp] {_SERVER_FLAVOR} -> robot en {robot.rpc_url}", file=sys.stderr)
    mcp.run()


if __name__ == "__main__":
    main()

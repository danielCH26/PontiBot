"""
Agente de voz end-to-end para PontiBot (el TonyPi de Hiwonder).

Ciclo completo, pensado para correr DENTRO del robot:

    microfono -> VAD -> ASR -> LLM -> herramientas -> TTS -> altavoz

Detalles que importan en un robot real:

  * VAD: el turno termina cuando TU dejas de hablar (ver vad.py).
  * Half-duplex: mientras el robot habla, el microfono esta ciego. Sin esto el
    robot se oye a si mismo y entra en bucle.
  * Memoria: PontiBot recuerda el hilo de la conversacion actual y, si el
    fichero de memoria esta en disco, tambien lo aprendido en sesiones
    anteriores (ver memory.py).
  * Dos backends de herramientas:
      - `--backend rpc` (por defecto): habla directo con el robot, sin
        dependencias. Es el que funciona aunque no haya MCP instalado.
      - `--backend mcp`: usa el servidor MCP como catalogo de herramientas,
        asi el LLM ve exactamente las mismas herramientas que ve Claude.

El LLM puede ser cualquier endpoint compatible con OpenAI:
NVIDIA NIM (gratis), OpenAI, OpenRouter o un llama-server local en la Pi.

Variables de entorno:
    LLM_API_KEY      clave del proveedor (nvapi-..., sk-...)
    LLM_BASE_URL    https://integrate.api.nvidia.com/v1 | https://api.openai.com/v1
    LLM_MODEL       p.ej. nvidia/nemotron-3.5-bolt-e4b
    ASR_BACKEND     openai | whispercpp | local_server   (default: whispercpp)
    ASR_MODEL       whisper-1 (openai) | small (whispercpp)
    ASR_SERVER_URL  http://127.0.0.1:8081 (si ASR_BACKEND=local_server)
    TTS_BACKEND     piper | espeak | openai   (default: piper)
    TTS_VOICE       alloy | echo | ... (openai)
    LLM_LANGUAGE    es | en                   (default: es)
    LLM_TEMPERATURE 0.0 - 1.0                (default: 0.6)
    TONYPI_HOST     IP del robot (si el agente corre en otra maquina)
    PONTIBOT_MEMORY ruta del fichero de memoria (default ~/.pontibot/memory.json)
    PONTIBOT_MAX_TURNS  cuantas intervenciones conserva en el hilo (default 12)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from typing import Any, Callable

from tonypi_client import NAMED_ACTIONS, TonyPiClient, TonyPiError
from vad import (
    LAST_TURN,
    SAMPLE_RATE,
    TurnConfig,
    VoiceActivityDetector,
    play_wav_bytes,
    record_turn,
)

# --------------------------------------------------------------------------- #
# Configuracion
# --------------------------------------------------------------------------- #

def _load_env_file() -> None:
    """
    Carga el .env de la carpeta del script (si existe).

    Las variables ya presentes en el entorno tienen prioridad: el .env es
    la configuracion por defecto, no una imposicion. Asi systemd puede
    sobreescribirlo con Environment= sin tocar el fichero.
    """
    # Se busca en la carpeta del script y tambien en la RAIZ del repo (una
    # carpeta por encima), que es donde vive de verdad.
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, ".env"),
        os.path.join(os.path.dirname(here), ".env"),
    ]
    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                for raw in handle:
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    os.environ.setdefault(key, value)
        except OSError:
            continue


_load_env_file()

LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/")
LLM_MODEL = os.environ.get("LLM_MODEL", "nvidia/nemotron-3.5-bolt-e4b")
ASR_BACKEND = os.environ.get("ASR_BACKEND", "whispercpp").lower()
ASR_MODEL = os.environ.get("ASR_MODEL", "base")
ASR_SERVER_URL = os.environ.get("ASR_SERVER_URL", "http://127.0.0.1:8081").rstrip("/")
# Dispositivo de entrada. Si es un fuente de PulseAudio (bluez_input.XX) el
# micro va por bluetooth; vacio = microfono ALSA por defecto.
ASR_DEVICE = os.environ.get("ASR_DEVICE", "").strip()
# Dispositivo de salida. Si es un sumidero de PulseAudio (bluez_output.XX) el
# audio sale por el auricular bluetooth; vacio = salida ALSA por defecto.
TTS_DEVICE = os.environ.get("TTS_DEVICE", "").strip()
TTS_BACKEND = os.environ.get("TTS_BACKEND", "piper").lower()
TTS_VOICE = os.environ.get("TTS_VOICE", "alloy")
LANGUAGE = os.environ.get("LLM_LANGUAGE", "es")
TEMPERATURE = float(os.environ.get("LLM_TEMPERATURE", "0.6"))

from prompts import BOT_NAME, SCENE_PROMPT, SYSTEM_PROMPT  # noqa: E402
from tool_parse import extract_inline_tool_calls, strip_inline_calls  # noqa: E402
from memory import ConversationMemory  # noqa: E402

# --------------------------------------------------------------------------- #
# Herramientas locales (backend rpc) -- el mismo catalogo que expone el MCP
# --------------------------------------------------------------------------- #
def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required}


def build_local_tools(robot: TonyPiClient) -> tuple[list[dict[str, Any]], dict[str, Callable]]:
    """
    Catalogo local de herramientas, por RPC directo.

    IMPORTANTE: los nombres y los parametros son EXACTAMENTE los mismos que
    los del servidor MCP (server.py). Si se divergen, el prompt del sistema
    (que habla de robot_do_action, robot_walk...) no cuadra con lo que el
    modelo ve, y el robot "habla" pero no se mueve nunca.
    """
    schemas: list[dict[str, Any]] = []
    impls: dict[str, Callable] = {}

    def register(name: str, description: str, schema: dict[str, Any], fn: Callable) -> None:
        schemas.append({"type": "function", "function": {"name": name, "description": description, "parameters": schema}})
        impls[name] = fn

    register(
        "robot_do_action",
        "Ejecuta un action group del robot por su nombre (wave, bow, chest, push_ups, "
        "squat, stepping...). `times` es el numero de repeticiones; usa 0 para repetir "
        "en bucle hasta llamar a robot_stop.",
        _schema(
            {"action": {"type": "string"},
             "times": {"type": "integer", "minimum": 0, "maximum": 10}},
            ["action"],
        ),
        _make_do_action(robot),
    )
    register(
        "robot_walk",
        "Mueve al robot. direction: forward, backward, left, right, turn_left, turn_right. "
        "steps es el numero de repeticiones de la accion.",
        _schema(
            {"direction": {"type": "string", "enum": ["forward", "backward", "left", "right", "turn_left", "turn_right"]},
             "steps": {"type": "integer", "minimum": 1, "maximum": 10}},
            ["direction"],
        ),
        _make_walk(robot),
    )
    register(
        "robot_stop",
        "Detiene la accion en curso y para el movimiento.",
        _schema({}, []),
        lambda: (robot.stop_action_group(), robot.stop_action(), "robot detenido")[2],
    )
    register(
        "robot_look",
        "Orienta la cabeza (camara de 2 grados de libertad). pan y tilt van de 500 a 2500, "
        "donde 1500 es el centro. Valores altos miran a la derecha/arriba.",
        _schema({"pan": {"type": "integer", "minimum": 500, "maximum": 2500},
                 "tilt": {"type": "integer", "minimum": 500, "maximum": 2500},
                 "duration": {"type": "integer", "minimum": 100, "maximum": 3000}},
                []),
        _make_look(robot),
    )
    register(
        "robot_start_vision",
        "Arranca una funcion de vision del robot. mode: face_detect (detecta rostros y "
        "saluda), color_track (sigue un color), line_follow, kick_ball, apriltag, "
        "transport, gesture, hurdles, stairs, color_classify.",
        _schema({"mode": {"type": "string"}}, ["mode"]),
        lambda mode: (robot.start_vision(mode), f"vision '{mode}' cargada y en marcha")[1],
    )
    register(
        "robot_stop_vision",
        "Detiene y descarga la funcion de vision activa.",
        _schema({}, []),
        lambda: (robot.stop_vision(), "vision detenida")[1],
    )
    register(
        "robot_camera_snapshot",
        "Mira con la camara y te dice lo que ve ahora mismo.",
        _schema({}, []),
        lambda: _describe_scene(robot),
    )
    register(
        "robot_read_camera_rgb",
        "Lee el color que la camara del robot esta viendo ahora mismo. "
        "mode: kick_ball, line_follow, color_track.",
        _schema({"mode": {"type": "string"}}, ["mode"]),
        lambda mode: (f"{mode}: {robot.get_rgb_value(mode)}"),
    )
    register(
        "robot_list_actions",
        "Lista los action groups que el robot sabe ejecutar (wave, bow, chest...).",
        _schema({}, []),
        lambda: ", ".join(sorted(NAMED_ACTIONS)),
    )
    register(
        "robot_list_files",
        "Lista los ficheros de un disco duro o carpeta montada en el robot. "
        "Con path vacio devuelve las carpetas montadas. pattern opcional (p.ej. '*.mp3').",
        _schema({"path": {"type": "string"},
                 "pattern": {"type": "string"},
                 "limit": {"type": "integer", "minimum": 1, "maximum": 500}}, []),
        _make_list_files(robot),
    )
    register(
        "robot_read_file",
        "Lee el contenido de un fichero de texto del robot (del disco duro o de "
        "una carpeta montada): .txt, .md, .csv...",
        _schema({"path": {"type": "string"},
                 "max_bytes": {"type": "integer", "minimum": 1, "maximum": 20000}},
                ["path"]),
        _make_read_file(robot),
    )
    register(
        "robot_list_audio",
        "Lista los ficheros de audio que el robot puede reproducir (wav, mp3, ogg...) "
        "de un disco duro o carpeta montada.",
        _schema({"path": {"type": "string"}}, []),
        _make_list_audio(robot),
    )
    return schemas, impls


def _make_list_files(robot: TonyPiClient) -> Callable:
    def list_files(path: str = "", pattern: str = "", limit: int = 200) -> str:
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
        return f"{path or 'carpetas montadas'} ({len(entries)} entradas):\n" + "\n".join(lines)
    return list_files


def _make_read_file(robot: TonyPiClient) -> Callable:
    def read_file(path: str, max_bytes: int = 4000) -> str:
        try:
            text, truncated = robot.read_file(path, int(max_bytes))
        except TonyPiError as exc:
            return f"no se pudo leer {path!r}: {exc}"
        if not text:
            return f"{path}: vacio"
        return text + ("\n[...truncado...]" if truncated else "")
    return read_file


def _make_list_audio(robot: TonyPiClient) -> Callable:
    audio_extensions = (".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac", ".opus")

    def list_audio(path: str = "") -> str:
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
                    walk(f"{folder.rstrip('/')}/{name}", depth + 1)
                elif name.lower().endswith(audio_extensions):
                    found.append(f"{folder.rstrip('/')}/{name}")

        if path:
            roots = [path]
        else:
            try:
                roots = [str(e.get("name", "")) for e in robot.list_files("", "", 50)
                         if e.get("is_dir")]
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
            return "no hay ficheros de audio. Comprueba con storage_doctor.py si el disco esta montado"
        return "audio disponible:\n" + "\n".join(found[:100])
    return list_audio


def _make_do_action(robot: TonyPiClient) -> Callable:
    def do_action(action: str, times: int = 1) -> str:
        if action not in NAMED_ACTIONS:
            return (f"accion desconocida: {action!r}. "
                    "Usa robot_list_actions para ver las validas.")
        robot.run_action(action, int(times))
        return f"ejecutando {action} x{times}" + (" (en bucle)" if int(times) == 0 else "")
    return do_action


def _make_walk(robot: TonyPiClient) -> Callable:
    def walk(direction: str, steps: int = 1) -> str:
        robot.walk(direction, int(steps))
        return f"robot caminando {direction} x{steps}"
    return walk


def _make_look(robot: TonyPiClient) -> Callable:
    def look(pan: int = 1500, tilt: int = 1500, duration: int = 500) -> str:
        robot.set_head(int(pan), int(tilt), int(duration))
        return f"cabeza en pan={pan} tilt={tilt}"
    return look


def _describe_scene(robot: TonyPiClient) -> str:
    """Manda un frame al LLM multimodal y devuelve su descripcion."""
    import base64

    jpeg = robot.snapshot()
    messages = [
        {"role": "system", "content": SCENE_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe en una frase breve lo que ve la camara del robot."},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()}},
            ],
        }
    ]
    return _chat(messages, tools=None, max_tokens=120)

# --------------------------------------------------------------------------- #
# LLM (compatible con OpenAI)
# --------------------------------------------------------------------------- #
def _chat(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
          max_tokens: int = 300) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": LLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": TEMPERATURE,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    request = urllib.request.Request(
        f"{LLM_BASE_URL}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LLM_API_KEY}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"LLM error HTTP {exc.code}: {detail[:400]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"no se pudo contactar al LLM: {exc.reason}") from exc
    return body["choices"][0]["message"]

# --------------------------------------------------------------------------- #
# ASR
# --------------------------------------------------------------------------- #
def transcribe(wav_bytes: bytes) -> str:
    """Transcribe audio WAV a texto segun ASR_BACKEND."""
    if ASR_BACKEND == "whispercpp":
        return _transcribe_whispercpp(wav_bytes)
    if ASR_BACKEND == "local_server":
        return _transcribe_server(wav_bytes)
    return _transcribe_openai(wav_bytes)


def _transcribe_whispercpp(wav_bytes: bytes) -> str:
    """whisper.cpp en local (gratis, offline). Requiere el binario `whisper`."""
    binary = shutil.which("whisper") or shutil.which("main")
    if not binary:
        raise RuntimeError(
            "ASR local no disponible: no encuentro el binario 'whisper'.\n"
            "  Opcion A (gratis, local):  bash setup_pi.sh --with-whisper\n"
            "  Opcion B (nube):            export ASR_BACKEND=openai y OPENAI_API_KEY=sk-...\n"
            "  Opcion C (servidor local):  export ASR_BACKEND=local_server"
        )
    model_path = os.environ.get("WHISPER_MODEL_PATH", f"models/ggml-{ASR_MODEL}.bin")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
        handle.write(wav_bytes)
        wav_path = handle.name
    try:
        subprocess.run(
            [binary, "-m", model_path, "-f", wav_path, "-l", LANGUAGE,
             "-nt", "-otxt", "-of", wav_path],
            check=True, capture_output=True, text=True,
        )
        with open(f"{wav_path}.txt", "r", encoding="utf-8") as handle:
            return handle.read().strip()
    finally:
        for suffix in ("", ".txt"):
            try:
                os.unlink(wav_path + suffix)
            except OSError:
                pass


def _transcribe_server(wav_bytes: bytes) -> str:
    """Servidor local compatible con OpenAI (whisper-server de whisper.cpp)."""
    boundary = "----tonypi"
    body = b""
    body += f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n'
    body += b"Content-Type: audio/wav\r\n\r\n" + wav_bytes + b"\r\n"
    body += f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="model"\r\n\r\n' + ASR_MODEL.encode() + b"\r\n"
    body += f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="language"\r\n\r\n' + LANGUAGE.encode() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()

    request = urllib.request.Request(
        f"{ASR_SERVER_URL}/v1/audio/transcriptions",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read().decode("utf-8"))["text"].strip()


def _transcribe_openai(wav_bytes: bytes) -> str:
    """Whisper API de OpenAI (nube)."""
    boundary = "----tonypi"
    body = b""
    body += f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n'
    body += b"Content-Type: audio/wav\r\n\r\n" + wav_bytes + b"\r\n"
    for name, value in (("model", ASR_MODEL), ("language", LANGUAGE)):
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
    body += f"--{boundary}--\r\n".encode()

    request = urllib.request.Request(
        "https://api.openai.com/v1/audio/transcriptions",
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY', LLM_API_KEY)}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read().decode("utf-8"))["text"].strip()

# --------------------------------------------------------------------------- #
# TTS
# --------------------------------------------------------------------------- #
def synthesize(text: str) -> bytes:
    """Convierte texto en audio WAV."""
    if not text.strip():
        return b""

    if TTS_BACKEND == "openai":
        request = urllib.request.Request(
            "https://api.openai.com/v1/audio/speech",
            data=json.dumps({"model": "gpt-4o-mini-tts", "voice": TTS_VOICE, "input": text}).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY', LLM_API_KEY)}"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            mp3 = response.read()
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as handle:
            handle.write(mp3)
            mp3_path = handle.name
        wav_path = mp3_path.replace(".mp3", ".wav")
        try:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp3_path, wav_path], check=True)
            with open(wav_path, "rb") as handle:
                return handle.read()
        finally:
            for path in (mp3_path, wav_path):
                try:
                    os.unlink(path)
                except OSError:
                    pass

    if TTS_BACKEND == "piper":
        binary = shutil.which("piper")
        if not binary:
            raise RuntimeError("no encuentro 'piper' (pip install piper-tts) — usa TTS_BACKEND=espeak")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            wav_path = handle.name
        try:
            subprocess.run([binary, "--output_file", wav_path], input=text, text=True, check=True)
            with open(wav_path, "rb") as handle:
                return handle.read()
        finally:
            try:
                os.unlink(wav_path)
            except OSError:
                pass

    # espeak-ng: offline, instantaneo, voz robotica pero siempre disponible
    binary = shutil.which("espeak-ng") or shutil.which("espeak")
    if not binary:
        raise RuntimeError("no encuentro espeak-ng ni espeak (apt install espeak-ng)")
    wav_path = tempfile.mktemp(suffix=".wav")
    try:
        subprocess.run([binary, "-v", "es" if LANGUAGE == "es" else "en", "-s", "165", "-w", wav_path, text],
                       check=True, capture_output=True)
        with open(wav_path, "rb") as handle:
            return handle.read()
    finally:
        try:
            os.unlink(wav_path)
        except OSError:
            pass

def _chat_loop(runner: ToolRunner, memory: ConversationMemory, speak: bool = False) -> None:
    """
    Chat por consola: escribes la orden, el bot responde por texto.

    Es el mismo cerebro que el modo de voz (mismo LLM, mismas herramientas, mismo
    robot). Aqui no hay microfono, ni TTS, ni VAD: solo texto.
    """
    print()
    print(f"  {BOT_NAME} · chat por consola")
    print("  Escribe lo que quieras y el bot lo ejecuta en el robot.")
    print("  /ayuda  ·ayuda · /herramientas · /memoria · /reset · /salir")
    print()

    try:
        import readline  # noqa: F401  (flechas arriba/abajo e historial)
    except ImportError:
        pass

    while True:
        try:
            line = input(f"{BOT_NAME.lower()}> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nhasta luego")
            return
        if not line:
            continue

        low = line.lower()
        if low in ("/salir", "/exit", "/quit", "salir", "exit", "quit"):
            print("hasta luego")
            return
        if low in ("/ayuda", "/help", "help", "?"):
            print("""
  Ordenes :
    saludar            -> el robot te saluda
    ponte de pie       -> se levanta
    haz una reverencia -> se inclina
    camina 3 pasos     -> avanza
    que ves            -> usa la camara y te lo describe
    para               -> detiene el movimiento

  Comandos :
    /herramientas  -> lista las herramientas disponibles
    /memoria       -> que recuerda de ti
    /reset         -> olvida la conversacion
    /salir         -> salir
""")
            continue
        if low in ("/herramientas", "/tools"):
            names = sorted({s["function"]["name"] for s in runner.schemas})
            print(f"  {len(names)} herramientas:")
            for n in names:
                print(f"    - {n}")
            continue
        if low in ("/memoria", "/memory"):
            print("  " + (memory.summary() or "aun no recuerdo nada de ti"))
            continue
        if low in ("/reset", "/olvidar"):
            memory.reset()
            print("  memoria borrada")
            continue

        try:
            answer = run_turn(runner, line, memory)
            memory.save()
        except Exception as exc:  # noqa: BLE001 - el chat no debe morir nunca
            print(f"  error: {exc}", file=sys.stderr)
            continue

        # Que se vea QUE ha hecho el robot, no solo lo que dice
        for msg in LAST_EXCHANGE:
            for call in msg.get("tool_calls") or []:
                fn = call.get("function", {})
                print(f"  -> {fn.get('name')}({fn.get('arguments', '')})")
            if msg.get("role") == "tool":
                content = (msg.get("content") or "").strip().replace("\n", " ")
                if content:
                    print(f"     {content[:160]}")

        print(f"  {BOT_NAME.lower()}: {answer}")

        if speak:
            audio = synthesize(answer)
            if audio:
                play_wav_bytes(audio, device=TTS_DEVICE or None)


# --------------------------------------------------------------------------- #
# Bucle principal
# --------------------------------------------------------------------------- #
class ToolRunner:
    """Ejecuta herramientas, ya sea por RPC directo o via el servidor MCP."""

    def __init__(self, backend: str, robot: TonyPiClient) -> None:
        self.backend = backend
        self.robot = robot
        if backend == "mcp":
            from mcp_bridge import MCPBridge

            self.bridge = MCPBridge(env={"TONYPI_HOST": robot.host})
            self.schemas = self.bridge.list_tools()
            self.impls: dict[str, Callable] = {}
        else:
            self.schemas, self.impls = build_local_tools(robot)
            self.bridge = None  # type: ignore[assignment]

    def call(self, name: str, arguments: dict[str, Any]) -> str:
        if self.backend == "mcp":
            assert self.bridge is not None
            return self.bridge.call(name, arguments)
        handler = self.impls.get(name)
        if handler is None:
            return f"herramienta desconocida: {name}"
        try:
            return str(handler(**arguments))
        except (TonyPiError, TypeError) as exc:
            return f"error ejecutando {name}: {exc}"


# Intercambio del ULTIMO turno (llamadas a herramientas y sus resultados).
# Se actualiza in situ para que el chat pueda mostrarlo.
LAST_EXCHANGE: list = []


def run_turn(runner: ToolRunner, utterance: str, memory: ConversationMemory) -> str:
    """
    Llamada al LLM con bucle de herramientas. Devuelve la respuesta final.

    La memoria guarda el hilo: el turno actual SIEMPRE ve lo que se dijo antes,
    tanto en esta sesion como en las anteriores (si la memoria esta en disco).

    El intercambio con las herramientas (llamada + resultado) se guarda TAMBIEN.
    No es un detalle estetico: si el historial solo guarda "assistant: Saludé",
    el modelo aprende de su propio ejemplo a contestar sin llamar a la
    herramienta, y el robot deja de moverse. Viendo la llamada en el historial,
    repite el patron correcto.
    """
    memory.begin_turn(utterance)
    known_tools = {schema["function"]["name"] for schema in runner.schemas}

    # Copia temporal: lo que se le manda al LLM en ESTE turno.
    messages = memory.messages()
    # Lo que quedara guardado en la memoria.
    exchange: list[dict[str, Any]] = []
    # Deteccion de bucles: la misma llamada repetida no es progreso.
    seen_calls: dict[str, int] = {}

    for _ in range(6):
        message = _chat(messages, tools=runner.schemas)
        calls = message.get("tool_calls") or []

        # Algunos modelos escriben la llamada como texto plano en vez de usar
        # el campo tool_calls. Si lo hacen, la recuperamos.
        if not calls:
            inline = extract_inline_tool_calls(message.get("content") or "", known_tools)
            if inline:
                calls = inline
                message = dict(message)
                message["tool_calls"] = inline
                message["content"] = strip_inline_calls(message.get("content") or "", known_tools)

        if not calls:
            answer = (message.get("content") or "").strip()
            if not answer:
                answer = _fallback_answer(exchange)
            LAST_EXCHANGE[:] = exchange
            memory.add_exchange(exchange)
            memory.end_turn(answer)
            return answer

        assistant_message = {
            "role": "assistant",
            "content": message.get("content") or "",
            "tool_calls": calls,
        }
        messages.append(assistant_message)
        exchange.append(assistant_message)

        for call in calls:
            function = call["function"]
            name = function["name"]
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError:
                arguments = {}
            signature = f"{name}:{json.dumps(arguments, sort_keys=True)}"
            seen_calls[signature] = seen_calls.get(signature, 0) + 1
            result = runner.call(name, arguments)
            tool_message = {
                "role": "tool",
                "tool_call_id": call.get("id", ""),
                "name": name,
                "content": str(result),
            }
            messages.append(tool_message)
            exchange.append(tool_message)

        # Si el modelo se queda repitiendo la misma llamada, se corta: no va a
        # llegar a una respuesta final y el robot se quedaria en bucle.
        if any(count >= 3 for count in seen_calls.values()):
            answer = _fallback_answer(exchange)
            LAST_EXCHANGE[:] = exchange
            memory.add_exchange(exchange)
            memory.end_turn(answer)
            return answer

    answer = "".join(m.get("content") or "" for m in messages[-3:]).strip()
    if not answer:
        answer = _fallback_answer(exchange)
    LAST_EXCHANGE[:] = exchange
    memory.add_exchange(exchange)
    memory.end_turn(answer)
    return answer


def _fallback_answer(exchange: list[dict[str, Any]]) -> str:
    """
    Respuesta de reserva.

    El modelo a veces vuelve con el contenido vacio (o se queda llamando
    herramientas en bucle). Callar del todo es lo peor que puede hacer un
    robot, asi que se dice algo corto y true.
    """
    did_something = any(message.get("role") == "tool" for message in exchange)
    return "Hecho." if did_something else "Te he oido. Repites?"


def _resolve_host(explicit: str | None) -> str:
    """
    Decide con que IP habla el agente.

    El caso normal es que el agente corra DENTRO del robot, asi que el robot
    esta en 127.0.0.1. Pero el mismo .env se puede usar desde un PC, donde
    hace falta la IP de la red. En vez de adivinar, se pregunta al robot:
    si el de loopback contesta, ese es el robot.
    """
    if explicit:
        return explicit
    try:
        if TonyPiClient(host="127.0.0.1", timeout=1.5).ping():
            return "127.0.0.1"
    except Exception:  # noqa: BLE001 - es una comprobacion, no un error
        pass
    return os.environ.get("TONYPI_HOST", "127.0.0.1").strip() or "127.0.0.1"


def main() -> None:
    parser = argparse.ArgumentParser(description=f"Agente de voz para {BOT_NAME}")
    parser.add_argument("--host", default=None,
                        help="IP del robot (por defecto, se detecta solo)")
    parser.add_argument("--backend", choices=["rpc", "mcp"], default="rpc")
    parser.add_argument("--max-seconds", type=float, default=12.0)
    parser.add_argument("--once", action="store_true", help="Una sola intervencion y salir")
    parser.add_argument("--text", default="", help="Procesa este texto en vez de usar el microfono")
    parser.add_argument("--chat", action="store_true",
                        help="Chat por consola: escribes la orden y el bot responde por texto")
    parser.add_argument("--speak", action="store_true",
                        help="En modo chat, leer tambien la respuesta en voz alta (experimental)")
    parser.add_argument("--memory", default=os.environ.get("PONTIBOT_MEMORY", ""),
                        help="Ruta del fichero de memoria (por defecto ~/.pontibot/memory.json)")
    parser.add_argument("--no-memory", action="store_true",
                        help="No recordar nada: cada turno empieza de cero")
    parser.add_argument("--reset-memory", action="store_true",
                        help="Olvida todo lo aprendido y sale")
    parser.add_argument("--max-turns", type=int,
                        default=int(os.environ.get("PONTIBOT_MAX_TURNS", "12")),
                        help="Cuantas intervenciones conservar en el hilo")
    args = parser.parse_args()

    if not LLM_API_KEY:
        print(f"[{BOT_NAME.lower()}] AVISO: falta LLM_API_KEY", file=sys.stderr)

    # --- memoria ------------------------------------------------------------
    memory = ConversationMemory(
        path=args.memory or None,
        max_turns=args.max_turns,
        persist=not args.no_memory,
    )
    if args.reset_memory:
        memory.reset()
        print(f"[{BOT_NAME.lower()}] memoria borrada")
        return

    robot = TonyPiClient(host=_resolve_host(args.host))
    runner = ToolRunner(args.backend, robot)
    config = TurnConfig(max_seconds=args.max_seconds)
    detector = VoiceActivityDetector(config=config)

    if args.chat:
        # En chat no hay microfono ni TTS: no alarmamos con avisos de audio.
        print(f"[{BOT_NAME.lower()}] backend={args.backend} llm={LLM_MODEL} "
              f"robot={robot.host}")
        _chat_loop(runner, memory, speak=args.speak)
        return

    print(f"[{BOT_NAME.lower()}] backend={args.backend} vad={detector.name} "
          f"asr={ASR_BACKEND} tts={TTS_BACKEND} llm={LLM_MODEL}")
    print(f"[{BOT_NAME.lower()}] microfono={ASR_DEVICE or 'ALSA por defecto'}  "
          f"altavoz={TTS_DEVICE or 'ALSA por defecto'}")

    # Aviso temprano si el ASR no esta disponible: es el fallo mas comun
    # ("el robot no me oye") y asi se ve en el log del servicio.
    if ASR_BACKEND == "whispercpp" and not (shutil.which("whisper") or shutil.which("main")):
        print(f"[{BOT_NAME.lower()}] AVISO: ASR local no disponible (falta el binario "
              f"'whisper'). El robot OIRA pero NO TRANSCRIBIRA lo que digas.")
        print(f"[{BOT_NAME.lower()}]   Solucion: bash setup_pi.sh --with-whisper")
        print(f"[{BOT_NAME.lower()}]   (o export ASR_BACKEND=openai con OPENAI_API_KEY)")
    if TTS_BACKEND not in ("espeak", "espeak-ng", "piper", "") and not shutil.which(TTS_BACKEND):
        print(f"[{BOT_NAME.lower()}] AVISO: TTS '{TTS_BACKEND}' no esta instalado: "
              f"no oiras la respuesta (instala espeak-ng o piper).")

    print(f"[{BOT_NAME.lower()}] {memory.greeting()}")
    if memory.profile or memory.notes:
        print(f"[{BOT_NAME.lower()}] recuerdo: {memory.summary()}")

    while True:
        try:
            if args.text:
                utterance = args.text
                args.text = ""
            else:
                print(f"[{BOT_NAME.lower()}] escuchando...")
                wav_bytes, spoke = record_turn(config=config, detector=detector,
                                                device=ASR_DEVICE or None)
                if not spoke:
                    rms = LAST_TURN.get("rms_max", 0.0)
                    thr = LAST_TURN.get("threshold", config.threshold)
                    secs = LAST_TURN.get("seconds", 0.0)
                    frames_n = LAST_TURN.get("frames", 0)
                    error = LAST_TURN.get("error", "")
                    if error:
                        print(f"[{BOT_NAME.lower()}] el grabador fallo: {error}")
                        print(f"[{BOT_NAME.lower()}]   comando: "
                              f"{LAST_TURN.get('command', '')}")
                        print(f"[{BOT_NAME.lower()}]   -> revisa el microfono y el servidor de audio: "
                              f"bash tools/audio_probe.sh")
                    elif frames_n == 0:
                        print(f"[{BOT_NAME.lower()}] el grabador no ha devuelto nada "
                              f"({secs:.1f}s, 0 muestras) -> bash tools/audio_probe.sh")
                    elif rms > 0.0005:
                        print(f"[{BOT_NAME.lower()}] no he entendido nada: RMS max "
                              f"{rms:.4f} < umbral {thr:.4f} en {secs:.1f}s")
                        print(f"[{BOT_NAME.lower()}]   -> habla mas cerca, o baja el umbral: "
                              f"VAD_THRESHOLD={max(round(thr / 3, 4), 0.001)} en el .env")
                    else:
                        print(f"[{BOT_NAME.lower()}] no he oido nada ({secs:.1f}s de silencio) "
                              f"-> revisa el microfono: bash tools/audio_probe.sh")
                    continue
                utterance = transcribe(wav_bytes)
                if not utterance:
                    continue

            fb = LAST_TURN.get("fallback", "")
            if fb:
                print(f"[{BOT_NAME.lower()}] OJO: he tenido que usar la {fb}")
                print(f"[{BOT_NAME.lower()}]   -> corrige ASR_DEVICE/TTS_DEVICE en el .env "
                      f"(pactl list short sources)")
            print(f"[{BOT_NAME.lower()}] oido: {utterance}")
            answer = run_turn(runner, utterance, memory)
            memory.save()
            print(f"[{BOT_NAME.lower()}] -> {answer}")

            # Half-duplex: el microfono esta ciego mientras suena la respuesta.
            audio = synthesize(answer)
            if audio:
                print(f"[{BOT_NAME.lower()}] hablando por {TTS_DEVICE or 'ALSA'} "
                      f"({len(audio)} bytes)")
                play_wav_bytes(audio, device=TTS_DEVICE or None)
            else:
                print(f"[{BOT_NAME.lower()}] AVISO: el TTS no ha generado audio "
                      f"(backend={TTS_BACKEND}) -> no oiras la respuesta", file=sys.stderr)

            if args.once:
                break
        except KeyboardInterrupt:
            print(f"\n[{BOT_NAME.lower()}] hasta luego")
            break
        except Exception as exc:  # noqa: BLE001 - queremos sobrevivir a cualquier fallo
            print(f"[{BOT_NAME.lower()}] error: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()

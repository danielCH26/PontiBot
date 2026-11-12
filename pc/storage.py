"""
Almacenamiento de PontiBot: discos, carpetas y ficheros.

El disco duro esta **en el robot**, asi que el listing y la lectura tienen que
ocurrir alli (por JSON-RPC). Este modulo tiene dos mitades:

  * La parte que corre en el ROBOT (la del parche del firmware): valida rutas
    y lista/lee ficheros.
  * La parte que corre en TU PC (el servidor MCP y el agente): decide que
    rutas son legitimas, formatea las respuestas y translate las llamadas.

Las rutas permitidas son las de las carpetas de montaje tipicas:

    /media/pi        (el nombre del usuario suele ser "pi")
    /mnt
    /media/usb0, /media/usb1 ...
    /home/pi/TonyPi/audio   (la carpeta de sonido del robot)

Se pueden ampliar con la variable de entorno STORAGE_ROOTS (separada por comas).
Todo es de SOLO LECTURA: el bot puede ver y leer, nunca escribir ni borrar.
"""

from __future__ import annotations

import os
import posixpath
import shlex

# Raices por defecto (las montadas de forma automatica en la Pi).
DEFAULT_ROOTS = [
    "/media/pi",
    "/mnt",
    "/media/usb0",
    "/media/usb1",
    "/media/usb2",
    "/home/pi/TonyPi/audio",
]

# Extensiones que el robot sabe reproducir.
AUDIO_EXTENSIONS = (".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac", ".opus")

# Extensiones que se consideran texto legible.
TEXT_EXTENSIONS = (
    ".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".xml", ".html", ".htm",
    ".py", ".sh", ".log", ".ini", ".cfg", ".conf", ".srt", ".vtt", ".rst",
)

MAX_READ_BYTES = 20000
MAX_LIST_ENTRIES = 500


def roots() -> list[str]:
    """Las carpetas donde se permite buscar, de la config o las de por defecto."""
    raw = os.environ.get("STORAGE_ROOTS", "").strip()
    if not raw:
        return list(DEFAULT_ROOTS)
    return [item.strip() for item in raw.split(",") if item.strip()]


def describe_roots() -> str:
    """Texto para el LLM: donde puede buscar el bot."""
    return ", ".join(roots())


def is_inside(path: str, root: str) -> bool:
    """¿El path (ya normalizado) está dentro de root?"""
    root = os.path.normpath(root)
    path = os.path.normpath(path)
    if path == root:
        return True
    return path.startswith(root.rstrip("/") + "/")


def safe_path(path: str) -> str | None:
    """
    Normaliza una ruta y comprueba que está dentro de las raíces permitidas.

    Devuelve la ruta absoluta, o None si la ruta es invalida o esta fuera.
    Rechaza "..", los enlaces simbolicos que escapen y las rutas relativas
    sueltas (se resuelven contra la primera raiz existente).
    """
    if path is None:
        return None
    path = str(path).strip()
    if not path:
        return None
    if "\x00" in path:
        return None

    candidates: list[str] = []
    if os.path.isabs(path):
        candidates.append(path)
    else:
        for root in roots():
            candidates.append(os.path.join(root, path))

    for candidate in candidates:
        normalized = os.path.normpath(candidate)
        if ".." in normalized.split(os.sep):
            continue
        for root in roots():
            if not is_inside(normalized, root):
                continue
            # El destino final (siguiendo enlaces) tambien debe estar dentro.
            real = os.path.realpath(normalized)
            real_root = os.path.realpath(root)
            if not (real == real_root or real.startswith(real_root.rstrip("/") + "/")):
                continue
            return normalized
    return None


def find_existing_roots() -> list[str]:
    """De las raíces permitidas, las que existen de verdad ahora mismo."""
    return [root for root in roots() if os.path.isdir(root)]


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def player_for(path: str) -> str:
    """Qué reproductor usar según la extensión (lo que haya instalado)."""
    extension = os.path.splitext(path)[1].lower()
    if extension == ".wav":
        return "aplay"
    if extension == ".mp3":
        return "mpg123"
    if extension in (".ogg", ".opus"):
        return "ogg123"
    if extension == ".flac":
        return "flac"
    if extension in (".m4a", ".aac"):
        return "ffplay"
    return "ffplay"


def format_listing(entries: list[dict], base: str) -> str:
    """Formatea la lista de ficheros para que la lea el LLM (o un humano)."""
    if not entries:
        return f"{base}: vacio (o sin permiso de lectura)"
    lines = []
    for entry in entries:
        kind = "dir " if entry.get("is_dir") else "file"
        size = "" if entry.get("is_dir") else f"  {human_size(int(entry.get('size', 0)))}"
        lines.append(f"{kind}  {entry.get('name', '?')}{size}")
    return f"{base} ({len(entries)} entradas):\n" + "\n".join(lines)


def shell_join(parts: list[str]) -> str:
    """Une argumentos para una linea de shell (lo usa el parche del robot)."""
    return " ".join(shlex.quote(part) for part in parts)


def normalize_relative(path: str) -> str:
    """Normaliza separadores y quita barras sobrantes (para comparar rutas)."""
    return posixpath.normpath("/" + str(path).replace("\\", "/")).lstrip("/")

"""
Parser de llamadas a herramientas escritas como texto plano.

Algunos modelos, cuando el prompt del sistema es largo o intricado, no usan el
campo `tool_calls` de la API: escriben la llamada dentro del contenido. Se han
visto cuatro formas distintas:

    robot_walk(direction="forward",steps="3")     <- parentesis
    robot_look{pan:2000,tilt:1500}                <- llaves
    robot_stop                                    <- nombre solo
    robot_look{pan:<|"|>2000<|"|>,tilt:<|"|>1500<|"|>}   <- llaves + tokens internos

Si no lo detectamos, el robot "responde" pero no se mueve nunca.

Este modulo convierte ese texto en llamadas con el mismo formato que devuelve
la API, para que el bucle del agente funcione igual.
"""

from __future__ import annotations

import json
import re
from typing import Any

# Marcadores internos que algunos modelos dejan filtrados en el texto.
_TOKEN_ARTIFACTS = re.compile(r"<\|[^|]*\|>")

# nombre seguido de parentesis o llaves
_CALL_PATTERN = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*([({])")


def _clean_artifacts(text: str) -> str:
    """Quita tokens internos tipo <|"|> que algunos modelos filtran."""
    return _TOKEN_ARTIFACTS.sub("", text)


def _find_balanced(text: str, start: int, opening: str, closing: str) -> str | None:
    """Contenido entre parentesis o llaves balanceados que empiezan en start."""
    depth = 0
    in_string: str | None = None
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_string:
                in_string = None
            continue
        if char in "\"'":
            in_string = char
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return text[start + 1:index]
    return None


def _parse_arguments(raw: str) -> dict[str, Any]:
    """
    Parsea los argumentos de una llamada escrita a mano.

    Acepta JSON ({"a": 1}) y el estilo keyword (a=1, b="x", c: 3).
    """
    raw = raw.strip()
    if not raw:
        return {}

    # JSON primero
    try:
        value = json.loads(raw)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass

    # estilo key=value o key: value
    arguments: dict[str, Any] = {}
    pattern = r"([A-Za-z_][A-Za-z0-9_]*)\s*[=:]\s*(\"[^\"]*\"|'[^']*'|[^,(){}]+)"
    for match in re.finditer(pattern, raw):
        key, value = match.group(1), match.group(2).strip()
        if value.startswith(("\"", "'")) and value.endswith(("\"", "'")):
            value = value[1:-1]
        else:
            lowered = value.lower()
            if lowered in ("true", "false"):
                value = lowered == "true"
            else:
                try:
                    value = int(value)
                except ValueError:
                    try:
                        value = float(value)
                    except ValueError:
                        value = value.strip().strip("\"'")
        arguments[key] = value
    return arguments


def _bare_tool_calls(content: str, known_tools: set[str]) -> list[tuple[int, int, str]]:
    """
    Detecta el nombre de una herramienta SOLO en su linea, sin parentesis.

        robot_stop
        Paré de moverme.

    Devuelve [(inicio, fin, nombre), ...]
    """
    found: list[tuple[int, int, str]] = []
    for name in known_tools:
        pattern = re.compile(rf"(?m)^[ \t]*{re.escape(name)}[ \t]*(\(\s*\))?[ \t]*$")
        for match in pattern.finditer(content):
            found.append((match.start(), match.end(), name))
    found.sort()
    return found


def extract_inline_tool_calls(content: str, known_tools: set[str]) -> list[dict[str, Any]]:
    """
    Busca llamadas a herramientas dentro de un texto y las devuelve con el
    formato de la API: [{"id":..., "type":"function", "function":{...}}]
    """
    if not content or not known_tools:
        return []

    calls: list[dict[str, Any]] = []
    clean = _clean_artifacts(content)
    consumed_until = 0

    for match in _CALL_PATTERN.finditer(clean):
        if match.start() < consumed_until:
            continue
        name = match.group(1)
        if name not in known_tools:
            continue
        opening = match.group(2)
        closer = ")" if opening == "(" else "}"
        raw_args = _find_balanced(clean, match.end() - 1, opening, closer)
        if raw_args is None:
            continue
        arguments = _parse_arguments(raw_args)
        calls.append({
            "id": f"call_inline_{len(calls) + 1}",
            "type": "function",
            "function": {
                "name": name,
                "arguments": json.dumps(arguments, ensure_ascii=False),
            },
        })
        consumed_until = match.end() + len(raw_args)

    if calls:
        return calls

    # forma desnuda: el nombre de la herramienta solo en su linea
    for _start, _end, name in _bare_tool_calls(clean, known_tools):
        calls.append({
            "id": f"call_inline_{len(calls) + 1}",
            "type": "function",
            "function": {"name": name, "arguments": "{}"},
        })
    return calls


def strip_inline_calls(content: str, known_tools: set[str]) -> str:
    """Quita del texto las llamadas inline para que no se lean en voz alta."""
    if not content:
        return content
    clean = _clean_artifacts(content)
    cleaned = clean

    for match in list(_CALL_PATTERN.finditer(clean)):
        name = match.group(1)
        if name not in known_tools:
            continue
        opening = match.group(2)
        closer = ")" if opening == "(" else "}"
        raw_args = _find_balanced(clean, match.end() - 1, opening, closer)
        if raw_args is None:
            continue
        start = match.start()
        # raw_args no incluye el cierre: hay que sumar 1
        end = match.end() + len(raw_args) + 1
        cleaned = cleaned[:start] + cleaned[end:]

    # forma desnuda
    for start, end, _name in _bare_tool_calls(cleaned, known_tools):
        cleaned = cleaned[:start] + cleaned[end:]

    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


if __name__ == "__main__":  # pragma: no cover
    known = {"robot_walk", "robot_stop", "robot_do_action", "robot_look", "robot_camera_snapshot"}
    demos = [
        'robot_walk(direction="forward",steps="3")\nYa avanzo tres pasos.',
        'robot_look{pan:<|"|>2000<|"|>,tilt:<|"|>1500<|"|>}\nLo miro a la derecha.',
        'robot_stop\nParé de moverme.',
        'El robot_stop no respondió y el robot_walk tampoco.',
    ]
    for demo in demos:
        calls = extract_inline_tool_calls(demo, known)
        print(f"{demo[:46]!r}")
        print(f"   -> {[(c['function']['name'], c['function']['arguments']) for c in calls]}")
        print(f"   limpio: {strip_inline_calls(demo, known)!r}")

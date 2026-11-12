"""
Memoria de PontiBot.

Tres niveles, de corto a largo:

  1. **Hilo de la conversacion actual** (en memoria): las ultimas
     intervenciones, tal y como se las pasa al LLM. Esto es lo que hace que
     "oye, y lo de antes?" funcione.
  2. **Perfil persistente** (en disco): los hechos que se deducen de lo que dice
     la persona ("me llamo Ana", "me gusta el cafe"). Sobrevive a reinicios.
  3. **Notas** (en disco): cosas que el bot decide recordar ("recuerda que
     el gate va el jueves").

El hilo guarda el intercambio COMPLETO de cada turno (la llamada a la
herramienta, su resultado y la respuesta final). No es un detalle: si en el
historial solo queda "assistant: Saludé", el modelo aprende de su propio
ejemplo a responder sin llamar a la herramienta, y el robot deja de moverse.
Guardando la llamada, el modelo ve el patron correcto.

El fichero es JSON y se escribe de forma atomica (tmp + rename), asi un corte
de luz a media escritura no deja la memoria corrupta.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from typing import Any

from prompts import BOT_NAME, build_system_prompt

MEMORY_VERSION = 2
DEFAULT_PATH = os.path.join(os.path.expanduser("~"), ".pontibot", "memory.json")

# --------------------------------------------------------------------------- #
# Extraccion de hechos
# --------------------------------------------------------------------------- #
# Los nombres propios empiezan por mayuscula; los motivos se cortan en la
# primera coma o signo de puntuacion.
#
# OJO: los patrones se buscan con re.IGNORECASE, asi que la parte del nombre
# propio va envuelta en (?-i:...) para que "me llamo Ana y mi color..." no
# capture "Ana y mi" (con IGNORECASE, [A-Z] tambien acepta minusculas).
_PROPER = r"[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ'\-]*(?:\s+[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ'\-]*){0,2}"
_PROPER_CS = r"(?-i:" + _PROPER + r")"
_UNTIL_STOP = r"([^,.!?;\n]{2,40})"

_FACT_PATTERNS: list[tuple[str, str]] = [
    (r"\bme llamo\s+(" + _PROPER_CS + r")\b", "nombre"),
    (r"\bmi nombre (?:es|se llama)\s+(" + _PROPER_CS + r")\b", "nombre"),
    (r"\b(?:ll[aá]mame|puedes llamarme)\s+(" + _PROPER_CS + r")\b", "como_llamarle"),
    (r"\bsoy\s+(" + _PROPER_CS + r")\b", "nombre"),
    (r"\bmi color favorito (?:es|ser[ií]a)\s+(" + _UNTIL_STOP + r")", "color_favorito"),
    (r"\bmi idioma favorito (?:es|ser[ií]a)\s+(" + _UNTIL_STOP + r")", "idioma_favorito"),
    (r"\b(?:vivo|estoy)\s+en\s+(" + _UNTIL_STOP + r")", "ciudad"),
    (r"\bmi trabajo es\s+(" + _UNTIL_STOP + r")", "ocupacion"),
    (r"\bme dedico a\s+(" + _UNTIL_STOP + r")", "ocupacion"),
]

# Conectores que pueden colgarse al final de una captura ("Ana y mi").
_TRAILING_JUNK = (
    "y", "o", "u", "e", "ni", "pero", "que", "mi", "tu", "su", "mis", "tus",
    "sus", "me", "te", "se", "lo", "la", "el", "los", "las", "un", "una",
    "unos", "unas", "de", "del", "al", "a", "en", "con", "por", "para",
)

_GUSTA_PATTERNS = [
    (r"\bme gusta\s+(" + _UNTIL_STOP + r")", "gusta"),
    (r"\bme encanta\s+(" + _UNTIL_STOP + r")", "gusta"),
    (r"\bno me gusta\s+(" + _UNTIL_STOP + r")", "no_gusta"),
    (r"\bno me apetece\s+(" + _UNTIL_STOP + r")", "no_gusta"),
]

# Las negativas se buscan PRIMERO y se tapan, para que "no me gusta X" no
# acabe tambien registrado como "me gusta X".
_NEGATIVE_GUST_PATTERNS = [
    r"\bno me gusta\s+" + _UNTIL_STOP,
    r"\bno me apetece\s+" + _UNTIL_STOP,
]

_NOTE_PATTERNS = [
    r"\brecuerda que\s+(.{3,140})",
    r"\bapunta(?:te)? que\s+(.{3,140})",
    r"\bno olvides que\s+(.{3,140})",
]

_CLEAN = re.compile(r"^[\s\"'`]+|[\s\"'`.!?]+$")

# Conectores que se quedan colgando al final de un gusto ("el jazz pero").
_TAIL_CONNECTORS = ("pero", "y", "o", "u", "e", "ni", "que", "porque", "aunque", "si")


def _tidy(value: str) -> str:
    value = _CLEAN.sub("", (value or "").strip())
    return re.sub(r"\s+", " ", value)


def _tidy_name(value: str) -> str:
    """Limpia un nombre propio y le quita conectores colgando."""
    value = _tidy(value)
    parts = value.split()
    while len(parts) > 1 and parts[-1].lower() in _TRAILING_JUNK:
        parts.pop()
    return " ".join(parts)


def _tidy_gusto(value: str) -> str:
    value = _tidy(value)
    parts = value.split()
    while len(parts) > 1 and parts[-1].lower() in _TAIL_CONNECTORS:
        parts.pop()
    return " ".join(parts)


def extract_facts(text: str) -> tuple[dict[str, str], list[str], list[tuple[str, str]]]:
    """
    Saca hechos de lo que ha dicho la persona.

    Devuelve (perfil, notas, listas) donde:
      - perfil: hechos de un solo valor (nombre, color favorito...)
      - notas:  frases que hay que recordar tal cual
      - listas: ("gusta" | "no_gusta", valor)
    """
    profile: dict[str, str] = {}
    notes: list[str] = []
    listas: list[tuple[str, str]] = []

    text = (text or "").strip()
    if not text:
        return profile, notes, listas

    for pattern, key in _FACT_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = _tidy_name(match.group(1)) if key in ("nombre", "como_llamarle") else _tidy(match.group(1))
            if value and len(value) > 1:
                profile[key] = value

    # Las frases negativas se tapan para que no se lean como positivas.
    remaining = text
    for pattern in _NEGATIVE_GUST_PATTERNS:
        for match in re.finditer(pattern, remaining, flags=re.IGNORECASE):
            remaining = remaining[:match.start()] + (" " * (match.end() - match.start())) + remaining[match.end():]

    for pattern, key in _GUSTA_PATTERNS:
        source = remaining if key == "gusta" else text
        for match in re.finditer(pattern, source, flags=re.IGNORECASE):
            value = _tidy_gusto(match.group(1))
            if value and len(value) > 1:
                listas.append((key, value))

    for pattern in _NOTE_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = _tidy(match.group(1))
            if value:
                notes.append(value)

    return profile, notes, listas


# --------------------------------------------------------------------------- #
# La memoria
# --------------------------------------------------------------------------- #
class ConversationMemory:
    """
    Hilo de conversacion + perfil persistente.

    El hilo se guarda por TURNOS, no por mensajes sueltos: cada turno es
    [pregunta, (llamada a herramienta + resultado)*, respuesta final]. Asi el
    recorte nunca deja una llamada a herramienta sin su respuesta, que es un
    mensaje invalido para la API.

    Uso normal:

        mem = ConversationMemory()
        mem.begin_turn("hola, me llamo Ana")
        mem.add_exchange([...])
        mem.end_turn("Hola Ana, soy PontiBot")
        messages = mem.messages()      # lo que se le pasa al LLM
        mem.save()
    """

    def __init__(self, path: str | None = None, max_turns: int = 12,
                 persist: bool = True) -> None:
        self.path = os.path.expanduser(path or DEFAULT_PATH)
        self.max_turns = max(1, int(max_turns))
        self.persist = persist
        self.profile: dict[str, str] = {}
        self.notes: list[str] = []
        self.turns: list[list[dict[str, Any]]] = []
        self._extra: dict[str, list[str]] = {}
        self._current: list[dict[str, Any]] | None = None
        if persist:
            self.load()

    # ---------------------------------------------------------------- datos --
    @property
    def system_prompt(self) -> str:
        """El prompt de sistema, con el perfil y las notas dentro."""
        profile = dict(self.profile)
        for key, values in self._extra.items():
            if values:
                profile[key] = ", ".join(values)
        return build_system_prompt(profile, self.notes)

    def messages(self) -> list[dict[str, Any]]:
        """Mensajes para el LLM: prompt de sistema + hilo de la conversacion."""
        flat: list[dict[str, Any]] = []
        for unit in self.turns:
            flat.extend(unit)
        return [{"role": "system", "content": self.system_prompt}] + flat

    @property
    def last_answer(self) -> str:
        """La ultima respuesta saida por el bot (util para tests y logs)."""
        for unit in reversed(self.turns):
            for message in reversed(unit):
                if message.get("role") == "assistant" and not message.get("tool_calls"):
                    return str(message.get("content") or "")
        return ""

    @property
    def flat_turns(self) -> list[dict[str, Any]]:
        """El hilo aplanado (comodo para inspeccionarlo)."""
        flat: list[dict[str, Any]] = []
        for unit in self.turns:
            flat.extend(unit)
        return flat

    # ------------------------------------------------------------- escritura --
    def begin_turn(self, text: str) -> None:
        """Empieza un turno con lo que ha dicho la persona."""
        text = (text or "").strip()
        if not text:
            return
        self._current = [{"role": "user", "content": text}]
        self.turns.append(self._current)
        self._learn(text)
        self._trim()

    def add_exchange(self, messages: list[dict[str, Any]]) -> None:
        """Guarda el intercambio con herramientas de este turno."""
        if self._current is None:
            return
        for message in messages:
            item = dict(message)
            content = item.get("content")
            if isinstance(content, str) and len(content) > 400:
                item["content"] = content[:400] + "..."
            self._current.append(item)

    def end_turn(self, answer: str) -> None:
        """Cierra el turno con la respuesta final del bot."""
        answer = (answer or "").strip()
        if self._current is None:
            return
        self._current.append({"role": "assistant", "content": answer})
        self._current = None
        self._trim()

    def add_user(self, text: str) -> None:
        """Atajo: abre un turno con el texto de la persona."""
        self.begin_turn(text)

    def add_assistant(self, text: str) -> None:
        """Atajo: cierra el turno con la respuesta del bot."""
        self.end_turn(text)

    def _learn(self, text: str) -> None:
        """Extrae hechos de lo que dice la persona y los guarda."""
        profile, notes, listas = extract_facts(text)
        for key, value in profile.items():
            self.profile[key] = value
        for note in notes:
            if note not in self.notes:
                self.notes.append(note)
                self.notes = self.notes[-8:]
        for key, value in listas:
            bucket = self._extra.setdefault(key, [])
            if value not in bucket:
                bucket.append(value)
                self._extra[key] = bucket[-6:]

    def _trim(self) -> None:
        """Mantiene solo los ultimos `max_turns` turnos."""
        if len(self.turns) > self.max_turns:
            self.turns = self.turns[-self.max_turns:]
            if self._current is not None and self._current not in self.turns:
                self._current = None

    # ------------------------------------------------------------ persistencia
    def to_dict(self) -> dict[str, Any]:
        return {
            "version": MEMORY_VERSION,
            "profile": self.profile,
            "notes": self.notes,
            "listas": self._extra,
            "turns": self.turns,
            "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

    def save(self) -> bool:
        if not self.persist:
            return False
        try:
            folder = os.path.dirname(self.path)
            if folder:
                os.makedirs(folder, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=folder or ".", delete=False, suffix=".tmp"
            )
            try:
                json.dump(self.to_dict(), handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                handle.close()
            os.replace(handle.name, self.path)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
            return True
        except OSError:
            return False

    def load(self) -> bool:
        if not os.path.exists(self.path):
            return False
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return False
        if not isinstance(data, dict):
            return False

        profile = data.get("profile")
        self.profile = {str(k): str(v) for k, v in profile.items()} if isinstance(profile, dict) else {}
        notes = data.get("notes")
        self.notes = [str(n) for n in notes][:8] if isinstance(notes, list) else []
        listas = data.get("listas")
        self._extra = {
            str(k): [str(v) for v in vals][:6]
            for k, vals in listas.items() if isinstance(vals, list)
        } if isinstance(listas, dict) else {}

        turns = data.get("turns")
        self.turns = []
        if isinstance(turns, list):
            for unit in turns:
                if isinstance(unit, list):
                    messages = [m for m in unit if isinstance(m, dict)]
                elif isinstance(unit, dict):  # formato plano de la version 1
                    messages = [unit]
                else:
                    continue
                clean = [
                    m for m in messages
                    if m.get("role") in ("user", "assistant", "tool")
                ]
                if clean:
                    self.turns.append(clean)
        self.turns = self.turns[-self.max_turns:]
        return True

    def reset(self) -> None:
        """Olvida todo: perfil, notas e hilo."""
        self.profile = {}
        self.notes = []
        self._extra = {}
        self.turns = []
        self._current = None
        if self.persist:
            try:
                os.unlink(self.path)
            except OSError:
                pass

    # ------------------------------------------------------------------ varios
    def summary(self) -> str:
        """Resumen legible, para diagnostics y para el arranque del agente."""
        lines = [f"{BOT_NAME}: {len(self.turns)} turnos en el hilo"]
        if self.profile:
            lines.append("perfil: " + ", ".join(f"{k}={v}" for k, v in self.profile.items()))
        if self.notes:
            lines.append("notas: " + " | ".join(self.notes))
        return "\n".join(lines)

    def greeting(self) -> str:
        """Saludo de arranque, personalizado con lo que recuerda."""
        name = (self.profile.get("nombre") or "").strip()
        if name:
            return f"Hola {name}. Soy {BOT_NAME}, ya te conozco."
        return f"Soy {BOT_NAME}. Te escucho."


if __name__ == "__main__":  # pragma: no cover - uso manual
    import sys

    mem = ConversationMemory(path=sys.argv[1] if len(sys.argv) > 1 else None)
    print(mem.summary())

"""
Prueba en vivo de la memoria de PontiBot contra el LLM real.

Comprueba lo que de verdad importa: que PontiBot RECUERDE.

    export NVIDIA_API_KEY=nvapi-...
    export LLM_API_KEY=$NVIDIA_API_KEY
    python test_live_memory.py

Hace una conversacion de 3 turnos:
    1. "me llamo Ana y mi color favorito es el azul"
    2. "como me llamo?"
    3. "cual es mi color favorito?"

Si la memoria funciona, las respuestas 2 y 3 deben mencionar "Ana" y "azul"
sin que se le vuelva a preguntar nada.

Tambien comprueba que el robot se identifica como PontiBot.
"""

from __future__ import annotations

import os
import sys

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

from memory import ConversationMemory  # noqa: E402
from prompts import BOT_NAME  # noqa: E402

PASSED = 0
FAILED = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ok   {label}")
    else:
        FAILED += 1
        print(f"  FAIL {label}  {detail}")


def main() -> int:
    key = os.environ.get("LLM_API_KEY") or os.environ.get("NVIDIA_API_KEY")
    if not key:
        print("FALTA LLM_API_KEY / NVIDIA_API_KEY")
        return 1
    os.environ["LLM_API_KEY"] = key
    os.environ.setdefault("NVIDIA_API_KEY", key)

    import voice_agent

    host = os.environ.get("TONYPI_HOST", "127.0.0.1")
    memory = ConversationMemory(path=None, persist=False)
    runner = voice_agent.ToolRunner("rpc", voice_agent.TonyPiClient(host=host))

    def ask(text: str) -> str:
        print(f"\n  > {text}")
        answer = voice_agent.run_turn(runner, text, memory)
        print(f"  < {answer}")
        return answer.lower()

    print("=== conversacion en vivo con PontiBot ===")

    answer1 = ask("Me llamo Ana y mi color favorito es el azul")
    check("responde a la primera frase", bool(answer1.strip()), answer1)
    check("el perfil guardo el nombre", memory.profile.get("nombre") == "Ana", str(memory.profile))
    check("el perfil guardo el color",
          "azul" in (memory.profile.get("color_favorito") or ""), str(memory.profile))

    answer2 = ask("Oye, como me llamo?")
    check("RECUERDA el nombre", "ana" in answer2, answer2)

    answer3 = ask("Y cual es mi color favorito?")
    check("RECUERDA el color favorito", "azul" in answer3, answer3)

    answer4 = ask("Quien eres?")
    check("se identifica como PontiBot", BOT_NAME.lower() in answer4, answer4)
    check("se identifica en espanol",
          not any(w in answer4 for w in ("i am", "my name is")), answer4)

    print(f"\nOK: {PASSED}   FALLOS: {FAILED}")
    if FAILED:
        print("\nSi falla 'RECUERDA el nombre', mira si el prompt de sistema")
        print("lleva la seccion 'Lo que sabes de quien estas hablando'.")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

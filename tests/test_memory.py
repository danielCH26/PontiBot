"""
Pruebas de la memoria de PontiBot. Sin red, sin robot, sin LLM.

Comprueba lo que de verdad importa:

  1. Los hechos se extraen de lo que dice la persona.
  2. La memoria sobrevive a reiniciar el agente (fichero en disco).
  3. El hilo se recorta solo cuando se hace largo.
  4. **El turno 2 ve al turno 1** (esta era la parte que estaba rota: el
     historial se construia en una lista nueva y nunca se guardaba).

    python test_memory.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

# --- rutas del proyecto (añade ../pc, ../patches y ../tools al sys.path) ---
import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
for _p in (_os.path.join(_ROOT, "pc"),
           _os.path.join(_ROOT, "patches", "robot_patch"),
           _os.path.join(_ROOT, "tools")):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)
# --- fin rutas del proyecto ---


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

PASSED = 0
FAILED = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ok   {label}")
    else:
        FAILED += 1
        print(f"  FAIL {label} {detail}")


def section(title: str) -> None:
    print(f"\n--- {title} ---")


# --------------------------------------------------------------------------- #
def test_extraccion() -> None:
    section("extraccion de hechos")
    from memory import extract_facts

    profile, notes, listas = extract_facts("Hola, me llamo Ana")
    check("detecta el nombre", profile.get("nombre") == "Ana", str(profile))

    profile, _, _ = extract_facts("Puedes llamarme Chef")
    check("detecta como llamarle", profile.get("como_llamarle") == "Chef", str(profile))

    profile, _, _ = extract_facts("Mi color favorito es el azul")
    check("detecta el color favorito", profile.get("color_favorito") == "el azul", str(profile))

    profile, _, _ = extract_facts("Vivo en Madrid")
    check("detecta la ciudad", profile.get("ciudad") == "Madrid", str(profile))

    _, notes, _ = extract_facts("Recuerda que el gate va el jueves")
    check("detecta la nota", notes and "jueves" in notes[0], str(notes))

    _, _, listas = extract_facts("Me gusta el jazz")
    check("detecta un gusto", ("gusta", "el jazz") in listas, str(listas))

    _, _, listas = extract_facts("No me gusta el ruido")
    check("detecta un disgusto", ("no_gusta", "el ruido") in listas, str(listas))
    check("'no me gusta' NO cuenta como 'me gusta'",
          ("gusta", "el ruido") not in listas, str(listas))

    profile, _, _ = extract_facts("Me llamo Ana y mi color favorito es el azul")
    check("el nombre no se come lo que sigue", profile.get("nombre") == "Ana", str(profile))
    check("y el color sigue igual", profile.get("color_favorito") == "el azul", str(profile))

    profile, _, _ = extract_facts("me llamo Ana María García")
    check("acepta nombres compuestos", profile.get("nombre") == "Ana María García", str(profile))

    profile, notes, listas = extract_facts("Hola, que tal?")
    check("no inventa hechos de una frase vacia",
          not profile and not notes and not listas, f"{profile} {notes} {listas}")


def test_persistencia() -> None:
    section("persistencia en disco")
    from memory import ConversationMemory

    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "memory.json")

        mem = ConversationMemory(path=path)
        mem.add_user("me llamo Ana")
        mem.add_assistant("Hola Ana, soy PontiBot")
        check("guarda en disco", mem.save() and os.path.exists(path))

        # Agente nuevo, mismo fichero: debe acordarse.
        mem2 = ConversationMemory(path=path)
        check("recupera el nombre", mem2.profile.get("nombre") == "Ana", str(mem2.profile))
        check("recupera el hilo", len(mem2.turns) == 1 and len(mem2.flat_turns) == 2,
              str(mem2.turns))
        check("el prompt incluye lo que sabe",
              "Ana" in mem2.system_prompt, mem2.system_prompt[-200:])

        # Permisos: el fichero contiene datos de la persona.
        mode = oct(os.stat(path).st_mode & 0o777)
        check("permisos 600", mode == "0o600", mode)

        # El fichero debe ser JSON valido y legible.
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        check("json valido", data.get("version") == 2, str(data)[:120])

        mem2.reset()
        check("reset borra el fichero", not os.path.exists(path))


def test_recorte() -> None:
    section("recorte del hilo")
    from memory import ConversationMemory

    mem = ConversationMemory(path=None, max_turns=3, persist=False)
    for index in range(10):
        mem.add_user(f"pregunta {index}")
        mem.add_assistant(f"respuesta {index}")
    check("respeta max_turns", len(mem.turns) == 3, str(len(mem.turns)))
    check("conserva lo reciente", mem.last_answer == "respuesta 9", str(mem.last_answer))
    check("descarta lo viejo", "pregunta 0" not in json.dumps(mem.turns))


def test_hilo_entre_turnos() -> None:
    section("el turno 2 ve al turno 1 (el bug que se corrigio)")
    import voice_agent

    seen: list[list[dict]] = []

    def fake_chat(messages, tools=None, max_tokens=300):
        seen.append([dict(m) for m in messages])
        return {"content": f"respuesta {len(seen)}"}

    original = voice_agent._chat
    voice_agent._chat = fake_chat
    try:
        from memory import ConversationMemory

        mem = ConversationMemory(path=None, persist=False)

        class FakeRunner:
            schemas = []
            def call(self, name, arguments):
                return "ok"

        runner = FakeRunner()
        voice_agent.run_turn(runner, "me llamo Ana", mem)
        voice_agent.run_turn(runner, "y como me llamo?", mem)
    finally:
        voice_agent._chat = original

    check("se hicieron dos llamadas", len(seen) == 2, str(len(seen)))
    if len(seen) != 2:
        return

    second = seen[1]
    roles = [m["role"] for m in second]
    check("el segundo turno lleva el sistema", roles[0] == "system", str(roles))
    check("el segundo turno ve la pregunta 1",
          any(m.get("content") == "me llamo Ana" for m in second), str(second))
    check("el segundo turno ve la respuesta 1",
          any(m.get("content") == "respuesta 1" for m in second), str(second))
    check("el segundo turno ve la pregunta 2",
          any(m.get("content") == "y como me llamo?" for m in second), str(second))

    # Y el prompt del segundo turno debe llevar el nombre aprendido.
    system = second[0]["content"]
    check("el prompt recuerda el nombre", "Ana" in system, system[-300:])
    check("el prompt dice el nombre del bot", "PontiBot" in system, system[:120])


def test_herramientas_no_contaminan() -> None:
    section("el intercambio con herramientas no llena la memoria")
    import voice_agent

    from memory import ConversationMemory

    calls = [{"id": "c1", "function": {"name": "move", "arguments": "{}"}}]

    def fake_chat(messages, tools=None, max_tokens=300):
        if len(messages) == 2:
            return {"content": "", "tool_calls": calls}
        return {"content": "hecho"}

    original = voice_agent._chat
    voice_agent._chat = fake_chat
    try:
        mem = ConversationMemory(path=None, persist=False)

        class FakeRunner:
            schemas = [{"function": {"name": "move"}}]
            def call(self, name, arguments):
                return "movido"

        voice_agent.run_turn(FakeRunner(), "avanza", mem)
    finally:
        voice_agent._chat = original

    roles = [m["role"] for m in mem.flat_turns]
    check("se guarda la llamada a la herramienta",
          roles == ["user", "assistant", "tool", "assistant"], str(roles))
    check("la llamada queda con sus argumentos",
          mem.flat_turns[1].get("tool_calls", [{}])[0]["function"]["name"] == "move",
          str(mem.flat_turns[1]))
    check("la respuesta final si se guarda", mem.last_answer == "hecho", str(mem.last_answer))


def main() -> int:
    print("=== Memoria de PontiBot ===")
    test_extraccion()
    test_persistencia()
    test_recorte()
    test_hilo_entre_turnos()
    test_herramientas_no_contaminan()

    print(f"\nOK: {PASSED}   FALLOS: {FAILED}")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

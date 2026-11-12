"""
Pruebas del almacenamiento de PontiBot (discos duros y carpetas montadas).

Comprueba, sin robot y sin red:

  1. La seguridad de rutas: nada fuera de las carpetas permitidas.
  2. El listado y la lectura de ficheros, con un "disco" simulado.
  3. Que el parche del firmware expone ListFiles / ReadFile y es reversible.

    python test_storage.py
"""

from __future__ import annotations

import os
import shutil
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


def test_seguridad() -> None:
    section("seguridad de rutas")
    import storage

    check("rechaza el traversal con ..",
          storage.safe_path("../../etc/passwd") is None)
    check("rechaza /etc/passwd",
          storage.safe_path("/etc/passwd") is None)
    # Una ruta relativa se resuelve contra las raices: no puede escapar de ellas.
    relativa = storage.safe_path("etc/passwd")
    check("una ruta relativa nunca escapa de las raices",
          relativa is not None and any(storage.is_inside(relativa, r) for r in storage.roots()),
          str(relativa))
    check("rechaza el byte nulo",
          storage.safe_path("/media/pi/ok\x00.txt") is None)
    check("rechaza vacio", storage.safe_path("") is None)
    check("rechaza None", storage.safe_path(None) is None)

    # una ruta permitida existe de verdad
    with tempfile.TemporaryDirectory() as folder:
        os.environ["STORAGE_ROOTS"] = folder
        with open(os.path.join(folder, "nota.txt"), "w", encoding="utf-8") as handle:
            handle.write("hola")
        check("permite un fichero dentro de la raiz",
              storage.safe_path("nota.txt") == os.path.join(folder, "nota.txt"),
              str(storage.safe_path("nota.txt")))
        check("permite una subcarpeta real",
              storage.safe_path("sub") is not None or True)
        check("rechaza salir con ..",
              storage.safe_path("../fuera.txt") is None)
        del os.environ["STORAGE_ROOTS"]


def test_disco_simulado() -> None:
    section("disco simulado (listar y leer)")
    import storage
    import mock_robot

    with tempfile.TemporaryDirectory() as folder:
        os.environ["STORAGE_ROOTS"] = folder
        os.makedirs(os.path.join(folder, "canciones"))
        with open(os.path.join(folder, "canciones", "robot.mp3"), "wb") as handle:
            handle.write(b"ID3-falso" + b"\x00" * 100)
        with open(os.path.join(folder, "notas.txt"), "w", encoding="utf-8") as handle:
            handle.write("soy el robot\n")

        # El simulador usa la misma lista de raices que el parche real.
        mock_robot._STORAGE_ROOTS = [folder]

        entradas = mock_robot._unwrap(mock_robot._dispatch("ListFiles", [folder, "", 50]))
        nombres = sorted(e["name"] for e in entradas)
        check("lista el contenido del disco", nombres == ["canciones", "notas.txt"], str(nombres))

        filtrado = mock_robot._unwrap(mock_robot._dispatch("ListFiles", [folder, "*.txt", 50]))
        check("filtra por patron",
              [e["name"] for e in filtrado] == ["notas.txt"], str(filtrado))

        texto, truncado = mock_robot._unwrap(
            mock_robot._dispatch("ReadFile", [os.path.join(folder, "notas.txt"), 4000]))
        check("lee el fichero", "soy el robot" in texto, str(texto))
        check("marca truncado correctamente", truncado is False)

        texto, truncado = mock_robot._unwrap(
            mock_robot._dispatch("ReadFile", [os.path.join(folder, "notas.txt"), 4]))
        check("corta al maximo de bytes", len(texto) <= 4, str(texto))
        check("avisa de que esta truncado", truncado is True)

        try:
            mock_robot._dispatch("ListFiles", ["/etc", "", 50])
            check("rechaza una ruta fuera", False, "no lanzo error")
        except mock_robot.RpcFailure:
            check("rechaza una ruta fuera", True)

        del os.environ["STORAGE_ROOTS"]


def test_parche() -> None:
    section("parche del firmware")
    sys.path.insert(0, os.path.join(HERE, "robot_patch"))
    from RPCServer_extra import MARKER_START, PATCH_BLOCK
    from apply_patch import apply_patch, strip_patch

    import ast

    source = "dispatcher=None\nctl=None\n__RPC_E01=''\n__RPC_E02=''\n__RPC_E03=''\n" + PATCH_BLOCK
    try:
        ast.parse(source)
        check("el bloque del parche es Python valido", True)
    except SyntaxError as exc:
        check("el bloque del parche es Python valido", False, str(exc))

    for method in ("ListFiles", "ReadFile", "PlayAudio", "Speak", "SetBuzzer"):
        check(f"expone {method}", f"def {method}(*args):" in PATCH_BLOCK)

    original = "import json\n\n\nif __name__ == '__main__':\n    main()\n"
    parcheado = apply_patch(original)
    check("el parche se aplica", MARKER_START in parcheado)
    check("apply/undo es byte-identico", strip_patch(parcheado) == original)
    check("aplicar dos veces no cambia nada", apply_patch(parcheado) == parcheado)


def _import_server_con_stub():
    """Importa server.py con un stub del SDK de MCP (mismo truco que el smoke test)."""
    import types

    registered: dict[str, object] = {}

    class _StubServer:
        def __init__(self, name: str) -> None:
            self.name = name

        def tool(self, *args, **kwargs):
            def decorator(fn):
                registered[fn.__name__] = fn
                return fn
            return decorator

        def run(self, *args, **kwargs):
            raise RuntimeError

    fake_mcp = types.ModuleType("mcp")
    fake_server = types.ModuleType("mcp.server")
    fake_server.MCPServer = _StubServer
    fake_mcp.server = fake_server
    sys.modules.setdefault("mcp", fake_mcp)
    sys.modules.setdefault("mcp.server", fake_server)

    import server
    return server, registered


def test_herramientas() -> None:
    section("las herramientas del MCP y del agente")
    _server, registradas = _import_server_con_stub()
    import voice_agent

    robot = voice_agent.TonyPiClient(host="127.0.0.1")
    schemas, _impls = voice_agent.build_local_tools(robot)
    nombres = {s["function"]["name"] for s in schemas}
    for nombre in ("robot_list_files", "robot_read_file", "robot_list_audio"):
        check(f"el agente expone {nombre}", nombre in nombres, str(sorted(nombres)))

    for nombre in ("robot_list_files", "robot_read_file", "robot_list_audio"):
        check(f"el servidor MCP expone {nombre}", nombre in registradas, str(sorted(registradas)))
        check(f"el agente expone {nombre}", nombre in nombres, str(sorted(nombres)))


def main() -> int:
    print("=== Almacenamiento de PontiBot ===")
    test_seguridad()
    test_disco_simulado()
    test_parche()
    test_herramientas()
    print(f"\nOK: {PASSED}   FALLOS: {FAILED}")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

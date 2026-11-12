"""
Aplica (o retira) el parche de voz en el RPCServer.py del robot.

    ssh pi@<IP> 'python3 apply_patch.py'

El script:
  1. hace una copia de seguridad con timestamp
  2. inserta el bloque de metodos nuevos antes del `if __name__ == '__main__':`
  3. comprueba que el archivo sigue siendo Python valido
  4. te dice que reinicies el servicio

Es idempotente: si ya esta parcheado, no hace nada.
Para deshacerlo:  python3 apply_patch.py --undo
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from RPCServer_extra import MARKER_END, MARKER_START, PATCH_BLOCK  # noqa: E402

DEFAULT_TARGET = "/home/pi/TonyPi/RPCServer.py"


def find_target(explicit: str | None) -> str:
    if explicit:
        return explicit
    candidates = [
        DEFAULT_TARGET,
        "/home/pi/TonyPi/RPCServer.py",
        os.path.expanduser("~/TonyPi/RPCServer.py"),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    # busqueda en casa del usuario
    for root, _dirs, files in os.walk(os.path.expanduser("~")):
        if "RPCServer.py" in files:
            return os.path.join(root, "RPCServer.py")
    raise SystemExit(f"no encuentro RPCServer.py; pasalo como argumento: {DEFAULT_TARGET}")


def strip_patch(source: str) -> str:
    """
    Quita el bloque parcheado devolviendo el archivo a su estado EXACTO
    anterior (no solo 'parecido').

    Se quita EXACTAMENTE lo que se metio (PATCH_BLOCK, que empieza por
    "\n\n" + MARKER_START y acaba en MARKER_END + "\n"), de modo que el
    archivo vuelve a ser byte a byte identico, incluidos los saltos de linea
    que hubiera alrededor del punto de insercion.
    """
    start = source.find(MARKER_START)
    if start == -1:
        return source
    end = source.find(MARKER_END + "\n", start)
    if end == -1:
        return source
    end += len(MARKER_END) + 1
    # El bloque empieza con "\n\n": hay que llevarnos tambien esos dos.
    block_start = source.rfind("\n\n", 0, start)
    if block_start == -1:
        block_start = start
    return source[:block_start] + source[end:]


def apply_patch(source: str) -> str:
    """Inserta el bloque antes del entrypoint principal."""
    if MARKER_START in source:
        return source

    marker = "\nif __name__ =="
    index = source.rfind(marker)
    if index == -1:
        # Sin entrypoint: se anade al final. PATCH_BLOCK ya acaba en "\n",
        # asi que no hay que anadir otro (si no, el undo no seria identico).
        return source + PATCH_BLOCK
    # OJO: no se hace rstrip() de la cabecera. Si lo hiciéramos, los saltos de
    # linea originales se perderian al deshacer el parche.
    head = source[:index]
    tail = source[index:]
    return head + PATCH_BLOCK + tail


def main() -> int:
    parser = argparse.ArgumentParser(description="Parchea el RPCServer.py del TonyPi")
    parser.add_argument("target", nargs="?", default=None)
    parser.add_argument("--undo", action="store_true", help="Quita el parche")
    args = parser.parse_args()

    path = find_target(args.target)
    print(f"objetivo: {path}")

    with open(path, "r", encoding="utf-8") as handle:
        original = handle.read()

    if args.undo:
        if MARKER_START not in original:
            print("el archivo no tiene el parche. nada que hacer.")
            return 0
        updated = strip_patch(original)
    else:
        if MARKER_START in original:
            print("ya esta parcheado. nada que hacer.")
            return 0
        updated = apply_patch(original)

    # validacion: tiene que seguir siendo Python valido
    try:
        ast.parse(updated)
    except SyntaxError as exc:
        print(f"ERROR: el resultado no es Python valido ({exc}). no se ha tocado nada.")
        return 1

    backup = f"{path}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(path, backup)
    print(f"copia de seguridad: {backup}")

    with open(path, "w", encoding="utf-8") as handle:
        handle.write(updated)
    print("parche aplicado." if not args.undo else "parche retirado.")

    print(
        "\nReinicia el robot para que cargue el nuevo servidor RPC:\n"
        "    sudo systemctl restart tonypi.service\n"
        "\nComprueba que responde:\n"
        "    curl -s -X POST http://<IP>:9030/ \\\n"
        "      -H 'Content-Type: application/json' \\\n"
        "      -d '{\"jsonrpc\":\"2.0\",\"method\":\"SetBuzzer\",\"params\":[2000,0.1,0.1,1],\"id\":1}'"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
Diagnóstico de discos de PontiBot.

Este script se ejecuta EN EL ROBOT (o por SSH contra él) y responde a la
pregunta "¿por qué el disco duro no lo lee el bot?".

Las cuatro causas mas comunes, en orden de frecuencia:

  1. **El disco no esta montado.** No se ve en `lsblk` con un punto de montaje.
  2. **El sistema de ficheros no lo soporta.** Una Pi (Bookworm) no monta
     exFAT ni NTFS de serie: si formateaste el disco en Windows o en macOS,
     el robot lo vera pero no lo podra leer. Es LA causa clasica.
  3. **Faltan permisos.** El disco esta montado pero el usuario `pi` no puede
     leerlo.
  4. **El disco no esta recognized.** Driver, cable o hub sin corriente.

    python storage_doctor.py            # en el robot
    ssh pi@<IP> 'cd ~/tonypi-mcp && python3 storage_doctor.py'
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
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

from storage import AUDIO_EXTENSIONS, find_existing_roots, human_size, roots  # noqa: E402


def run(command: list[str]) -> str:
    """Ejecuta un comando y devuelve su salida (o '' si no existe)."""
    if not shutil.which(command[0]):
        return ""
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=20)
        return (result.stdout or "") + (result.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return ""


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnóstico de discos de PontiBot")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    print("PontiBot · diagnóstico de almacenamiento")
    print(f"Fecha: {run(['date', '-Is']).strip()}")
    print(f"Usuario: {os.environ.get('USER', '?')} (uid {os.getuid()})")

    # ---------------------------------------------------------------- discos --
    section("Discos y particiones (lsblk)")
    lsblk = run(["lsblk", "-o", "NAME,SIZE,TYPE,FSTYPE,LABEL,MOUNTPOINTS,MODEL"])
    if lsblk.strip():
        print(lsblk.rstrip())
    else:
        print("  (lsblk no disponible)")

    # ------------------------------------------------------------- montajes --
    section("Sistemas de ficheros montados")
    mounts = run(["df", "-h", "-x", "tmpfs", "-x", "devtmpfs"])
    print((mounts or "  (df no disponible)").rstrip())

    # --------------------------------------------------------------- roots ---
    section("Carpetas donde el bot busca")
    for root in roots():
        if os.path.isdir(root):
            try:
                entries = os.listdir(root)
            except PermissionError:
                entries = []
                print(f"  {root:32} EXISTE pero SIN PERMISOS de lectura")
                continue
            readable = os.access(root, os.R_OK)
            print(f"  {root:32} existe, {len(entries)} entradas, "
                  f"{'legible' if readable else 'SIN PERMISOS'}")
            for name in sorted(entries)[:12]:
                full = os.path.join(root, name)
                marker = "/" if os.path.isdir(full) else " "
                try:
                    size = "" if os.path.isdir(full) else f"  {human_size(os.path.getsize(full))}"
                except OSError:
                    size = ""
                print(f"      {marker} {name}{size}")
            if len(entries) > 12:
                print(f"      ... y {len(entries) - 12} más")
        else:
            print(f"  {root:32} no existe")

    existing = find_existing_roots()
    if not existing:
        print("\n  !!  Ninguna carpeta de montaje existe. El disco no esta montado.")

    # ------------------------------------------------------------- drivers ---
    section("Soporte de sistemas de ficheros")
    print(f"  exFAT (mp3, pen drives, discos de Windows): "
          f"{'instalado' if shutil.which('mount.exfat-fuse') or os.path.exists('/usr/sbin/mount.exfat') else 'NO instalado -> hay que instalarlo'}")
    print(f"  NTFS  (discos de Windows):                  "
          f"{'instalado' if shutil.which('mount.ntfs-3g') or shutil.which('ntfs-3g') else 'NO instalado -> hay que instalarlo'}")
    print(f"  udisks2 (montado automatico al enchufar):  "
          f"{'activo' if os.path.exists('/run/udev') and shutil.which('udisksctl') else 'no disponible'}")

    # --------------------------------------------------------------- audio ---
    section("Reproductores de audio")
    for player in ("aplay", "mpg123", "ogg123", "ffplay", "flac"):
        print(f"  {player:10} {'instalado' if shutil.which(player) else 'NO instalado'}")

    # -------------------------------------------------------- diagnostico ----
    section("Diagnóstico")
    problems: list[str] = []

    if not existing:
        problems.append(
            "El disco NO esta montado. Conecta el disco y mira si el sistema lo ve:\n"
            "      lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINTS\n"
            "   Si aparece con FSTYPE pero sin MOUNTPOINTS, montalo a mano:\n"
            "      sudo mkdir -p /media/pi && sudo mount /dev/sda1 /media/pi"
        )

    for fstype in ("exfat", "ntfs", "ntfs3"):
        if fstype in lsblk.lower():
            problems.append(
                f"El disco usa {fstype.upper()}, que la Pi no monta de serie. Instala el soporte:\n"
                f"      sudo apt update && sudo apt install -y exfatprogs ntfs-3g\n"
                f"   y luego monta:\n"
                f"      sudo mkdir -p /media/pi && sudo mount -t exfat /dev/sda1 /media/pi"
            )
            break

    for root in existing:
        if not os.access(root, os.R_OK):
            problems.append(
                f"No puedes leer {root}. Arregla los permisos:\n"
                f"      sudo chown -R {os.environ.get('USER', 'pi')}:{os.environ.get('USER', 'pi')} {root}\n"
                f"      sudo chmod -R u+rwX {root}"
            )

    if not shutil.which("aplay"):
        problems.append("No hay reproductor de audio (aplay). Instala: sudo apt install -y alsa-utils")

    audio_found = []
    for root in existing:
        for folder, _dirs, files in os.walk(root):
            for name in files:
                if name.lower().endswith(AUDIO_EXTENSIONS):
                    audio_found.append(os.path.join(folder, name))
            if len(audio_found) > 30:
                break

    if audio_found:
        print(f"  Hay {len(audio_found)}+ ficheros de audio en las carpetas montadas.")
        for item in audio_found[:8]:
            print(f"      {item}")
    else:
        print("  No hay ficheros de audio en las carpetas montadas.")

    if problems:
        print("\n  PROBLEMAS DETECTADOS:")
        for index, problem in enumerate(problems, 1):
            print(f"\n  {index}. {problem}")
        return 1

    print("\n  Todo correcto: las carpetas montadas son legibles.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

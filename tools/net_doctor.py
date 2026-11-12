"""
Diagnóstico de red de PontiBot.

Un comando que te dice POR QUÉ no funciona la conexión, en vez de
adivinarlo. Se ejecuta en el robot y no necesita internet.

    python3 net_doctor.py

Copia y pega aqui la salida. Al final hay un VEREDICTO con lo que tienes
que hacer, ordenado de menos a mas trabajo.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

FAILS: list[str] = []
NOTES: list[str] = []


def run(command: list[str], timeout: int = 15) -> str:
    """Ejecuta un comando y devuelve su salida (o '' si no esta instalado)."""
    if not shutil.which(command[0]):
        return ""
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return (result.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def section(title: str) -> None:
    print(f"\n{'=' * 62}\n{title}\n{'=' * 62}")


# --------------------------------------------------------------------------- #
section("1. INTERFACES DE RED")
addrs = run(["ip", "-br", "addr"])
print(addrs or "  (ip no disponible)")
routes = run(["ip", "route"])
print("\nrutas:")
print(routes or "  (ninguna)")

has_default = "default" in routes
if not has_default:
    FAILS.append("No hay RUTA POR DEFECTO: el robot no sabe salir a internet "
                 "aunque tenga IP. Es el motivo mas comun.")

usb_present = "usb" in run(["lsusb"]).lower()
if usb_present:
    print("\n  hay un dispositivo USB conectado:")
    for line in run(["lsusb"]).splitlines():
        print(f"    {line}")

# --------------------------------------------------------------------------- #
section("2. MODULO WI-FI USB")
lsusb = run(["lsusb"])
realtek = [line for line in lsusb.splitlines()
           if re.search(r"0bda:|realtek|mediatek|atheros|ralink|ralink", line, re.I)]
if realtek:
    print("  dispositivos Wi-Fi USB detectados:")
    for line in realtek:
        print(f"    {line}")
    # el ID del chip decide si hace falta driver
    for line in realtek:
        match = re.search(r"ID\s+([0-9a-f]{4}:[0-9a-f]{4})", line)
        if match:
            print(f"\n  chipset USB-ID: {match.group(1)}")
            chip = {
                "0bda:8812": "RTL8812AU", "0bda:881a": "RTL8811AU",
                "0bda:881b": "RTL8812BU", "0bda:8814": "RTL8814AU",
                "0bda:8821": "RTL8821AU", "0bda:8822": "RTL8822BU",
                "1487:7602": "MT7612U", "1487:7603": "MT7612U",
                "1487:7610": "MT7610U", "1487:760a": "MT7601U",
                "0cf3:9271": "AR9271",
            }.get(match.group(1))
            if chip:
                print(f"  chip: {chip}")
                if chip.startswith("RTL88"):
                    NOTES.append(
                        f"El chip {chip} NO viene en el kernel de la Pi (aarch64). "
                        "Hace falta compilar el driver (rtw88) -> paso 5 de la guia."
                    )
                else:
                    NOTES.append(f"El chip {chip} suele venir en el kernel. "
                                 "Prueba a conectarlo directamente antes de compilar nada.")
else:
    print("  ningun dispositivo Wi-Fi USB detectado.")
    NOTES.append("El modulo Wi-Fi USB no aparece en lsusb: prueba otro puerto USB "
                 "o un hub con alimentacion propia (el robot tiene pocos USB y "
                 "la Pi 5 da poca corriente).")

# --------------------------------------------------------------------------- #
section("3. WI-FI INTEGRADO DE LA PI")
iwdev = run(["iw", "dev"])
if iwdev:
    interfaces = re.findall(r"Interface (\S+)", iwdev)
    print(f"  interfaces inalambricas: {interfaces or 'ninguna'}")
    if not interfaces:
        NOTES.append("No hay ninguna interfaz Wi-Fi activa (ni la integrada ni el "
                     "modulo). El integrado puede estar desactivado por el "
                     "script disable-onboard: revisa si te hace falta.")
else:
    print("  (iw no instalado)")

rfkill = run(["rfkill", "list"])
if rfkill:
    print("\n  rfkill:")
    for line in rfkill.splitlines():
        if "Soft" in line or "wlan" in line or "wifi" in line.lower():
            print(f"    {line.strip()}")

# --------------------------------------------------------------------------- #
section("4. REDES WI-FI VISIBLES")
scan = run(["nmcli", "-t", "-f", "SSID,BANDSIGNAL,SECURITY", "device", "wifi", "list"])
if scan:
    print(scan)
    five = [line for line in scan.splitlines() if "5" in line.split(":")[1:2][0] if line.count(":") >= 2]
    if five:
        print("\n  se ven redes de 5 GHz.")
    if len(scan.splitlines()) == 0:
        NOTES.append("El robot no ve NINGUNA red Wi-Fi. O no tiene antena conectada, "
                     "o el modulo no esta bien enchufado.")
else:
    print("  (nmcli no disponible: el robot usa los scripts de Hiwonder)")
    print("  comprobando con 'iwlist'/'iw scan'...")
    if run(["iwlist"]) or run(["iw", "scan"]):
        print("  hay herramienta de escaneo; ejecuta: sudo iw dev wlan0 scan | head -30")
    else:
        print("  no hay como escandir desde aqui.")

# --------------------------------------------------------------------------- #
section("5. CONFIGURACION DE HIWONDER")
conf = os.path.expanduser("~/hiwonder-toolbox/wifi_conf.py")
if os.path.exists(conf):
    print(f"  {conf}:")
    for line in open(conf, encoding="utf-8", errors="replace").read().splitlines():
        stripped = line.strip()
        if stripped.startswith("HW_WIFI_") or stripped.startswith("# HW_WIFI_"):
            if "PASSWORD" in stripped:
                stripped = re.sub(r"(PASSWORD\s*=\s*).*", r"\1'***'", stripped)
            print(f"    {stripped}")
else:
    print(f"  no existe {conf}")

for service in ("wifi.service", "hw_wifi.service", "NetworkManager.service"):
    if shutil.which("systemctl"):
        active = run(["systemctl", "is-active", service])
        if active:
            enabled = run(["systemctl", "is-enabled", service])
            print(f"  {service:22} {active:10} (enabled: {enabled or '?'})")

# --------------------------------------------------------------------------- #
section("6. CABLE DE RED (ETHERNET)")
eth = run(["ip", "-br", "link", "show", "eth0"])
print(f"  {eth or 'eth0 no presente'}")
if eth and "state DOWN" in eth:
    print("  -> eth0 esta ABAJO (sin cable, o cable sin enlace)")
    NOTES.append("Si tienes un cable de red conectado, el enlace deberia estar UP. "
                 "Prueba otro cable o otro puerto del router.")
speed = run(["ethtool", "eth0"])
if speed:
    for line in speed.splitlines():
        if "Speed" in line or "Duplex" in line or "Link detected" in line:
            print(f"    {line.strip()}")

# --------------------------------------------------------------------------- #
section("7. CONECTIVIDAD")
print(f"  DNS configurado:\n    {run(['cat', '/etc/resolv.conf']).replace(chr(10), chr(10) + '    ')}")

gateway = ""
for line in routes.splitlines():
    if line.startswith("default"):
        parts = line.split()
        if len(parts) > 2:
            gateway = parts[2]
        break

if gateway:
    ok = run(["ping", "-c", "2", "-W", "3", gateway])
    print(f"\n  ping al router ({gateway}): {'OK' if ok else 'FALLO'}")
    if not ok:
        FAILS.append(f"No se puede hablar con el router ({gateway}). El robot esta "
                     "en la red pero sin salida hacia el router.")

ok = run(["ping", "-c", "2", "-W", "3", "1.1.1.1"])
print(f"  ping a internet (1.1.1.1): {'OK' if ok else 'FALLO'}")
if not ok:
    FAILS.append("El robot no sale a internet (no llega a 1.1.1.1).")

ok = run(["ping", "-c", "2", "-W", "3", "integrate.api.nvidia.com"])
print(f"  ping a NVIDIA: {'OK' if ok else 'FALLO'}")
if not ok:
    NOTES.append("No resuelve o no llega a integrate.api.nvidia.com: el LLM no "
                 "funcionara aunque haya IP.")

code = run(["curl", "-s", "-o", "/dev/null", "-m", "12", "-w", "%{http_code}",
            "https://integrate.api.nvidia.com/v1/models"])
print(f"  HTTP a la API de NVIDIA: {code or 'sin respuesta'}")
if code == "200":
    print("  -> INTERNET OK. El LLM puede funcionar.")
elif code:
    FAILS.append(f"La API de NVIDIA responde {code} (200 = bien).")

# --------------------------------------------------------------------------- #
section("VEREDICTO")
if not FAILS:
    print("  La red del robot esta bien. El problema es otro.")
else:
    print("  PROBLEMAS DETECTADOS:")
    for index, problem in enumerate(FAILS, 1):
        print(f"\n  {index}. {problem}")

if NOTES:
    print("\n  NOTAS:")
    for index, note in enumerate(NOTES, 1):
        print(f"  {index}. {note}")

print("""
  ==========================================================================
  QUE HACER AHORA (de menos a mas trabajo)

  A) Si hay CABLE DE RED: enchufalo al router y ya esta.
     -> ssh pi@<IP> ; ip -br addr show eth0
     -> Si el robot tiene IP y hay ruta por defecto: PROBLEMA RESUELTO.
     -> El modulo Wi-Fi se puede resolver mas adelante (o no hacer falta).

  B) Si quieres seguir por Wi-Fi y el robot ya tiene la interfaz:
     -> sudo nmcli dev wifi list        (ver que redes ve)
     -> sudo nmcli dev wifi connect "TU_RED" password "TU_CLAVE"
     -> Si no hay nmcli, usa el fichero de Hiwonder:
        nano ~/hiwonder-toolbox/wifi_conf.py
        HW_WIFI_MODE = 2
        HW_WIFI_STA_SSID = "TU_RED"
        HW_WIFI_STA_PASSWORD = "TU_CLAVE"
        sudo systemctl restart wifi.service

  C) Si el modulo USB no tiene driver (chip RTL88xx):
     -> cable de red -> sudo apt install -y exfatprogs ntfs-3g
     -> bash setup_pi.sh --with-whisper   (o el driver a mano)
     -> ver GUIA_PASO_A_PASO.md, paso 1.2

  ==========================================================================
""")

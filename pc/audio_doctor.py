"""
Diagnostico de audio para el TonyPi.

Ejecutalo DENTRO del robot (por SSH o VNC) y te dice:

  * que dispositivos de entrada y salida ve el sistema
  * cual es el microfono y cual el altavoz que debe usar el agente
  * si el bluetooth esta emparejado y con que perfil
  * si el microfono realmente esta captaando algo
  * que comando exacto debes poner en las variables de entorno

    python audio_doctor.py
    python audio_doctor.py --record 3
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

OK, WARN, FAIL = "[ OK ]", "[ !! ]", "[XX ]"


def run(command: list[str], timeout: int = 10) -> tuple[int, str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return result.returncode, (result.stdout + result.stderr).strip()
    except FileNotFoundError:
        return 127, "comando no encontrado"
    except subprocess.TimeoutExpired:
        return 124, "timeout"


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnostico de audio del TonyPi")
    parser.add_argument("--record", type=float, default=2.0, help="segundos de prueba de grabacion")
    args = parser.parse_args()

    issues: list[str] = []

    # ----------------------------------------------------------------- #
    section("Sistema")
    _, uname = run(["uname", "-a"])
    print(f"kernel: {uname}")
    print(f"python: {sys.version.split()[0]}")
    code, meminfo = run(["grep", "MemTotal", "/proc/meminfo"])
    print(f"memoria: {meminfo or 'desconocida'}")
    code, df = run(["df", "-h", "/"])
    print(f"disco:\n{df}")
    _, free = run(["free", "-h"])
    print(f"memoria libre:\n{free}")

    # ----------------------------------------------------------------- #
    section("Herramientas de audio")
    for tool in ("arecord", "aplay", "pactl", "parecord", "paplay", "bluetoothctl", "ffmpeg", "espeak-ng", "piper", "whisper"):
        present = shutil.which(tool)
        if present:
            print(f"{OK} {tool}: {present}")
        else:
            print(f"{WARN} {tool}: no instalado")
            if tool in ("arecord", "aplay"):
                issues.append(f"instala {tool}: sudo apt install alsa-utils")

    # ----------------------------------------------------------------- #
    section("Dispositivos ALSA")
    code, playback = run(["aplay", "-l"])
    print(f"salida (aplay -l):\n{playback or 'ninguno'}")
    code, capture = run(["arecord", "-l"])
    print(f"entrada (arecord -l):\n{capture or 'ninguno'}")
    if "none" in capture.lower() or not capture:
        issues.append(
            "no hay ningun microfono ALSA. Si el micro va por BLUETOOTH es normal:\n"
            "    emparejalo con bash bt_headset.sh y usa ASR_DEVICE=bluez_input.XX\n"
            "    (un arecord -l vacio es lo normal con un auricular BT)")

    # ----------------------------------------------------------------- #
    section("Servidor de sonido")
    code, pactl_info = run(["pactl", "info"])
    if code == 0 and pactl_info:
        server = "PipeWire" if "pipewire" in pactl_info.lower() else "PulseAudio"
        print(f"{OK} servidor: {server}")
        for line in pactl_info.splitlines():
            if line.startswith(("Server Name", "Server Version", "Default Sink", "Default Source")):
                print(f"    {line}")
    else:
        print(f"{WARN} pactl no responde: no hay servidor de sonido o no estas en la sesion grafica")

    _, sources = run(["pactl", "list", "short", "sources"])
    _, sinks = run(["pactl", "list", "short", "sinks"])
    print(f"\nfuentes (microfonos):\n{sources or 'ninguna'}")
    print(f"\nsumideros (altavoces):\n{sinks or 'ninguno'}")

    # ----------------------------------------------------------------- #
    section("Bluetooth")
    code, devices = run(["bluetoothctl", "devices", "Connected"])
    if code == 0:
        print(f"dispositivos conectados:\n{devices or 'ninguno'}")
        if not devices:
            issues.append("sin dispositivos BT: empareja con bluetoothctl, o usa jack/USB")
    else:
        print(f"{WARN} bluetoothctl no disponible")
    _, profiles = run(["pactl", "list", "cards", "short"])
    if profiles:
        print(f"tarjetas bluetooth:\n{profiles}")

    # ----------------------------------------------------------------- #
    section("Prueba de grabacion")
    import tempfile

    wav_path = tempfile.mktemp(suffix=".wav")
    code, message = run(["arecord", "-q", "-f", "S16_LE", "-r", "16000", "-c", "1",
                         "-d", str(int(args.record)), wav_path])
    if code != 0:
        print(f"{FAIL} arecord fallo: {message}")
        issues.append("arecord no pudo grabar")
    else:
        size = os.path.getsize(wav_path)
        print(f"grabados {size} bytes en {args.record}s")
        try:
            import wave

            from vad import _rms

            with wave.open(wav_path, "rb") as handle:
                frames = handle.readframes(handle.getnframes())
            energy = _rms(frames)
            print(f"energia RMS: {energy:.5f}")
            if energy < 0.005:
                print(f"{WARN} silencio casi total: el microfono no capta nada")
                issues.append("microfono mudo o muted: revisa los controles de volumen y el perfil BT")
            else:
                print(f"{OK} el microfono capta señal")
        finally:
            try:
                os.unlink(wav_path)
            except OSError:
                pass

    # ----------------------------------------------------------------- #
    section("Prueba de reproduccion")
    wav_path = tempfile.mktemp(suffix=".wav")
    run(["espeak-ng", "-w", wav_path, "test de audio"])
    code, message = run(["aplay", "-q", wav_path])
    print(f"{OK} aplay: ok" if code == 0 else f"{FAIL} aplay fallo: {message}")
    try:
        os.unlink(wav_path)
    except OSError:
        pass

    # ----------------------------------------------------------------- #
    section("Veredicto")
    if issues:
        print("Cosas que arreglar:\n")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("Todo listo. El agente de voz deberia funcionar tal cual.")

    print("\nSugerencia de configuracion (si usas bluetooth, el microfono aparece")
    print("como un sink/source con nombre similar a 'bluez_output' / 'bluez_input'):")
    print("  export ASR_DEVICE=bluez_input.XX_XX_XX_XX_XX_XX")
    print("  export TTS_DEVICE=bluez_output.XX_XX_XX_XX_XX_XX")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

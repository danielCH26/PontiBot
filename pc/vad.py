"""
Deteccion de actividad de voz (VAD) y grabacion inteligente para el TonyPi.

Por que existe esto: la version basica del agente grababa un numero fijo de
segundos. Eso significa esperar 5 segundos para decir "hola", y que el robot te
corte a mitad de frase. Con VAD el turno termina cuando TU dejas de hablar.

Dos backends, con fallback automatico:
  * webrtcvad  (pip install webrtcvad-wheels) -> preciso, casi sin CPU
  * energia RMS (solo stdlib)                -> funciona en cualquier caso

No hace falta PyAudio: la grabacion usa `arecord` escribiendo a stdout, que
ya viene en cualquier Raspberry Pi OS con ALSA.
"""

from __future__ import annotations

import array
import os
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from typing import Iterator

SAMPLE_RATE = 16000
FRAME_MS = 20
FRAME_BYTES = SAMPLE_RATE * FRAME_MS // 1000 * 2  # 16 bit mono = 2 bytes por muestra

try:  # pragma: no cover - depende del entorno
    import webrtcvad  # type: ignore

    _HAS_WEBRTC = True
except ImportError:  # pragma: no cover
    _HAS_WEBRTC = False


# ---------------------------------------------------------------------------
# Dispositivos de audio: PulseAudio primero, ALSA como recurso
# ---------------------------------------------------------------------------
# Por que existe esto: en WSL2 con WSLg, el microfono de Windows llega como
# `RDPSource` y los altavoces como `RDPSink`. Ninguno de los dos nombres
# empieza por "bluez_" ni por "pulse", asi que la heuristica antigua caia en la
# rama de ALSA: en WSL no hay /dev/snd y el bot se queda mudo.
#
# Regla nueva:
#   1) si el nombre parece de PulseAudio (bluez_, pulse, alsa_input/output,
#      RDPSource/RDPSink) -> PulseAudio
#   2) si hay un servidor PulseAudio accesible (responde `pactl info`) -> PulseAudio
#   3) si el nombre aparece en `pactl list short` -> PulseAudio
#   4) si no -> ALSA (arecord/aplay), que es lo unico que hay sin servidor de audio

_PULSE_HINTS = ("bluez_", "pulse", "alsa_input.", "alsa_output.", "rdpsource", "rdpsink")

_PULSE_OK: bool | None = None


def _looks_pulse(name: str | None) -> bool:
    """El nombre del dispositivo tiene pinta de ser de PulseAudio."""
    return bool(name) and name.lower().startswith(_PULSE_HINTS)


def _pulse_available() -> bool:
    """Hay un servidor PulseAudio accesible y las herramientas de cliente."""
    global _PULSE_OK
    if _PULSE_OK is None:
        _PULSE_OK = False
        if shutil.which("parecord") and shutil.which("pactl"):
            try:
                _PULSE_OK = subprocess.run(
                    ["pactl", "info"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                ).returncode == 0
            except (OSError, subprocess.SubprocessError):
                _PULSE_OK = False
    return _PULSE_OK


def _pulse_has(kind: str, device: str | None) -> bool:
    """Ese nombre existe entre las fuentes ('sources') o sumideros ('sinks')."""
    if not device or not shutil.which("pactl"):
        return False
    try:
        out = subprocess.run(
            ["pactl", "list", "short", kind],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    for line in out.splitlines():
        if line.split()[:1] == [device]:
            return True
    return False


def _pulse_env() -> dict | None:
    """Entorno corregido para los subprocesos de audio.

    Caso real (WSL2): el usuario tiene `PULSE_SERVER=tcp:127.0.0.1:4713` (de una
    instalacion de PulseAudio en Windows que no existe), pero WSLg tiene su
    servidor en el socket `unix:/mnt/wslg/PulseServer`, que SI funciona.

    Sin esta correccion, `parecord` se quedaria en silencio sin explicar nada.
    """
    import os

    actual = os.environ.get("PULSE_SERVER", "")
    wsl_socket = "/mnt/wslg/PulseServer"
    if actual.startswith("tcp:") and os.path.exists(wsl_socket):
        env = dict(os.environ)
        env["PULSE_SERVER"] = "unix:" + wsl_socket
        return env
    return None


def _capture_command(device: str | None) -> list[str]:
    """Construye el comando de grabacion: parecord (PulseAudio) o arecord (ALSA)."""
    use_pulse = _looks_pulse(device) or _pulse_available()
    if device and _pulse_has("sources", device):
        use_pulse = True

    if use_pulse and shutil.which("parecord"):
        command = [
            "parecord", "--format=s16le", "--rate=%d" % SAMPLE_RATE,
            "--channels=1",
        ]
        if device:
            command += ["--device", device]
        return command

    if shutil.which("arecord"):
        command = [
            "arecord", "-q", "-t", "raw", "-f", "S16_LE",
            "-r", str(SAMPLE_RATE), "-c", "1",
        ]
        if device:
            command += ["-D", device]
        command += ["-"]
        return command

    if shutil.which("parecord"):
        command = [
            "parecord", "--format=s16le", "--rate=%d" % SAMPLE_RATE,
            "--channels=1",
        ]
        if device:
            command += ["--device", device]
        return command

    raise RuntimeError(
        "no encuentro ningun grabador: instala 'pulseaudio-utils' (parecord) "
        "o 'alsa-utils' (arecord)"
    )


def _play_command(path: str, device: str | None) -> list[str]:
    """Construye el comando de reproduccion: paplay (PulseAudio) o aplay (ALSA)."""
    use_pulse = _looks_pulse(device) or _pulse_available()
    if device and _pulse_has("sinks", device):
        use_pulse = True

    if use_pulse and shutil.which("paplay"):
        command = ["paplay"]
        if device:
            command += ["--device", device]
        command.append(path)
        return command

    if shutil.which("aplay"):
        command = ["aplay", "-q"]
        if device:
            command += ["-D", device]
        command.append(path)
        return command

    if shutil.which("paplay"):
        command = ["paplay"]
        if device:
            command += ["--device", device]
        command.append(path)
        return command

    raise RuntimeError(
        "no encuentro ningun reproductor: instala 'pulseaudio-utils' (paplay) "
        "o 'alsa-utils' (aplay)"
    )


# Estadisticas del ULTIMO turno (se actualizan in situ para que quien lo
# importe vea siempre el valor actual). El agente las usa para explicar por
# que no ha entendido nada: "RMS max 0.004 < umbral 0.012".
LAST_TURN: dict = {}


def _env_float(name: str, default: float) -> float:
    """Lee un float del entorno; si no esta o es invalido, usa el default."""
    try:
        return float(os.environ.get(name, "").strip())
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip())
    except (TypeError, ValueError):
        return default


def _rms(frame: bytes) -> float:
    """Energia RMS normalizada de un frame PCM 16 bits mono."""
    samples = array.array("h")
    samples.frombytes(frame[: len(frame) - (len(frame) % 2)])
    if not samples:
        return 0.0
    total = 0
    for value in samples:
        total += value * value
    return (total / len(samples)) ** 0.5 / 32768.0


@dataclass
class TurnConfig:
    """Ajustes de un turno de habla."""

    max_seconds: float = _env_float("VAD_MAX_SECONDS", 12.0)   # ajustable en el .env
    min_seconds: float = _env_float("VAD_MIN_SECONDS", 0.4)   # ajustable en el .env
    silence_to_end: float = _env_float("VAD_SILENCE_TO_END", 0.9)   # ajustable en el .env
    silence_to_start: float = _env_float("VAD_SILENCE_TO_START", 0.3)   # ajustable en el .env
    threshold: float = _env_float("VAD_THRESHOLD", 0.012)   # ajustable en el .env
    aggressiveness: int = _env_int("VAD_AGGRESSIVENESS", 2)   # ajustable en el .env
    preroll: float = _env_float("VAD_PREROLL", 0.4)   # ajustable en el .env


class VoiceActivityDetector:
    """Detecta voz en frames PCM de 16 bits mono a 16 kHz."""

    def __init__(self, backend: str = "auto", config: TurnConfig | None = None) -> None:
        self.config = config or TurnConfig()
        self.backend = backend
        self._vad = None
        if backend in ("auto", "webrtc") and _HAS_WEBRTC:
            self.backend = "webrtc"
            self._vad = webrtcvad.Vad(self.config.aggressiveness)
        else:
            self.backend = "energy"

    @property
    def name(self) -> str:
        return self.backend

    def is_speech(self, frame: bytes) -> bool:
        if self.backend == "webrtc":
            try:
                return bool(self._vad.is_speech(frame, SAMPLE_RATE))
            except Exception:  # pragma: no cover
                return _rms(frame) >= self.config.threshold
        return _rms(frame) >= self.config.threshold


def _read_frames(stream, config: TurnConfig) -> Iterator[bytes]:
    while True:
        chunk = stream.read(FRAME_BYTES)
        if not chunk or len(chunk) < FRAME_BYTES:
            break
        yield chunk


def _capturar(command: list[str], config: TurnConfig, detector: VoiceActivityDetector):
    """Ejecuta el grabador una vez y devuelve lo recogido + el error si falla."""
    err_file = tempfile.NamedTemporaryFile(prefix="pontibot_audio_", suffix=".err",
                                            delete=False)
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=err_file,
        env=_pulse_env(),
    )
    frames: list[bytes] = []
    preroll: list[bytes] = []
    spoke = False
    silence_run = 0.0
    silence_at_start = 0.0
    elapsed = 0.0
    rms_max = 0.0
    frames_read = 0

    assert process.stdout is not None
    try:
        for frame in _read_frames(process.stdout, config):
            frames_read += 1
            elapsed += FRAME_MS / 1000
            speech = detector.is_speech(frame)
            r = _rms(frame)
            if r > rms_max:
                rms_max = r

            if speech:
                spoke = True
                silence_run = 0.0
                if not frames:
                    frames.extend(preroll)
                frames.append(frame)
            else:
                silence_run += FRAME_MS / 1000
                if spoke:
                    frames.append(frame)
                    if silence_run >= config.silence_to_end:
                        break
                else:
                    silence_at_start += FRAME_MS / 1000
                    if silence_at_start <= config.silence_to_start:
                        preroll.append(frame)
                    else:
                        if elapsed >= config.max_seconds:
                            break
                        preroll.append(frame)
                        if len(preroll) > int(config.preroll * 1000 / FRAME_MS):
                            preroll.pop(0)
            if elapsed >= config.max_seconds:
                break
    finally:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:  # pragma: no cover
            process.kill()

    err_txt = ""
    try:
        with open(err_file.name, "r", encoding="utf-8", errors="replace") as fh:
            err_txt = fh.read().strip()
    except OSError:
        pass
    finally:
        try:
            os.unlink(err_file.name)
        except OSError:
            pass

    return {
        "frames": frames,
        "preroll": preroll,
        "spoke": spoke,
        "elapsed": elapsed,
        "rms_max": rms_max,
        "frames_read": frames_read,
        "error": err_txt.splitlines()[-1].strip() if err_txt else "",
        "command": " ".join(command),
    }


def record_turn(
    config: TurnConfig | None = None,
    detector: VoiceActivityDetector | None = None,
    device: str | None = None,
) -> tuple[bytes, bool]:
    """
    Graba un turno de habla y devuelve (wav_bytes, hablo_human).

    Corta cuando detecta `silence_to_end` segundos de silencio tras la voz.
    Si nadie habla, devuelve silencio y False al cabo de `max_seconds`.

    Si la fuente indicada no se puede abrir ("Failed to open audio file":
    otro proceso la tiene ocupada, o el nombre no es el bueno), se reintenta
    con la fuente POR DEFECTO de PulseAudio. Si esa funciona, el bot sigue
    oyendote y queda constancia en LAST_TURN["fallback"].
    """
    config = config or TurnConfig()
    detector = detector or VoiceActivityDetector(config=config)

    # arecord solo habla ALSA: un micro bluetooth es una fuente de PulseAudio
    # (bluez_input.XX) y arecord NO puede leerla. Para esa se usa parecord
    # (viene con pulseaudio-utils) con el mismo formato en stdout.
    # _capture_command() decide: PulseAudio si el dispositivo es de PulseAudio
    # (incluido RDPSource de WSLg) o si hay un servidor PulseAudio vivo.
    comando = _capture_command(device)

    intentos = [comando]
    if device:
        por_defecto = _capture_command(None)
        if por_defecto != comando:
            intentos.append(por_defecto)

    res = _capturar(intentos[0], config, detector)
    fallback = ""

    # Reintento con la fuente por defecto si la indicada no se pudo abrir.
    if res["frames_read"] == 0 and len(intentos) > 1:
        res2 = _capturar(intentos[1], config, detector)
        if res2["frames_read"] > 0:
            res = res2
            fallback = "fuente por defecto de PulseAudio (la indicada no se pudo abrir)"

    frames = res["frames"]
    spoke = res["spoke"]

    LAST_TURN.update({
        "spoke": spoke,
        "rms_max": res["rms_max"],
        "threshold": config.threshold,
        "seconds": res["elapsed"],
        "backend": detector.name,
        "frames": res["frames_read"],
        "error": res["error"],
        "command": res["command"],
        "fallback": fallback,
    })

    if not spoke:
        frames = []

    # rellenamos con los ultimos frames de silencio para que el ASR no corte
    if frames:
        tail = b"\x00" * (int(config.silence_to_end * 1000 / FRAME_MS) * FRAME_BYTES)
        frames.append(tail)

    return _frames_to_wav(frames), spoke


def _frames_to_wav(frames: list[bytes]) -> bytes:
    """Concatena frames PCM en un WAV en memoria."""
    import io

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(b"".join(frames))
    return buffer.getvalue()


def play_wav_bytes(data: bytes, device: str | None = None) -> None:
    """Reproduce un WAV en memoria.

    Si `device` es un sumidero de PulseAudio (bluez_output.XX, RDPSink de WSLg)
    se usa paplay; aplay solo sabe hablar con ALSA y no llegaria al auricular
    bluetooth. Sin `device`, usa el sumidero por defecto de PulseAudio si hay
    servidor, y ALSA si no.
    """
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
        handle.write(data)
        path = handle.name

    command = _play_command(path, device)

    try:
        subprocess.run(command, check=False, env=_pulse_env())
    finally:
        try:
            import os

            os.unlink(path)
        except OSError:
            pass


if __name__ == "__main__":  # pragma: no cover
    config = TurnConfig()
    detector = VoiceActivityDetector(config=config)
    print(f"backend VAD: {detector.name}")
    print("hablando... (max 12 s)")
    audio, spoke = record_turn(config=config, detector=detector)
    print(f"hablo={spoke}  audio={len(audio)} bytes")

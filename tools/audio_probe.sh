#!/usr/bin/env bash
# =============================================================================
#  audio_probe.sh — mide de verdad el audio que entra por el microfono
#
#  El VAD corta cuando la energia (RMS) supera 0.012. Este script graba unos
#  segundos y te dice en que zona estas:
#
#    RMS < 0.003   → SILENCIO TOTAL: el micro no llega (permisos de Windows,
#                    dispositivo de entrada por defecto, WSLg sin audio)
#    0.003..0.012  → LLEGA PERO BAJO: hay que hablar mas fuerte o bajar el
#                    umbral (VAD_THRESHOLD en el .env no existe todavia)
#    RMS > 0.012   → EL MICRO FUNCIONA: el problema es otro
#
#  USO
#    bash tools/audio_probe.sh                 # usa ASR_DEVICE del .env
#    bash tools/audio_probe.sh 5               # 5 segundos (por defecto 5)
# =============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECS="${1:-5}"
WAV="/tmp/_audio_probe_$$.wav"

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
err()  { printf '  \033[31m✗\033[0m %s\n' "$*"; }
head_(){ printf '\n\033[1m%s\033[0m\n' "$*"; }

# --- dispositivo ---------------------------------------------------------------
DEV=""
if [ -f "$ROOT/.env" ]; then
  DEV=$(grep -E "^ASR_DEVICE=" "$ROOT/.env" | head -1 | cut -d= -f2 | tr -d ' \r"'"'"'')
fi
[ -z "$DEV" ] && DEV="RDPSource"

echo "═══════════════════════════════════════════════════════════"
echo "  Sonda de microfono ($SECS s, dispositivo: $DEV)"
echo "═══════════════════════════════════════════════════════════"

head_ "1. Estado del servidor de audio"
if ! pactl info >/dev/null 2>&1; then
  err "no hay servidor PulseAudio accesible"
  echo "      bash tools/wslg_check.sh"
  exit 1
fi
pactl info 2>/dev/null | grep -E "Server Name|Default Source" | sed 's/^/    /'
echo "    fuentes:"
pactl list short sources 2>/dev/null | sed 's/^/      /'

head_ "2. Grabando $SECS s (habla durante la grabacion)"
if ! command -v parecord >/dev/null 2>&1; then
  err "falta parecord → sudo apt install -y pulseaudio-utils"
  exit 1
fi

timeout $((SECS + 3)) parecord --format=s16le --rate=16000 --channels=1 \
  --device "$DEV" --file-format=wav "$WAV" 2>/dev/null &
PID=$!
sleep "$SECS"
kill "$PID" 2>/dev/null
wait "$PID" 2>/dev/null
[ -s "$WAV" ] || { err "no se capturó nada"; rm -f "$WAV"; exit 1; }

head_ "3. Resultado"
python3 - "$WAV" <<'EOF'
import array, math, sys, wave

path = sys.argv[1]
try:
    w = wave.open(path)
except Exception as e:
    print("  no se pudo leer el wav: %s" % e); sys.exit(1)
n = w.getnframes()
raw = w.readframes(n)
a = array.array("h")
a.frombytes(raw[: len(raw) - (len(raw) % 2)])
if sys.byteorder == "big":
    a.byteswap()
if not a:
    print("  0 muestras"); sys.exit(1)
rms = math.sqrt(sum(float(x) * x for x in a) / len(a)) / 32768.0
peak = max(abs(x) for x in a) / 32768.0
print("  muestras : %d  (%.1f s)" % (len(a), len(a) / 16000.0))
print("  RMS      : %.5f" % rms)
print("  pico     : %.5f" % peak)
print("  umbral   : 0.01200  (VAD)")
print()
if rms < 0.003:
    print("  >> SILENCIO TOTAL: el microfono NO llega al WSL.")
    print("     · Windows: Ajustes > Privacidad > Microfono > permitir aplicaciones de escritorio")
    print("     · Windows: Ajustes > Sistema > Sonido > Entrada > pon el AURICULAR como predeterminado")
    print("     · comprueba que el auricular este conectado con perfil de manos libres (HFP)")
elif rms < 0.012:
    print("  >> LLEGA AUDIO, pero por DEBAJO del umbral del VAD.")
    print("     · habla mas fuerte / mas cerca del microfono")
    print("     · o baja el umbral: en pc/vad.py, TurnConfig.threshold = 0.012 -> 0.005")
    print("     · o instala el VAD preciso:  pip install webrtcvad-wheels")
else:
    print("  >> EL MICROFONO FUNCIONA: el audio llega con energia suficiente.")
    print("     Si el agente sigue en bucle, el problema NO es el microfono.")
EOF
rm -f "$WAV"

#!/usr/bin/env bash
# =============================================================================
#  bt_headset_pc.sh — configura el auricular Bluetooth en el PC
#
#  Sustituye al bt_headset.sh del robot: ahora el audio (micro + bocina) lo
#  gestiona el PC, no el bot.
#
#  Qué hace:
#    · lista las fuentes y sumideros de PulseAudio
#    · elige el auricular Bluetooth (preferencia: bluez_ > otro BT > default)
#    · lo pone como sumidero por defecto
#    · escribe ASR_DEVICE y TTS_DEVICE en el .env del PC
#    · mide el RMS de una captura de 2 s para saber si el micro funciona
#
#  USO
#    bash tools/bt_headset_pc.sh --list      # solo listar dispositivos
#    bash tools/bt_headset_pc.sh --detect    # detectar, configurar y escribir el .env
#    bash tools/bt_headset_pc.sh --test      # probar entrada (RMS) y salida (tono)
#    bash tools/bt_headset_pc.sh --detect --env /ruta/.env
# =============================================================================
set -uo pipefail

ACTION="detect"
ENV_FILE=""
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

while [ $# -gt 0 ]; do
  case "$1" in
    --list)   ACTION="list"; shift ;;
    --detect) ACTION="detect"; shift ;;
    --test)   ACTION="test"; shift ;;
    --env)    ENV_FILE="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "Opción desconocida: $1" >&2; exit 2 ;;
  esac
done

[ -n "$ENV_FILE" ] || ENV_FILE="$ROOT/.env"

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
err()  { printf '  \033[31m✗\033[0m %s\n' "$*" >&2; }
head_() { printf '\n\033[1m%s\033[0m\n' "$*"; }

# --- ¿Hay PulseAudio? ---------------------------------------------------------
head_ "1. Servidor de audio"
if ! command -v pactl >/dev/null 2>&1; then
  err "pactl no está instalado (PulseAudio)."
  err "En Debian/Ubuntu: sudo apt install pulseaudio-utils"
  err "En WSL2: el auricular vive en Windows -> mira la fase 3.2 de GUIA-DESPLIEGUE.md"
  exit 1
fi

if ! pactl info >/dev/null 2>&1; then
  # Caso frecuente en WSL2: PULSE_SERVER apunta a un PulseAudio de Windows que
  # no existe, pero el socket de WSLg si funciona.
  if [ -S /mnt/wslg/PulseServer ]; then
    warn "PULSE_SERVER=${PULSE_SERVER:-<sin definir>} no responde, pero el socket de WSLg si."
    export PULSE_SERVER="unix:/mnt/wslg/PulseServer"
    if pactl info >/dev/null 2>&1; then
      ok "usando el servidor de WSLg: $PULSE_SERVER"
      echo "     Para que sea permanente, quita la línea antigua de ~/.bashrc y deja esta:"
      echo "       export PULSE_SERVER=unix:/mnt/wslg/PulseServer"
    else
      err "el socket de WSLg tampoco responde → bash tools/wslg_check.sh"
      exit 1
    fi
  else
    err "No hay servidor PulseAudio accesible."
    err "WSL2? Ejecuta:  bash tools/wslg_check.sh"
    exit 1
  fi
fi
ok "PulseAudio accesible: $(pactl info | awk -F': ' '/Server Name/{print $2}')"

# --- Dispositivos -------------------------------------------------------------
head_ "2. Fuentes (micrófonos) y sumideros (salidas)"
SOURCES="$(pactl list short sources 2>/dev/null || true)"
SINKS="$(pactl list short sinks 2>/dev/null || true)"

if [ -z "$SOURCES" ] && [ -z "$SINKS" ]; then
  err "PulseAudio no ve ningún dispositivo de audio."
  err "¿Está emparejado el auricular y conectado como manos libres (HFP)?"
  exit 1
fi

echo "  Fuentes:";  echo "$SOURCES"  | sed 's/^/    /'
echo "  Sumideros:"; echo "$SINKS"   | sed 's/^/    /'

# --- Selección ----------------------------------------------------------------
pick_source() {
  # 1) bluez_ (auricular BT), 2) cualquier otro con "headset/headphone", 3) default
  local s
  s=$(echo "$SOURCES" | grep -E '\.bluez_input\.' | head -1 | awk '{print $1}')
  [ -n "$s" ] && { echo "$s"; return; }
  s=$(echo "$SOURCES" | grep -Ei 'headset|headphone|head' | grep -v '\.monitor$' | head -1 | awk '{print $1}')
  [ -n "$s" ] && { echo "$s"; return; }
  echo "$SOURCES" | grep -v '\.monitor$' | head -1 | awk '{print $1}'
}

pick_sink() {
  # 1) RDPSink (puente de WSLg: los altavoces de Windows), 2) bluez_ (BT nativo),
  # 3) cualquiera con "headset/headphone/head", 4) el primero
  local s
  s=$(echo "$SINKS" | awk '$1=="RDPSink"{print $1; exit}')
  [ -n "$s" ] && { echo "$s"; return; }
  s=$(echo "$SINKS" | grep -E '\.bluez_output\.' | head -1 | awk '{print $1}')
  [ -n "$s" ] && { echo "$s"; return; }
  s=$(echo "$SINKS" | grep -Ei 'headset|headphone|head' | head -1 | awk '{print $1}')
  [ -n "$s" ] && { echo "$s"; return; }
  echo "$SINKS" | head -1 | awk '{print $1}'
}

ASR_DEV="$(pick_source)"
TTS_DEV="$(pick_sink)"

[ "$ACTION" = "list" ] && exit 0

head_ "3. Dispositivo elegido"
if [ -n "$ASR_DEV" ]; then ok "ASR (micro)  : $ASR_DEV"; else err "No hay fuente de entrada disponible."; fi
if [ -n "$TTS_DEV" ]; then ok "TTS (bocina) : $TTS_DEV"; else err "No hay sumidero de salida disponible."; fi

# --- Poner el sumidero por defecto --------------------------------------------
if [ -n "$TTS_DEV" ]; then
  pactl set-default-sink "$TTS_DEV" 2>/dev/null && ok "Sumidero por defecto: $TTS_DEV"
fi

# --- Medir el RMS -------------------------------------------------------------
head_ "4. Prueba de micrófono (2 s)"
RMS="n/d"
if command -v parecord >/dev/null 2>&1 && [ -n "$ASR_DEV" ]; then
  TMPF="$(mktemp -u /tmp/rmstestXXXX.wav)"
  if timeout 5 parecord --format=s16le --rate=16000 --channels=1 --device "$ASR_DEV" --file-format=wav "$TMPF" >/dev/null 2>&1; then
    if command -v sox >/dev/null 2>&1; then
      RMS=$(sox "$TMPF" -n stat 2>/dev/null | awk '/RMS amplitude/ {print $3}')
    else
      RMS="(instala sox para medirlo)"
    fi
    rm -f "$TMPF"
  fi
  if [ -n "$RMS" ] && [ "$RMS" != "n/d" ]; then
    if awk "BEGIN{exit !($RMS > 0.001)}" 2>/dev/null; then
      ok "RMS = $RMS  → el micrófono está captando señal"
    else
      warn "RMS = $RMS  → silencio. Comprueba el mute del auricular y el modo HFP."
    fi
  fi
else
  warn "parecord no disponible o sin fuente: instala pulseaudio-utils"
fi

# --- Escribir el .env ---------------------------------------------------------
head_ "5. Configuración en $ENV_FILE"
if [ ! -f "$ENV_FILE" ]; then
  warn "No existe $ENV_FILE. Creoando desde .env.example"
  if [ -f "$ROOT/.env.example" ]; then
    cp "$ROOT/.env.example" "$ENV_FILE"; chmod 600 "$ENV_FILE"
  else
    : > "$ENV_FILE"; chmod 600 "$ENV_FILE"
  fi
fi

set_env() {
  local key="$1" val="$2"
  if grep -qE "^${key}=" "$ENV_FILE" 2>/dev/null; then
    # sustituye la línea, tolerando CRLF
    sed -i "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$val" >> "$ENV_FILE"
  fi
  ok "$key=$val"
}

[ -n "$ASR_DEV" ] && set_env "ASR_DEVICE" "$ASR_DEV"
[ -n "$TTS_DEV" ] && set_env "TTS_DEVICE" "$TTS_DEV"
set_env "ASR_BACKEND" "${ASR_BACKEND:-whispercpp}"

chmod 600 "$ENV_FILE" 2>/dev/null || true

# --- Prueba de salida ---------------------------------------------------------
if [ "$ACTION" = "test" ] && [ -n "$TTS_DEV" ]; then
  head_ "6. Prueba de bocina"
  if command -v paplay >/dev/null 2>&1; then
    TMPW="$(mktemp -u /tmp/toneXXXX.wav)"
    if command -v sox >/dev/null 2>&1; then
      sox -n -r 44100 -c 1 -b 16 "$TMPW" synth 0.4 sine 440 2>/dev/null &&
        paplay --device="$TTS_DEV" "$TMPW" 2>/dev/null &&
        ok "Tono de 440 Hz enviado al auricular" || warn "No se pudo reproducir"
      rm -f "$TMPW"
    else
      warn "Instala sox (sudo apt install sox) para el tono de prueba"
    fi
  else
    warn "paplay no disponible"
  fi
fi

head_ "Listo"
echo "  Comprueba que en el .env queda:"
echo "    ASR_DEVICE=$ASR_DEV"
echo "    TTS_DEVICE=$TTS_DEV"

#!/usr/bin/env bash
# =============================================================================
#  env_check.sh — comprueba que el .env tiene TODO lo que necesita la
#                  arquitectura nueva (agente en el PC, robot como ejecutor).
#
#  No imprime la clave: solo la enmascara.
#
#  USO
#    bash tools/env_check.sh                    # usa el .env de la raíz del repo
#    bash tools/env_check.sh /ruta/al/.env
# =============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${1:-$ROOT/.env}"

ok()   { printf '  \033[32m✓\033[0m %-18s %s\n' "$1" "${2:-}"; }
warn() { printf '  \033[33m!\033[0m %-18s %s\n' "$1" "${2:-}"; }
err()  { printf '  \033[31m✗\033[0m %-18s %s\n' "$1" "${2:-}"; }
head_() { printf '\n\033[1m%s\033[0m\n' "$*"; }

if [ ! -f "$ENV_FILE" ]; then
  err "No existe: $ENV_FILE"
  echo "    cp .env.example .env && chmod 600 .env"
  exit 1
fi

# --- leer valores (sin eval, tolerante a comillas y CRLF) --------------------
get() {
  local key="$1" line
  line=$(grep -E "^[[:space:]]*${key}=" "$ENV_FILE" 2>/dev/null | head -1)
  [ -z "$line" ] && { echo ""; return; }
  line="${line#*=}"
  line="${line%$'\r'}"                       # quita CR de fin de línea (Windows)
  line="${line%$'\n'}"
  line="$(echo "$line" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  line="${line%\"}"; line="${line#\"}"       # comillas dobles
  line="${line%\'}"; line="${line#\'}"       # comillas simples
  echo "$line"
}

mask() {
  local v="$1"
  if [ ${#v} -le 12 ]; then echo "$v"; else echo "${v:0:8}…${v: -4}"; fi
}

echo "═══════════════════════════════════════════════════════════"
echo "  .env → $ENV_FILE"
echo "═══════════════════════════════════════════════════════════"

# --- 0. Formato del fichero ---------------------------------------------------
head_ "0. Formato"
PERMS="$(stat -c '%a' "$ENV_FILE" 2>/dev/null || echo '?')"
if [ "$PERMS" = "600" ]; then ok "permisos" "600 ✓"; else warn "permisos" "$PERMS (deberían ser 600) → chmod 600 $(basename "$ENV_FILE")"; fi

if grep -qU $'\r' "$ENV_FILE" 2>/dev/null; then
  err "fin de línea" "CRLF (Windows) → la clave acabará en \\r y la API devolverá 401"
  echo "      sed -i 's/\r$//' \"$ENV_FILE\""
else
  ok "fin de línea" "LF ✓"
fi

if grep -qE "^[[:space:]]*#" "$ENV_FILE"; then
  ok "comentarios" "hay líneas comentadas (ok)"
fi

# --- 1. Clave de la API -------------------------------------------------------
head_ "1. Credenciales"
# El agente (voice_agent.py) lee LLM_API_KEY. nvidia_models.py y
# nvidia_smoke_test.py aceptan cualquiera de las dos.
KEY="$(get LLM_API_KEY)"
if [ -z "$KEY" ]; then
  err "LLM_API_KEY" "FALTA → ponla en el .env del PC (voice_agent.py la lee con este nombre)"
elif [ "${KEY:0:6}" != "nvapi-" ]; then
  err "LLM_API_KEY" "prefijo raro: $(mask "$KEY") → debe empezar por nvapi-"
elif [ ${#KEY} -lt 40 ]; then
  err "LLM_API_KEY" "demasiado corta: $(mask "$KEY")"
else
  ok "LLM_API_KEY" "$(mask "$KEY")  (${#KEY} caracteres)"
fi

if [ -n "$(get NVIDIA_API_KEY)" ]; then
  warn "NVIDIA_API_KEY" "también está puesta; el agente usa LLM_API_KEY. No dupliques la clave"
fi

# --- 2. Modelo y ASR ----------------------------------------------------------
head_ "2. Modelo y ASR"
MODEL="$(get LLM_MODEL)"
if [ -z "$MODEL" ]; then
  err "LLM_MODEL" "FALTA → nvidia/nemotron-3.5-bolt-e4b"
elif [ "$MODEL" = "nvidia/nemotron-3.5-bolt-e4b" ]; then
  ok "LLM_MODEL" "$MODEL ✓"
else
  warn "LLM_MODEL" "$MODEL (el verificado es nvidia/nemotron-3.5-bolt-e4b)"
fi

BACKEND="$(get ASR_BACKEND)"
case "$BACKEND" in
  whispercpp) warn "ASR_BACKEND" "whispercpp → necesitas el BINARIO whisper.cpp en el PC (se compiló en el robot, no sirve ahí)" ;;
  openai)    ok "ASR_BACKEND" "openai (necesita OPENAI_API_KEY en el .env)" ;;
  "")         err "ASR_BACKEND" "FALTA → whispercpp u openai" ;;
  *)          warn "ASR_BACKEND" "$BACKEND" ;;
esac

if [ -n "$(get OPENAI_API_KEY)" ] && [ "$BACKEND" = "openai" ]; then
  ok "OPENAI_API_KEY" "$(mask "$(get OPENAI_API_KEY)")"
fi

# --- 3. Dispositivos de audio -------------------------------------------------
head_ "3. Audio (ahora en el PC)"
ASR="$(get ASR_DEVICE)"
TTS="$(get TTS_DEVICE)"
if [ -z "$ASR" ]; then
  if grep -qE "^[[:space:]]*ASR_DEVICE=" "$ENV_FILE" 2>/dev/null; then
    ok "ASR_DEVICE" "vacio → autodeteccion en vad.py (bluez_ > pulse > alsa)"
  else
    err "ASR_DEVICE" "FALTA → bash tools/bt_headset_pc.sh --detect"
  fi
else
  warn "ASR_DEVICE" "$ASR  → ¿es el del PC? Si es un bluez_ escrito por el bt_headset.sh DEL ROBOT, está obsoleto"
fi
if [ -z "$TTS" ]; then
  if grep -qE "^[[:space:]]*TTS_DEVICE=" "$ENV_FILE" 2>/dev/null; then
    ok "TTS_DEVICE" "vacio → autodeteccion (bluez_ > pulse > alsa)"
  else
    err "TTS_DEVICE" "FALTA → bash tools/bt_headset_pc.sh --detect"
  fi
else
  warn "TTS_DEVICE" "$TTS  → mismo chequeo que ASR_DEVICE"
fi

# --- 4. Robot -----------------------------------------------------------------
head_ "4. Robot"
HOST="$(get TONYPI_HOST)"
if [ -z "$HOST" ]; then
  err "TONYPI_HOST" "FALTA → la IP del robot (en modo AP: 192.168.149.1)"
  echo "      el agente también la acepta por argumento:  python3 pc/voice_agent.py --host <IP>"
else
  ok "TONYPI_HOST" "$HOST"
fi
for v in TONYPI_RPC_PORT TONYPI_MJPG_PORT; do
  val="$(get $v)"
  case "$v" in
    TONYPI_RPC_PORT)  def="9030 (JSON-RPC del robot)" ;;
    TONYPI_MJPG_PORT) def="8080 (snapshot de la cámara)" ;;
  esac
  if [ -z "$val" ]; then warn "$v" "no está (por defecto: $def)"; else ok "$v" "$val"; fi
done

# --- 5. Memoria y varios ------------------------------------------------------
head_ "5. Otros"
MEM="$(get PONTIBOT_MEMORY)"
if [ -z "$MEM" ]; then
  ok "PONTIBOT_MEMORY" "~/.pontibot/memory.json (por defecto)"
else
  ok "PONTIBOT_MEMORY" "$MEM"
fi

head_ "Resumen"
echo "  · Lo que está bien: se queda como está."
echo "  · Lo que hay que rehacer en el PC:  ASR_DEVICE / TTS_DEVICE  →  bash tools/bt_headset_pc.sh --detect"
echo "  · Lo que hay que decidir:         ASR_BACKEND  → whisper.cpp compilado en el PC, u OpenAI"
echo "  · Lo que hay que añadir:          TONYPI_HOST  (o el argumento --host de voice_agent.py)"
echo "═══════════════════════════════════════════════════════════"

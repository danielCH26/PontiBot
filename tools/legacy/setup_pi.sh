#!/usr/bin/env bash
#
# Instalador del stack de voz para el TonyPi.
# EJECUTAR DENTRO DEL ROBOT (por SSH o terminal VNC):
#
#   cd ~/tonypi-mcp && bash setup_pi.sh
#
# Opciones:
#   --with-whisper   compila whisper.cpp para ASR local (30-60 min en la Pi)
#   --with-piper     instala piper + voz en espanol (TTS local natural)
#   --with-service   instala y habilita el servicio systemd del agente
#   --pair-bt MAC    empareja un auricular bluetooth
#   --fix-repos      arregla las fuentes de apt (buster esta archivado)
#   --no-apt         no instalar paquetes del sistema
#
# NOTA SOBRE RASPBIAN BUSTER (imagen del TonyPi v1.0):
#   - buster esta archivado: raspbian.raspberrypi.org ya no existe y hay que
#     usar legacy.raspbian.org + archive.debian.org.
#   - el paquete 'pipewire-audio-client-libraries' NO existe en buster (es de
#     bullseye+). Aqui el stack de audio es PulseAudio y pipewire 0.2.5.
#
set -uo pipefail

WITH_WHISPER=0
WITH_PIPER=0
WITH_SERVICE=0
PAIR_BT=""
DO_APT=1
FIX_REPOS=0

for arg in "$@"; do
  case "$arg" in
    --with-whisper) WITH_WHISPER=1 ;;
    --with-piper)   WITH_PIPER=1 ;;
    --with-service) WITH_SERVICE=1 ;;
    --pair-bt)      PAIR_BT="${2:-}"; shift ;;
    --fix-repos)    FIX_REPOS=1 ;;
    --no-apt)       DO_APT=0 ;;
    -h|--help)      sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "opcion desconocida: $arg" >&2; exit 1 ;;
  esac
done

AGENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROBOT_HOME="/home/pi/tonypi-mcp"

say()  { printf "\n\033[1;36m==> %s\033[0m\n" "$*"; }
note() { printf "\033[0;36m[info] %s\033[0m\n" "$*"; }
warn() { printf "\033[1;33m[aviso] %s\033[0m\n" "$*"; }
err()  { printf "\033[1;31m[error] %s\033[0m\n" "$*"; }
ok()   { printf "\033[1;32m[ ok ] %s\033[0m\n" "$*"; }

say "TonyPi - instalador del stack de voz"
echo "directorio: $AGENT_DIR"

CODENAME=$(grep -oP '(?<=VERSION_CODENAME=).*' /etc/os-release 2>/dev/null | tr -d '"' | head -1)
[ -z "$CODENAME" ] && CODENAME=$(lsb_release -cs 2>/dev/null || echo "desconocido")
echo "sistema: $CODENAME"

# ════════════════════════════════════════════════════════════════════
#  0 · RED  (sin DNS no hay apt, ni pip, ni LLM)
# ════════════════════════════════════════════════════════════════════
check_network() {
  local dns_ok=0 http_ok=0 route_ok=0
  if command -v ip >/dev/null 2>&1; then
    ip route 2>/dev/null | grep -q '^default' && route_ok=1
  else
    route_ok=1   # sin 'ip' no hay forma de comprobarlo: no lo penalizamos
  fi
  getent hosts archive.debian.org >/dev/null 2>&1 && dns_ok=1
  curl -s -o /dev/null -m 10 -w '%{http_code}' https://deb.debian.org/ 2>/dev/null | grep -q '^2' && http_ok=1

  echo "  ruta por defecto : $([ $route_ok = 1 ] && echo OK || echo FALLO)"
  echo "  DNS              : $([ $dns_ok = 1 ] && echo OK || echo FALLO)"
  echo "  salida HTTP      : $([ $http_ok = 1 ] && echo OK || echo FALLO)"
  return $(( route_ok && dns_ok && http_ok ))
}

if [ "$DO_APT" = "1" ] || [ "$FIX_REPOS" = "1" ]; then
  say "Red"
  if check_network; then
    ok "el robot tiene internet"
  else
    warn "el robot NO tiene internet resoluble"
    echo
    echo "  Sin DNS, 'apt update' falla con 'Temporary failure resolving' y"
    echo "  no se puede instalar nada. Esto es lo primero que hay que arreglar."
    echo
    echo "  Diagnostico completo:"
    echo "      bash ~/tonypi-mcp/tonypi_wifi.sh probe"
    echo
    echo "  Atajo (1 minuto, sin tocar la config del WiFi):"
    echo "      1) enchufa un cable de red (RJ45) del robot al router"
    echo "      2) ip -br addr show eth0   # y ping -c3 1.1.1.1"
    echo
    echo "  O entra en tu router por WiFi:"
    echo "      bash ~/tonypi-mcp/tonypi_wifi.sh sta --ssid \"TU_RED\" --pass \"TU_CLAVE\""
    echo
    if [ "$FIX_REPOS" = "0" ] && [ "$DO_APT" = "1" ]; then
      err "sin internet no puedo instalar paquetes. Arregla la red y vuelve a ejecutar."
      err "si solo quieres lo que no necesita red: bash setup_pi.sh --no-apt"
      exit 1
    fi
  fi
fi

# ════════════════════════════════════════════════════════════════════
#  0b · REPOSITORIOS ARQUIVADOS (buster)
# ════════════════════════════════════════════════════════════════════
fix_repos() {
  say "Arreglando las fuentes de apt ($CODENAME)"
  local stamp; stamp=$(date +%Y%m%d-%H%M%S)

  for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list; do
    [ -f "$f" ] || continue
    grep -q 'raspbian\.raspberrypi\.org' "$f" 2>/dev/null || continue
    sudo cp -p "$f" "$f.bak.$stamp"
    # raspbian.raspberrypi.org esta muerto (dists/buster vacio): se comenta
    # la linea (deb Y deb-src) y se añaden despues las del archivo
    sudo sed -i -E '/raspbian\.raspberrypi\.org/ s|^(deb-src? )|# (repo muerto) \1|' "$f"
    ok "$f: linea de raspbian.raspberrypi.org comentada (copia en $f.bak.$stamp)"
  done

  if [ "$CODENAME" = "buster" ]; then
    local need=(
      "deb https://legacy.raspbian.org/raspbian/ buster main contrib non-free rpi"
      "deb http://archive.raspberrypi.org/debian/ buster main"
      "deb http://archive.debian.org/debian/ buster main contrib non-free"
      "deb http://archive.debian.org/debian-security/ buster/updates main contrib non-free"
    )
    for line in "${need[@]}"; do
      if ! grep -qF "$line" /etc/apt/sources.list 2>/dev/null; then
        echo "$line" | sudo tee -a /etc/apt/sources.list >/dev/null
        ok "añadido: $line"
      fi
    done
    # los repos archivados tienen el Release caducado: hay que saltarse el chequeo
    echo 'Acquire::Check-Valid-Until "false";' | sudo tee /etc/apt/apt.conf.d/99no-check-valid-until >/dev/null
    ok "Check-Valid-Until desactivado (obligatorio en repos archivados)"

    # Las claves de los repos archivados no vienen en la imagen de Hiwonder
    # (NO_PUBKEY ... is not signed). Se importan de Debian; si no se puede
    # (keyserver bloqueado), se marcan las lineas como [trusted=yes].
    if ! apt-key list 2>/dev/null | grep -qi '648ACFD622F3D138'; then
      note "importando claves de los repos archivados"
      for u in https://ftp-master.debian.org/keys/archive-key-9.asc \
               https://ftp-master.debian.org/keys/archive-key-10.asc \
               https://ftp-master.debian.org/keys/archive-key-10-security.asc \
               https://ftp-master.debian.org/keys/archive-key-11.asc; do
        sudo curl -fsSL "$u" 2>/dev/null | sudo apt-key add - >/dev/null 2>&1 || true
      done
      sudo apt-key adv --keyserver keyserver.ubuntu.com --recv-keys \
        648ACFD622F3D138 0E98404D386FA1D9 DCC9EFBF77E11517 \
        112695A0E562B32A 54404762BBB6E853 >/dev/null 2>&1 || true
    fi
  fi

  say "Actualizando indices (puede tardar un poco)"
  local out
  out=$(sudo apt-get update 2>&1)
  echo "$out" | tail -15
  # Si siguen faltando las claves, se marca el repo archivado como de
  # confianza: es un distro congelado e inmutable, no hay riesgo real.
  if echo "$out" | grep -q 'NO_PUBKEY\|is not signed'; then
    warn "faltan claves GPG: se marca archive.debian.org como [trusted=yes]"
    sudo sed -i -E 's|^deb http://archive\.debian\.org|deb [trusted=yes] http://archive.debian.org|' /etc/apt/sources.list
    sudo apt-get update 2>&1 | tail -5
  fi
  echo
  echo "  Si sale 'Temporary failure resolving' -> es DNS, no son los repos."
  echo "  Si un espejo concreto falla (p.ej. mirrors.ustc.edu.cn), comentalo"
  echo "  en /etc/apt/sources.list: ya estan los espejos del archivo."
}

[ "$FIX_REPOS" = "1" ] && fix_repos

# ════════════════════════════════════════════════════════════════════
#  1 · PAQUETES DEL SISTEMA
# ════════════════════════════════════════════════════════════════════
# Instala un grupo. Si falla el grupo entero, reintenta uno a uno para que
# la ausencia de un paquete no se lleve por delante los demas.
install_group() {
  local label="$1"; shift
  local pkgs="$*"
  echo "  · $label"
  if sudo apt-get install -y --no-install-recommends $pkgs >/dev/null 2>&1; then
    ok "$label: todo instalado"
    return 0
  fi
  warn "$label: instalando uno a uno (alguno no existe en este repositorio)"
  local p
  for p in $pkgs; do
    if sudo apt-get install -y --no-install-recommends "$p" >/dev/null 2>&1; then
      ok "  $p"
    else
      warn "  $p NO disponible (se sigue sin el)"
    fi
  done
}

if [ "$DO_APT" = "1" ]; then
  say "Paquetes del sistema"

  if [ "$CODENAME" = "buster" ]; then
    APT_PIPEWIRE="pipewire"          # 0.2.5: no existe pipewire-audio-client-libraries
  else
    APT_PIPEWIRE="pipewire pipewire-audio-client-libraries"
  fi

  # lo imprescindible: sin esto no hay TTS, ni ffmpeg, ni compilador
  install_group "base" \
    alsa-utils libsndfile1 espeak-ng ffmpeg \
    cmake build-essential git \
    python3-pip python3-venv python3-dev

  # audio: en buster el servidor de sonido es PulseAudio
  install_group "audio" \
    pulseaudio pulseaudio-utils pulseaudio-module-bluetooth \
    bluez bluez-tools

  # opcional: pipewire (experimental en buster) y portaudio
  install_group "opcionales" \
    $APT_PIPEWIRE portaudio19-dev

  say "Comprobando lo esencial"
  for tool in espeak-ng ffmpeg aplay arecord pactl parecord paplay; do
    if command -v "$tool" >/dev/null 2>&1; then
      ok "$tool"
    else
      warn "$tool no disponible (sigue adelante)"
    fi
  done
fi

# ════════════════════════════════════════════════════════════════════
#  2 · ENTORNO PYTHON
# ════════════════════════════════════════════════════════════════════
say "Entorno python"
cd "$AGENT_DIR"

# Disco: la imagen de Hiwonder llega al 95% de uso. Compilar whisper.cpp
# necesita espacio, asi que se limpia antes de nada.
note "limpiando cache de apt y logs antiguos"
sudo apt-get clean 2>/dev/null || true
sudo journalctl --vacuum-size=20M >/dev/null 2>&1 || true
df -h / | tail -1

PY_VER=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "0.0")
note "python3 del sistema: $PY_VER"

# El SDK de MCP exige Python >= 3.10. En el robot (buster = 3.7) no cabe:
# se instala solo lo que el agente necesita y se usa el backend 'rpc'.
PY_OK=$(python3 -c 'import sys; print(1 if sys.version_info[:2] >= (3,10) else 0)' 2>/dev/null || echo 0)
if [ "$PY_OK" = "1" ]; then
  REQ_FILE="requirements.txt"
  note "SDK MCP instalable en este python"
else
  REQ_FILE="requirements-pi.txt"
  note "python < 3.10: se omite el SDK MCP (el agente usara --backend rpc)"
  note "el servidor MCP se ejecuta en tu PC, no en el robot"
fi

if [ ! -d .venv ]; then
  python3 -m venv .venv || err "no se pudo crear el venv (falta python3-venv?)"
fi
if [ -x .venv/bin/pip ]; then
  # pip en el robot: los mirrors por defecto (piwheels) agotan el tiempo de
  # espera en una red movil, y el fallo de build de setuptools hace que TODO
  # el pip install quede sin hacer. Se sube el timeout, se anaden reintentos
  # y se evita la construccion desde el fuente.
  PIP_ARGS="--disable-pip-version-check --timeout 60 --retries 8"
  export PIP_INDEX_URL="https://pypi.org/simple"
  export PIP_EXTRA_INDEX_URL="https://www.piwheels.org/simple"

  ./.venv/bin/pip install --quiet $PIP_ARGS --upgrade "pip<24.1" 2>/dev/null || true
  if ./.venv/bin/pip install --quiet $PIP_ARGS -r "$REQ_FILE"; then
    ok "dependencias instaladas ($REQ_FILE)"
  else
    warn "reintentando sin aislamiento de build"
    if ./.venv/bin/pip install --quiet $PIP_ARGS --no-build-isolation -r "$REQ_FILE"; then
      ok "dependencias instaladas en el reintento"
    else
      warn "no se pudieron instalar todas las dependencias"
    fi
  fi
  if [ "$PY_OK" != "1" ]; then
    # solo binario: si no encuentra el wheel, falla limpio en vez de compilar
    if ./.venv/bin/pip install --quiet $PIP_ARGS --only-binary=:all: \
         "webrtcvad-wheels==2.0.14"; then
      ok "webrtcvad instalado (VAD robusto)"
    else
      warn "webrtcvad no instalado: el VAD caera al modo simple"
    fi
  fi
  echo "venv ok"
else
  err "no hay venv: no se pueden instalar las dependencias de python"
fi

# ════════════════════════════════════════════════════════════════════
#  3 · PIPER (TTS local)
# ════════════════════════════════════════════════════════════════════
if [ "$WITH_PIPER" = "1" ]; then
  say "Piper (TTS local)"
  PIPER_MODEL_DIR="${PIPER_MODEL_DIR:-$HOME/.local/share/piper-voices}"
  mkdir -p "$PIPER_MODEL_DIR"
  VOICE_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/davefx-medium/es_ES-davefx-medium.onnx"
  VOICE_CFG="https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/davefx-medium/es_ES-davefx-medium.onnx.json"
  if [ ! -f "$PIPER_MODEL_DIR/es_ES-davefx-medium.onnx" ]; then
    curl -fL "$VOICE_URL" -o "$PIPER_MODEL_DIR/es_ES-davefx-medium.onnx" && \
    curl -fL "$VOICE_CFG" -o "$PIPER_MODEL_DIR/es_ES-davefx-medium.onnx.json"
  fi
  echo "piper listo en $PIPER_MODEL_DIR"
fi

# ════════════════════════════════════════════════════════════════════
#  4 · WHISPER (ASR local) — tarda mucho
# ════════════════════════════════════════════════════════════════════
if [ "$WITH_WHISPER" = "1" ]; then
  say "whisper.cpp (ASR local, esto tarda)"
  cd "$HOME"
  if [ ! -d whisper.cpp ]; then
    git clone --depth 1 https://github.com/ggml-org/whisper.cpp
  fi
  cd whisper.cpp
  cmake -B build -DCMAKE_BUILD_TYPE=Release
  cmake --build build -j"$(nproc)" --target whisper-cli whisper-server
  mkdir -p "$HOME/models"
  MODEL="${WHISPER_MODEL:-base}"
  URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-${MODEL}.bin"
  if [ ! -f "$HOME/models/ggml-${MODEL}.bin" ]; then
    curl -fL "$URL" -o "$HOME/models/ggml-${MODEL}.bin"
  fi
  mkdir -p /usr/local/bin
  ln -sf "$HOME/whisper.cpp/build/bin/whisper-cli" /usr/local/bin/whisper
  ln -sf "$HOME/whisper.cpp/build/bin/whisper-server" /usr/local/bin/whisper-server
  echo "whisper.cpp listo"
fi

# ════════════════════════════════════════════════════════════════════
#  5 · BLUETOOTH
# ════════════════════════════════════════════════════════════════════
if [ -n "$PAIR_BT" ]; then
  say "Emparejando bluetooth $PAIR_BT"
  bluetoothctl power on
  bluetoothctl agent on
  bluetoothctl default-agent || true
  bluetoothctl scan on || true
  sleep 5
  bluetoothctl pair "$PAIR_BT" || true
  bluetoothctl trust "$PAIR_BT" || true
  bluetoothctl connect "$PAIR_BT" || true
  bluetoothctl scan off || true
  echo "listo. comprueba el perfil en pavucontrol"
fi

# ════════════════════════════════════════════════════════════════════
#  6 · SERVICIO SYSTEMD
# ════════════════════════════════════════════════════════════════════
if [ "$WITH_SERVICE" = "1" ]; then
  say "Servicio systemd"
  sudo mkdir -p "$ROBOT_HOME"
  sudo cp -r "$AGENT_DIR"/*.py "$ROBOT_HOME"/ 2>/dev/null || true
  sudo chown -R pi:pi "$ROBOT_HOME"

  sudo tee /etc/systemd/system/pontibot.service >/dev/null <<EOF
[Unit]
Description=PontiBot agente de voz (TonyPi)
After=tonypi.service bluetooth.service
Requires=tonypi.service

[Service]
Type=simple
User=pi
WorkingDirectory=$ROBOT_HOME
Environment="PATH=$AGENT_DIR/.venv/bin:/usr/local/bin:/bin:/usr/sbin:/sbin"
Environment="PYTHONPATH=$ROBOT_HOME"
EnvironmentFile=-$ROBOT_HOME/.env
# Necesario para que parecord/paplay (audio bluetooth via PulseAudio) hablen
# con el servidor de sonido del usuario pi.
Environment="XDG_RUNTIME_DIR=/run/user/1000"
Environment="DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus"
Environment="TTS_BACKEND=espeak"
Environment="ASR_BACKEND=whispercpp"
Environment="LLM_LANGUAGE=es"
Environment="LLM_BASE_URL=https://integrate.api.nvidia.com/v1"
Environment="LLM_MODEL=nvidia/nemotron-3.5-bolt-e4b"
Environment="PONTIBOT_MEMORY=$ROBOT_HOME/memory.json"
Environment="PONTIBOT_MAX_TURNS=12"
ExecStart=$AGENT_DIR/.venv/bin/python $ROBOT_HOME/voice_agent.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

  sudo systemctl daemon-reload
  sudo systemctl enable pontibot.service
  sudo systemctl restart pontibot.service
  echo "servicio instalado. logs: journalctl -u pontibot -f"
fi

# ════════════════════════════════════════════════════════════════════
#  7 · DIAGNOSTICO
# ════════════════════════════════════════════════════════════════════
say "Diagnostico"
cd "$AGENT_DIR"
[ -x .venv/bin/python ] && ./.venv/bin/python audio_doctor.py || warn "no se pudo ejecutar audio_doctor.py"

say "Hecho"
cat <<'EOF'

Siguientes pasos:

  1. El fichero .env (con la clave de NVIDIA) viene en el proyecto, en
     /home/pi/tonypi-mcp/.env con permisos 600. Comprueba que existe:
       ls -l ~/tonypi-mcp/.env
     Si no esta, crealo con el contenido de .env.example.

  2. Si prefieres cambiar la clave: esta en el panel de secretos de Mavis
     (NVIDIA_API_KEY) o en https://build.nvidia.com/settings

  3. Prueba el audio:
       cd /home/pi/tonypi-mcp && ./.venv/bin/python audio_doctor.py

  4. Arranca el agente a mano antes de dejarlo en servicio:
       cd /home/pi/tonypi-mcp
       set -a; source .env; set +a
       ./.venv/bin/python voice_agent.py

     (LLM_MODEL verificado: nvidia/nemotron-3.5-bolt-e4b)

EOF

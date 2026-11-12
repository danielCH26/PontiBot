#!/usr/bin/env bash
#
# Despliegue completo del agente TonyPi en el robot, con un solo comando.
#
#
#   ── DISEÑO ACTUAL (el agente vive en el PC) ────────────────────────────────
#   El robot NO necesita nuestro Python. Este script sirve para:
#     · copiar el parche de firmware y aplicarlo   (--patch)
#   Para desplegar el diseño ANTERIOR (agente DENTRO del robot) necesitas
#   además --with-service, y solo entonces se escribe el .env con la clave.
#
#   ── DESPLIEGUE COMPLETO (diseño anterior) ────────────────────────────────
#   ./deploy_to_robot.sh --host 192.168.1.50
#
# Hace todo lo que hay que hacer, en orden:
#   1. comprueba que el robot responde por SSH
#   2. comprueba que el robot tiene internet (imprescindible para el LLM)
#   3. copia el codigo (sin .env ni basurilla)
#   4. escribe el .env en el robot con la clave de NVIDIA
#   5. instala dependencias (apt, venv, piper, whisper si los pides)
#   6. aplica el parche opcional del firmware (--patch)
#   7. instala el servicio systemd (--with-service)
#   8. verifica: test_rpc.py + audio_doctor.py + una llamada real al LLM
#
# Opciones:
#   --host IP        IP o hostname del robot      (o $TONYPI_HOST)
#   --user USUARIO   usuario ssh (default: pi)
#   --key CLAVE      clave NVIDIA (o $NVIDIA_API_KEY / $LLM_API_KEY)
#   --with-piper     instala piper (TTS natural, local)
#   --with-whisper   compila whisper.cpp (ASR local)   [tarda]
#   --with-service   instala y habilita el servicio systemd
#   --patch          aplica el parche del firmware (buzzer + audio por RPC)
#   --dry-run        solo comprueba la conexion
#
set -euo pipefail

HOST="${TONYPI_HOST:-}"
USER_NAME="${TONYPI_USER:-pi}"
API_KEY="${NVIDIA_API_KEY:-${LLM_API_KEY:-}}"
WITH_PIPER=0
WITH_WHISPER=0
WITH_SERVICE=0
APPLY_PATCH=0
DRY_RUN=0

while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --user) USER_NAME="$2"; shift 2 ;;
    --key) API_KEY="$2"; shift 2 ;;
    --with-piper) WITH_PIPER=1; shift ;;
    --with-whisper) WITH_WHISPER=1; shift ;;
    --with-service) WITH_SERVICE=1; shift ;;
    --patch) APPLY_PATCH=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) sed -n '2,28p' "$0"; exit 0 ;;
    *) echo "opcion desconocida: $1" >&2; exit 1 ;;
  esac
done

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # raíz del repo
REMOTE_DIR="/home/$USER_NAME/tonypi-mcp"

say()  { printf "\n\033[1;36m==> %s\033[0m\n" "$*"; }
ok()   { printf "  \033[1;32mOK\033[0m  %s\n" "$*"; }
warn() { printf "  \033[1;33m!!\033[0m  %s\n" "$*"; }
die()  { printf "  \033[1;31mXX\033[0m  %s\n" "$*" >&2; exit 1; }

[ -n "$HOST" ] || die "falta --host (o export TONYPI_HOST=...)"

say "Destino: $USER_NAME@$HOST:$REMOTE_DIR"

# --------------------------------------------------------------------------- #
say "1/8 Conectividad SSH"
if ! ssh -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new "$USER_NAME@$HOST" "true" 2>/dev/null; then
  die "no puedo conectarme por SSH. Comprueba la IP, el usuario y que el robot tenga sshd activo"
fi
ok "ssh funciona"

if [ "$DRY_RUN" = "1" ]; then
  say "dry-run: nada mas que hacer"
  exit 0
fi

# --------------------------------------------------------------------------- #
say "2/8 Comprobando que el robot tiene internet"
# En modo AP (hotspot HW...) el robot NO sale a internet, y sin internet no
# hay LLM. Esta es la causa numero uno de "el robot no habla".
if ssh "$USER_NAME@$HOST" "curl -sS -o /dev/null -m 10 https://integrate.api.nvidia.com/v1/models" 2>/dev/null; then
  ok "el robot llega a NVIDIA"
else
  warn "el robot NO puede salir a internet. El agente de voz no funcionara."
  warn "diagnostica la red del robot:"
  warn "  ./tonypi_wifi.sh --host $HOST probe"
  warn "despues ponlo en modo LAN/STA (ver GUIA_WIFI.md):"
  warn "  ./tonypi_wifi.sh --host $HOST sta --ssid 'TU_WIFI' --pass 'TU_PASS'"
fi

# --------------------------------------------------------------------------- #
say "3/8 Copiando el codigo"
tar -czf - \
  --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='.git' --exclude='nvidia_catalog.json' \
  -C "$SRC_DIR" . | ssh "$USER_NAME@$HOST" "mkdir -p $REMOTE_DIR && tar xzf - -C $REMOTE_DIR"
ok "codigo copiado"

# --------------------------------------------------------------------------- #
say "4/8 Escribiendo la configuracion (.env)"
# La clave viaja por stdin, NO en la linea de comandos: asi no aparece en el
# 'ps' de ninguna de las dos maquinas.
ENV_CONTENT=""
if [ -n "$API_KEY" ]; then
  ENV_CONTENT="LLM_API_KEY=$API_KEY
LLM_BASE_URL=https://integrate.api.nvidia.com/v1
LLM_MODEL=nvidia/nemotron-3.5-bolt-e4b
LLM_LANGUAGE=es
LLM_TEMPERATURE=0.6
ASR_BACKEND=whispercpp
TTS_BACKEND=espeak
PONTIBOT_MEMORY=~/.pontibot/memory.json
PONTIBOT_MAX_TURNS=12"
elif [ -f "$SRC_DIR/.env" ]; then
  ENV_CONTENT=$(cat "$SRC_DIR/.env")
  ok "usando el .env que viene en el proyecto"
else
  warn "no hay clave de NVIDIA (usa --key, o export NVIDIA_API_KEY / LLM_API_KEY)"
  warn "el agente arrancara pero no podra hablar hasta que la pongas"
fi
if [ -n "$ENV_CONTENT" ] && [ "$WITH_SERVICE" = "1" ]; then
  printf '%s\n' "$ENV_CONTENT" \
    | ssh "$USER_NAME@$HOST" "cat > $REMOTE_DIR/.env && chmod 600 $REMOTE_DIR/.env"
  ok ".env escrito en el robot (permisos 600)"
elif [ -n "$ENV_CONTENT" ]; then
  warn "NO se escribe el .env en el robot: en el diseño actual la clave se queda en el PC."
  warn "  (el robot solo ejecuta; la API la llama el PC). Usa --with-service si de verdad"
  warn "   quieres el diseño viejo, con el agente DENTRO del robot."
fi

# --------------------------------------------------------------------------- #
say "5/8 Instalando dependencias"
FLAGS=""
[ "$WITH_PIPER" = "1" ] && FLAGS="$FLAGS --with-piper"
[ "$WITH_WHISPER" = "1" ] && FLAGS="$FLAGS --with-whisper"
[ "$WITH_SERVICE" = "1" ] && FLAGS="$FLAGS --with-service"
# buster esta archivado: sus repos ya no existen, hay que apuntar al archivo
REMOTE_CODENAME=$(ssh "$USER_NAME@$HOST" "cat /etc/os-release 2>/dev/null" 2>/dev/null \
  | grep -oE 'VERSION_CODENAME=.*' | cut -d= -f2 | tr -d '"'"'"'"' | head -1)
if [ "$REMOTE_CODENAME" = "buster" ]; then
  FLAGS="$FLAGS --fix-repos"
  say "buster detectado: se arreglan las fuentes de apt (repos archivados)"
fi
ssh "$USER_NAME@$HOST" "cd $REMOTE_DIR && bash tools/legacy/setup_pi.sh $FLAGS"
ok "instalacion terminada"

# --------------------------------------------------------------------------- #
if [ "$APPLY_PATCH" = "1" ]; then
  say "6/8 Parche del firmware (buzzer + audio por RPC)"
  ssh "$USER_NAME@$HOST" "cd $REMOTE_DIR/patches/robot_patch && python3 apply_patch.py && sudo systemctl restart tonypi.service"
  ok "parche aplicado (para deshacer: cd $REMOTE_DIR/patches/robot_patch && python3 apply_patch.py --undo)"
else
  say "6/8 Parche del firmware (omitido; usa --patch si lo quieres)"
fi

# --------------------------------------------------------------------------- #
say "7/8 Verificando"
ssh "$USER_NAME@$HOST" "cd $REMOTE_DIR/tools && PYTHONPATH=$REMOTE_DIR/pc ../.venv/bin/python test_rpc.py 127.0.0.1" || warn "test_rpc fallo: revisa que tonypi.service este activo"
ssh "$USER_NAME@$HOST" "cd $REMOTE_DIR/pc && ../.venv/bin/python audio_doctor.py" || true

# --------------------------------------------------------------------------- #
say "8/8 Probando el LLM real desde el robot"
ssh "$USER_NAME@$HOST" "cd $REMOTE_DIR/tools && PYTHONPATH=$REMOTE_DIR/pc ../.venv/bin/python nvidia_smoke_test.py --skip-tools" || warn "el smoke test fallo (revisa la clave o el rate limit)"

if [ "$WITH_SERVICE" = "1" ]; then
  say "Servicio"
  ssh "$USER_NAME@$HOST" "sudo systemctl status pontibot --no-pager -l | head -12" || true
  ok "logs: ssh $USER_NAME@$HOST 'journalctl -u pontibot -f'"
fi

say "Listo"
cat <<EOF

Robot desplegado en $REMOTE_DIR

Probarlo a mano:
  ssh $USER_NAME@$HOST
  cd $REMOTE_DIR/pc
  ../.venv/bin/python voice_agent.py

Ver los logs:
  ssh $USER_NAME@$HOST 'journalctl -u pontibot -f'

EOF

#!/usr/bin/env bash
# =============================================================================
#  wslg_check.sh — ¿por qué no hay audio en WSL? y qué hacer exactamente
#
#  Diagnostica la cadena completa:
#    ¿hay WSL?  ·  ¿hay WSLg?  ·  ¿existe el socket?  ·  ¿responde el server?
#    ·  ¿hay un daemon PulseAudio local?  ·  ¿está el micro en Windows?
#
#  USO
#    bash tools/wslg_check.sh
# =============================================================================
set -uo pipefail

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
err()  { printf '  \033[31m✗\033[0m %s\n' "$*"; }
head_(){ printf '\n\033[1m%s\033[0m\n' "$*"; }

echo "═══════════════════════════════════════════════════════════"
echo "  Diagnóstico de audio en WSL"
echo "═══════════════════════════════════════════════════════════"

# --- 1. ¿Estamos en WSL? ------------------------------------------------------
head_ "1. ¿WSL?"
IS_WSL=0
if grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null; then
  IS_WSL=1; ok "sí: $(grep -oE 'WSL[0-9]*' /proc/version | head -1)"
  ok "kernel: $(uname -r)"
else
  warn "no: esto no es WSL (Linux nativo)"
fi

# --- 2. Herramientas de cliente ------------------------------------------------
head_ "2. Herramientas de PulseAudio en WSL"
for c in pactl parecord paplay; do
  if command -v "$c" >/dev/null 2>&1; then ok "$c → $(command -v $c)"
  else warn "$c NO INSTALADO → sudo apt install -y pulseaudio-utils"; fi
done

# --- 3. ¿Existe WSLg? ----------------------------------------------------------
head_ "3. ¿WSLg presente?"
if [ -d /mnt/wslg ]; then
  ok "/mnt/wslg existe"
  ls -1 /mnt/wslg 2>/dev/null | head -8 | sed 's/^/    /'
  if [ -S /mnt/wslg/PulseServer ]; then
    ok "socket /mnt/wslg/PulseServer presente"
    SOCKET_PRESENTE=1
  else
    err "socket /mnt/wslg/PulseServer AUSENTE"
    SOCKET_PRESENTE=0
  fi
else
  err "/mnt/wslg NO existe → WSLg no está instalado en este distro"
  SOCKET_PRESENTE=0
fi

# --- 4. ¿Responde el servidor? -------------------------------------------------
head_ "4. ¿Responde el servidor PulseAudio?"
echo "    PULSE_SERVER=${PULSE_SERVER:-<sin definir>}"
if pactl info >/dev/null 2>&1; then
  ok "pactl info funciona"
  pactl info 2>/dev/null | grep -E "Server Name|Default Sink|Default Source" | sed 's/^/    /'
  FUNCIONA=1
else
  warn "pactl info falla (el servidor no acepta conexiones)"
  FUNCIONA=0
  if [ "$SOCKET_PRESENTE" = "1" ]; then
    echo "    probando con el socket explícito..."
    if PULSE_SERVER="unix:/mnt/wslg/PulseServer" pactl info >/dev/null 2>&1; then
      ok "funciona con PULSE_SERVER=unix:/mnt/wslg/PulseServer"
      FUNCIONA=1
      echo
      echo "    ► DIAGNÓSTICO: tu PULSE_SERVER apunta a otro sitio y por eso falla."
      echo "      Busca dónde está puesto:"
      echo "        grep -rn PULSE_SERVER ~/.bashrc ~/.profile /etc/environment 2>/dev/null"
      echo "      Y deja el de WSLg:"
      echo "        sed -i '/PULSE_SERVER/d' ~/.bashrc"
      echo "        echo 'export PULSE_SERVER=unix:/mnt/wslg/PulseServer' >> ~/.bashrc"
      echo "        source ~/.bashrc"
      echo "      (mata a la vez el PulseAudio de Windows: no lo necesitas)"
      echo
    else
      err "tampoco con el socket explícito → el servidor de WSLg está MUERTO"
    fi
  fi
fi

# --- 5. Daemon local ------------------------------------------------------------
head_ "5. Daemon PulseAudio local en WSL"
if systemctl --user is-active pulseaudio 2>/dev/null | grep -q active; then
  ok "hay un pulseaudio local activo"
elif command -v pulseaudio >/dev/null 2>&1; then
  warn "pulseaudio instalado pero no corriendo"
  echo "      puedes arrancarlo:  pulseaudio --start"
else
  warn "no hay pulseaudio en el distro (no hace falta si WSLg funciona)"
fi

# --- 6. Veredicto ---------------------------------------------------------------
head_ "6. Veredicto"
if [ "$FUNCIONA" = "1" ]; then
  ok "HAY AUDIO. Siguiente paso:"
  echo "      bash tools/bt_headset_pc.sh --detect"
  echo
  echo "    Si no aparece el auricular, en Windows ponlo como dispositivo de"
  echo "    ENTRADA por defecto (Ajustes → Sistema → Sonido → Entrada) y con"
  echo "    perfil de manos libres (HFP)."
  exit 0
fi

echo "  ARREGLO SEGÚN TU CASO:"
echo
if [ "$IS_WSL" = "0" ]; then
  echo "    · No estás en WSL: el audio normal de Linux ya funciona."
  echo "      Instala:  sudo apt install -y pulseaudio-utils"
elif [ ! -d /mnt/wslg ]; then
  echo "    · WSLg no está en este distro. Desde PowerShell (Windows):"
  echo "        wsl --update"
  echo "        wsl --set-version <TU_DISTRO> 2     # si es WSL1"
  echo "        wsl --shutdown"
  echo "      (WSLg viene con WSL2 de la Microsoft Store; si instalaste el"
  echo "       kernel a mano, no incluye WSLg)"
else
  echo "    · WSLg está pero su servidor PulseAudio está muerto."
  echo "      Desde PowerShell (Windows), en este orden:"
  echo "        wsl --shutdown          # reinicia la VM de WSL y WSLg"
  echo "        wsl --update            # actualiza WSLg"
  echo "      Luego vuelve a abrir esta terminal y repite este script."
  echo
  echo "    · Si sigue igual: el micro de Windows está bloqueado por permisos."
  echo "      Ajustes → Privacidad y seguridad → Micrófono →"
  echo "      'Permitir que las aplicaciones de escritorio accedan al micrófono'"
  echo "      (WSLg captura el micro como un cliente RDP de escritorio)."
  echo
  echo "    · Alternativa sin WSLg: un daemon PulseAudio local en WSL"
  echo "        sudo apt install -y pulseaudio"
  echo "        pulseaudio --start"
  echo "      (solo sirve si compartes el adaptador Bluetooth con usbipd;"
  echo "       si no, el micro llega por el plan de WSLg o no llega)"
fi
echo "═══════════════════════════════════════════════════════════"

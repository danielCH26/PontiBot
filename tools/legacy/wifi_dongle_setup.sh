#!/usr/bin/env bash
# TonyPi · Módulo Wi-Fi USB
# Diagnóstico, driver y puesta en la red del robot.
#
# En el robot:
#   ./wifi_dongle_setup.sh diagnose
#   ./wifi_dongle_setup.sh disable-onboard
#   ./wifi_dongle_setup.sh install-driver
#   ./wifi_dongle_setup.sh sta --ssid MI_WIFI --pass MI_PASS
#   ./wifi_dongle_setup.sh ap
#   ./wifi_dongle_setup.sh verify
#
# Desde el PC (por SSH, copia el script al robot y lo ejecuta):
#   ./wifi_dongle_setup.sh --host 192.168.149.1 diagnose
#   ./wifi_dongle_setup.sh --host 192.168.149.1 sta --ssid MI_WIFI --pass MI_PASS

set -uo pipefail

HOST=""
CMD=""
SSID=""
PASS=""
USER_NAME="${TONYPI_USER:-pi}"

die()  { echo "!!  $*" >&2; exit 1; }
info() { echo "  $*"; }
ok()   { echo "OK $*"; }
warn() { echo "!!  $*"; }

# ─────────────────────────── argumentos ───────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --user) USER_NAME="$2"; shift 2 ;;
    --ssid) SSID="$2"; shift 2 ;;
    --pass|--password) PASS="$2"; shift 2 ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) CMD="$1"; shift ;;
  esac
done
[[ -n "$CMD" ]] || { sed -n '2,18p' "$0"; exit 1; }

# ─────────────────────────── modo remoto ───────────────────────────
if [[ -n "$HOST" ]]; then
  echo "==> Conectando por SSH a $USER_NAME@$HOST"
  ssh -o ConnectTimeout=10 "$USER_NAME@$HOST" true 2>/dev/null \
    || die "no responde por SSH. Conéctate al hotspot HW... y usa $USER_NAME@192.168.149.1"
  scp -q "$0" "$USER_NAME@$HOST:/tmp/wifi_dongle_setup.sh" || die "fallo al copiar"
  REMOTE_ARGS="'$CMD'"
  [[ -n "$SSID" ]] && REMOTE_ARGS="$REMOTE_ARGS --ssid '$SSID'"
  [[ -n "$PASS" ]] && REMOTE_ARGS="$REMOTE_ARGS --pass '$PASS'"
  echo "==> Ejecutando en el robot: $REMOTE_ARGS"
  exec ssh -t "$USER_NAME@$HOST" "bash /tmp/wifi_dongle_setup.sh $REMOTE_ARGS"
fi

# ─────────────────────────── utilidades ───────────────────────────
as_root() { if [[ $EUID -eq 0 ]]; then "$@"; else sudo "$@"; fi; }

pi_model() {
  if [[ -r /proc/device-tree/model ]]; then
    tr -d '\0' < /proc/device-tree/model 2>/dev/null | sed 's/Raspberry Pi //' | cut -d, -f1
  else
    echo "?"
  fi
}

config_txt() {
  for f in /boot/firmware/config.txt /boot/config.txt; do
    [[ -f "$f" ]] && { echo "$f"; return; }
  done
}

# Interfaces inalámbricas reales (ignora lo virtual)
wifi_ifaces() {
  iw dev 2>/dev/null | awk '/^Interface /{print $2}'
}

# USB-ID del adaptador -> nombre del chip
chip_of() {
  local id="$1" name
  name=$(lsusb 2>/dev/null | awk -v id="$id" 'tolower($6)==id {print $0}')
  case "$id" in
    0bda:8812) echo "Realtek RTL8812AU" ;;
    0bda:881a) echo "Realtek RTL8811AU" ;;
    0bda:881b) echo "Realtek RTL8812BU" ;;
    0bda:8814) echo "Realtek RTL8814AU" ;;
    0bda:8821) echo "Realtek RTL8821AU" ;;
    0bda:8822) echo "Realtek RTL8822BU" ;;
    0bda:013c) echo "Realtek RTL8188ETV" ;;
    0bda:*)    echo "Realtek ($id) — revisar" ;;
    1487:7602|1487:7603) echo "MediaTek MT7612U" ;;
    1487:7610) echo "MediaTek MT7610U" ;;
    1487:760a) echo "MediaTek MT7601U" ;;
    0cf3:9271|0e0c:0001) echo "Atheros AR9271" ;;
    2357:010c) echo "TP-Link Archer (MT7610U)" ;;
    2357:010e) echo "TP-Link Archer (MT7612U)" ;;
    *) echo "desconocido ($id)" ;;
  esac
}

# ─────────────────────────── diagnose ───────────────────────────
do_diagnose() {
  echo "=== DIAGNÓSTICO DEL MÓDULO WI-FI ==="
  echo "Fecha      : $(date -Is)"
  echo "Modelo Pi  : $(pi_model)"
  echo "Kernel     : $(uname -r)"
  echo "OS         : $(grep -h PRETTY_NAME /etc/os-release 2>/dev/null | cut -d'"' -f2)"
  echo

  echo "-- USB conectado --"
  if command -v lsusb >/dev/null; then
    lsusb | sed 's/^/  /'
  else
    echo "  (lsusb no instalado: sudo apt install usbutils)"
  fi
  echo

  echo "-- Interfaces de red --"
  if command -v ip >/dev/null; then
    ip -br link 2>/dev/null | sed 's/^/  /' || echo "  (sin interfaces)"
  else
    echo "  (ip no instalado)"
  fi
  echo

  echo "-- Interfaces inalámbricas (iw dev) --"
  local ifs
  ifs=$(wifi_ifaces)
  if [[ -n "$ifs" ]]; then
    echo "$ifs" | sed 's/^/  /'
    echo "  => el kernel YA reconoce un adaptador Wi-Fi."
  else
    echo "  (ninguna)"
    echo "  => si el módulo está enchufado, falta el driver."
  fi
  echo

  echo "-- Módulos Realtek/MT76/rtw88 cargados --"
  lsmod 2>/dev/null | grep -iE '88x2|rtw88|mt76|rtl8|brcmfmac|ath9k' | sed 's/^/  /' || echo "  (ninguno)"
  echo

  echo "-- ¿El integrado (brcmfmac) sigue presente? --"
  if lsmod 2>/dev/null | grep -q brcmfmac; then
    echo "  SI -> el Wi-Fi de la Pi sigue activo."
    echo "       Para que el módulo USB lo sustituyas:  ./wifi_dongle_setup.sh disable-onboard"
  else
    echo "  NO -> el Wi-Fi integrado no está cargado."
    echo "       En una Raspberry Pi eso significa que ya está desactivado: perfecto,"
    echo "       el módulo USB es el único wlan0."
  fi
  echo

  echo "-- Reinicios de USB (falla de alimentación) --"
  dmesg 2>/dev/null | grep -iE 'reset (high )?speed USB|over-current|device descriptor read' | tail -5 | sed 's/^/  /' \
    || echo "  (ninguno)"
  echo

  echo "-- Gestor de red --"
  if command -v nmcli >/dev/null; then
    echo "  NetworkManager: $(systemctl is-active NetworkManager 2>/dev/null)"
  else
    echo "  (sin NetworkManager)"
  fi
  for s in wifi.service hw_wifi.service; do
    if systemctl list-unit-files 2>/dev/null | grep -q "^$s"; then
      echo "  $s: $(systemctl is-active "$s" 2>/dev/null)"
    fi
  done
  echo

  echo "-- Configuración de Hiwonder --"
  local conf="$HOME/hiwonder-toolbox/wifi_conf.py"
  if [[ -f "$conf" ]]; then
    echo "  $conf"
    grep -nE '^\s*#?\s*HW_WIFI_(MODE|STA_SSID|AP_SSID)' "$conf" | sed 's/^/    /' \
      || echo "    (sin líneas HW_WIFI_)"
  else
    echo "  (no encontrado $conf)"
  fi
  echo

  echo "-- IP y rutas --"
  ip -4 -br addr show 2>/dev/null | sed 's/^/  /'
  ip route 2>/dev/null | sed 's/^/  /'
  echo

  echo "-- Conectividad --"
  if ping -c 2 -W 3 1.1.1.1 >/dev/null 2>&1; then
    ok "hay salida a internet (ping 1.1.1.1)"
  else
    warn "SIN internet por ping (normal en modo AP)"
  fi
  local code
  code=$(curl -s -o /dev/null -m 12 -w '%{http_code}' https://integrate.api.nvidia.com/v1/models 2>/dev/null)
  if [[ "$code" == "200" ]]; then
    ok "NVIDIA NIM accesible (HTTP 200)"
  else
    warn "NVIDIA NIM no accesible (HTTP ${code:-sin respuesta})"
  fi
}

# ─────────────────── disable-onboard (el USB toma wlan0) ───────────────────
do_disable_onboard() {
  echo "=== DESACTIVANDO EL WI-FI INTEGRADO ==="
  local cfg; cfg=$(config_txt)
  [[ -n "$cfg" ]] || die "no encuentro config.txt"

  local model; model=$(pi_model)
  local overlay="dtoverlay=disable-wifi"
  [[ "$model" == 5* ]] && overlay="dtoverlay=disable-wifi-pi5"

  if ! grep -q '^dtoverlay=disable-wifi' "$cfg"; then
    printf '\n# TonyPi: el modulo Wi-Fi USB sustituye al integrado\n%s\n' "$overlay" >> "$cfg"
    ok "añadido '$overlay' a $cfg"
  else
    info "'$overlay' ya estaba en $cfg"
  fi

  # Red de seguridad a nivel de modulo (funciona aunque el overlay no aplique)
  local mk=/etc/modprobe.d/blacklist-brcmfmac.conf
  if [[ ! -f "$mk" ]] || ! grep -q brcmfmac "$mk" 2>/dev/null; then
    as_root tee "$mk" >/dev/null <<'EOF'
# TonyPi: el modulo Wi-Fi USB sustituye al integrado de la Raspberry Pi
blacklist brcmfmac
blacklist brcmutil
EOF
    ok "blacklist creado: $mk"
  else
    info "blacklist ya presente"
  fi

  echo
  warn "NO se toca el Bluetooth: el audio del robot (WonderEcho) lo necesita."
  echo
  echo "Reinicia para que el modulo USB reclame wlan0:"
  echo "  sudo reboot"
  echo
  echo "Despues comprueba que el USB es wlan0:"
  echo "  iw dev"
  echo "Y si no aparece, el driver falta -> install-driver (necesita internet)."
}

# ─────────────────────────── install-driver ───────────────────────────
do_install_driver() {
  echo "=== INSTALANDO DRIVER (necesita internet) ==="
  if ! ping -c 2 -W 3 1.1.1.1 >/dev/null 2>&1; then
    die "el robot no tiene internet. Conecta un cable Ethernet al router (el TonyPi tiene RJ45) y reintenta."
  fi
  ok "hay internet"

  echo "-- chipsets USB detectados --"
  lsusb | grep -iE 'realtek|0bda|mediatek|atheros|ralink|ralink|mediatek' | sed 's/^/  /' || echo "  (ninguno Realtek/MT76/ATHD)"

  echo
  echo "Instalando prerequisites..."
  as_root apt-get update -qq >/dev/null 2>&1
  as_root apt-get install -y -qq raspberrypi-kernel-headers build-essential bc git dkms >/dev/null 2>&1 \
    || die "fallo instalando prerequisites"
  ok "prerequisites listos"

  echo
  echo "Descargando driver rtw88 (cubre 8811AU/8812AU/8814AU/8821AU/8812BU/8822BU...)..."
  rm -rf /tmp/rtw88
  git clone --depth 1 https://github.com/lwfinger/rtw88.git /tmp/rtw88 2>&1 | tail -2 | sed 's/^/  /' \
    || die "fallo al clonar (¿internet?)"

  echo "Compilando e instalando via DKMS (puede tardar varios minutos)..."
  ( cd /tmp/rtw88 && as_root dkms install -m rtw88 -v 5.15.0 "$PWD" ) 2>&1 | tail -8 | sed 's/^/  /' \
    || warn "DKMS devolvio error; revisa el log /var/lib/dkms/"
  ( cd /tmp/rtw88 && as_root make install_fw ) 2>&1 | tail -3 | sed 's/^/  /' \
    || warn "no se pudo instalar el firmware"
  as_root cp /tmp/rtw88/rtw88.conf /etc/modprobe.d/ 2>/dev/null && ok "rtw88.conf copiado (blacklist de rtw88 in-tree)"

  echo
  echo "Reinicia y comprueba:"
  echo "  sudo reboot && iw dev"
}

# ─────────────────────────── sta / ap ───────────────────────────
write_wifi_conf() {
  local mode="$1"
  local conf="$HOME/hiwonder-toolbox/wifi_conf.py"
  [[ -f "$conf" ]] || die "no encuentro $conf"

  python3 - "$conf" "$mode" "$SSID" "$PASS" <<'PY'
import re, sys, pathlib
conf, mode, ssid, pw = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
p = pathlib.Path(conf)
src = p.read_text(encoding="utf-8", errors="replace")

keys = ("HW_WIFI_MODE", "HW_WIFI_STA_SSID", "HW_WIFI_STA_PASSWORD")
out = []
for line in src.splitlines():
    m = re.match(r"^(\s*)(HW_WIFI_(?:MODE|STA_SSID|STA_PASSWORD))\s*=", line)
    if m:
        out.append(m.group(1) + "# " + m.group(2) + " = (gestionado por wifi_dongle_setup.sh)")
    else:
        out.append(line)

block = []
if mode == "2":
    block += ["", "# --- TonyPi: modo LAN/STA con el modulo Wi-Fi USB ---",
              "HW_WIFI_MODE = 2",
              "HW_WIFI_STA_SSID = " + repr(ssid),
              "HW_WIFI_STA_PASSWORD = " + repr(pw)]
p.write_text("\n".join(out + block) + "\n", encoding="utf-8")
print("  escrito:", conf)
for l in block:
    if l.strip() and not l.startswith("#"):
        print("   ", l.split(" = ")[0], "=", l.split(" = ", 1)[1] if " = " in l else "")
PY
}

do_sta() {
  [[ -n "$SSID" ]] || die "falta --ssid"
  echo "=== MODO LAN/STA (el robot entra en tu Wi-Fi) ==="
  write_wifi_conf 2
  echo
  echo "Reiniciando el servicio de Wi-Fi..."
  as_root systemctl restart wifi.service 2>/dev/null || warn "wifi.service no reinició"
  as_root systemctl restart hw_wifi.service 2>/dev/null || true
  sleep 12
  echo
  do_verify
  echo
  warn "Si tu sesion SSH se ha caido, el robot ya esta en tu red: conéctate a la IP nueva."
}

do_ap() {
  echo "=== MODO AP (hotspot propio del robot) ==="
  write_wifi_conf 1
  as_root systemctl restart hw_wifi.service 2>/dev/null || as_root systemctl restart wifi.service 2>/dev/null
  sleep 8
  echo "Hotspotshould ser 'HW...' (contraseña 'hiwonder'), IP 192.168.149.1"
  echo "MODO AP = SIN internet. Para el LLM necesitas modo STA."
}

# ─────────────────────────── verify ───────────────────────────
do_verify() {
  echo "=== VERIFICACIÓN ==="
  echo "-- interfaces --"
  wifi_ifaces | sed 's/^/  /'
  ip -br addr 2>/dev/null | sed 's/^/  /'
  echo
  echo "-- ruta por defecto --"
  ip route show default 2>/dev/null | sed 's/^/  /' || echo "  (sin ruta por defecto)"
  echo
  if ping -c 3 -W 3 1.1.1.1 >/dev/null 2>&1; then
    ok "internet (ping 1.1.1.1)"
  else
    warn "sin salida a internet"
  fi
  local code
  code=$(curl -s -o /dev/null -m 12 -w '%{http_code}' https://integrate.api.nvidia.com/v1/models 2>/dev/null)
  if [[ "$code" == "200" ]]; then
    ok "NVIDIA NIM accesible (HTTP 200) -> el LLM puede funcionar"
  else
    warn "NVIDIA NIM no accesible (HTTP ${code:-sin respuesta})"
  fi
  echo
  echo "Tu PC debe poder alcanzar el robot en esta IP:"
  ip -4 -br addr show 2>/dev/null | awk '$1!="lo" {print "  " $1, $3}'
}

# ─────────────────────────── dispatch ───────────────────────────
case "$CMD" in
  diagnose)        do_diagnose ;;
  disable-onboard) do_disable_onboard ;;
  install-driver)  do_install_driver ;;
  sta)             do_sta ;;
  ap)              do_ap ;;
  verify)          do_verify ;;
  *)
    echo "Comandos: diagnose | disable-onboard | install-driver | sta | ap | verify" >&2
    exit 1 ;;
esac

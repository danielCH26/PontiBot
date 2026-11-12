#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════════
#  TonyPi · tonypi_wifi.sh
#  Gestión de la red del robot (Hiwonder TonyPi · Ubuntu 20.04 · Pi 4B/5)
#
#  USO
#    bash tonypi_wifi.sh probe                        # diagnóstico (solo lectura)
#    bash tonypi_wifi.sh sta --ssid "RED" --pass "CLAVE"   # entrar en tu router
#    bash tonypi_wifi.sh sta --mode 3 --ssid "RED"    # AP + internet por cable
#    bash tonypi_wifi.sh ap                           # volver al hotspot propio
#    bash tonypi_wifi.sh status                       # resumen rápido
#    bash tonypi_wifi.sh find-ip                     # localizar el robot en la red
#    bash tonypi_wifi.sh cancel-watchdog              # cancelar la vuelta atrás auto.
#
#  MODOS (HW_WIFI_MODE del firmware de Hiwonder)
#    1 = AP puro (hotspot, sin internet)   ← estado inicial del robot
#    2 = cliente WiFi: entra en tu router, pide IP por DHCP, tiene internet
#    3 = AP + comparte el internet que le llega por el cable eth0
#        (mantiene el hotspot Y tiene internet: el VNC nunca se cae)
#
#  DESDE TU PC, POR SSH (no hace falta copiar nada al robot):
#    bash tonypi_wifi.sh --host 192.168.149.1 probe
#    bash tonypi_wifi.sh --host 192.168.149.1 sta --ssid "RED" --pass "CLAVE"
#
#  POR QUÉ ESTE SCRIPT
#    El robot arranca en MODO AP: crea su propio hotspot ("HW...") y en ese
#    modo NO tiene internet (lo confirma la doc de Hiwonder). Además, su WiFi
#    tiene configuración propia: los ajustes de red del escritorio NO sirven.
#    La única vía soportada es editar ~/hiwonder-toolbox/wifi_conf.py
#    (HW_WIFI_MODE = 2 + SSID + contraseña) y reiniciar el servicio.
#
#  SEGURIDAD
#    Al pasar a modo STA se guarda copia de la configuración y se lanza un
#    vigilante: si en N segundos el robot no tiene IP de LAN, se restaura el
#    modo AP automáticamente (así no pierdes el acceso al robot).
#    Escape físico: botón KEY1 de la placa, mantener pulsado hasta que
#    parpadee el LED azul → vuelve a modo AP.
# ════════════════════════════════════════════════════════════════════════

set -uo pipefail

# Si la sesión SSH se cae (porque el robot cambia de red), el proceso NO debe
# morir: tiene que terminar la comprobacion y dejar el resultado en el log.
trap '' HUP

# ─────────────────────────────── rutas ───────────────────────────────
CONF_DIR="$HOME/hiwonder-toolbox"
BACKUP_DIR="$HOME/tonypi_wifi_backup"
WATCHDOG_SCRIPT="$HOME/tonypi_wifi_watchdog.sh"
WATCHDOG_PID="$HOME/tonypi_wifi_watchdog.pid"
RESULT_LOG="$HOME/tonypi_wifi_result.log"
DEFAULT_WATCHDOG_DELAY=180

# ─────────────────────────────── color ───────────────────────────────
if [ -t 1 ]; then
  R=$'\033[31m'; G=$'\033[32m'; Y=$'\033[33m'; C=$'\033[36m'; B=$'\033[1m'; D=$'\033[2m'; N=$'\033[0m'
else
  R=''; G=''; Y=''; C=''; B=''; D=''; N=''
fi

sec()  { printf '\n%s%s== %s ==%s\n' "$C$B" "$C" "$*" "$N"; }
say()  { printf '\n%s%s%s\n' "$B" "$*" "$N"; }
ok()   { printf '%s  [OK]    %s%s\n' "$G" "$*" "$N"; }
bad()  { printf '%s  [FALLO] %s%s\n' "$R" "$*" "$N"; }
warn() { printf '%s  [AVISO] %s%s\n' "$Y" "$*" "$N"; }
note() { printf '         %s%s%s\n' "$D" "$*" "$N"; }
die()  { printf '%s  [ERROR] %s%s\n' "$R" "$*" "$N"; exit 1; }

has() { command -v "$1" >/dev/null 2>&1; }

# ─────────────────────────────── utilidades ────────────────────────────
# Primera interfaz WiFi real del sistema
wifi_iface() {
  local ifs
  ifs=$(iw dev 2>/dev/null | awk '/^Interface /{print $2}')
  [ -n "$ifs" ] && { echo "$ifs" | head -1; return; }
  ip -o link show 2>/dev/null | awk -F': ' '{print $2}' | grep -E '^(wlan|wlp)' | head -1
}

# ¿Está la interfaz en modo punto de acceso (hotspot)?
iface_is_ap() {
  local iface="$1"
  [ -n "$iface" ] || return 1
  iw dev "$iface" info 2>/dev/null | grep -q 'type.*AP'
}

# IPv4 asignadas a una interfaz (sin /prefijo)
iface_ips() {
  local iface="$1"
  ip -4 -o addr show "$iface" 2>/dev/null | awk '{print $4}' | cut -d/ -f1
}

default_gw() { ip route 2>/dev/null | awk '/^default/{print $3; exit}'; }
default_dev() { ip route 2>/dev/null | awk '/^default/{print $5; exit}'; }

# Ficheros de configuración de Hiwonder que contienen el modo WiFi
conf_files() {
  local f
  for f in "$CONF_DIR"/wifi_conf.py "$CONF_DIR"/hw_wifi.py "$CONF_DIR"/wifi.py; do
    [ -f "$f" ] && grep -q 'HW_WIFI_MODE' "$f" 2>/dev/null && echo "$f"
  done
  # barrido extra: cualquier .py del toolbox con HW_WIFI_MODE
  for f in "$CONF_DIR"/*.py; do
    [ -f "$f" ] || continue
    case "$f" in
      */wifi_conf.py|*/hw_wifi.py|*/wifi.py) continue ;;
    esac
    grep -q 'HW_WIFI_MODE' "$f" 2>/dev/null && echo "$f"
  done
}

# ¿Está el robot dentro del rango del hotspot propio (192.168.149.0/24)?
in_ap_range() {
  local ip
  for ip in $(ip -4 -o addr show 2>/dev/null | awk '{print $4}' | cut -d/ -f1); do
    case "$ip" in 192.168.149.*) echo "$ip"; return 0 ;; esac
  done
  return 1
}

has_internet() {
  curl -s -o /dev/null -m 12 -w '%{http_code}' https://integrate.api.nvidia.com/v1/models 2>/dev/null
}

mask_pw() { printf '%s' "$1" | sed -e 's/\(.\)/•/g' -e 's/^•\{0,3\}.\{0,3\}$/***/'; }

# ════════════════════════════════════════════════════════════════════
#  PROBE · diagnóstico completo (no cambia nada)
# ════════════════════════════════════════════════════════════════════
do_probe() {
  local iface ip gw code

  sec "1 · SISTEMA"
  note "modelo   : $(tr -d '\0' < /proc/device-tree/model 2>/dev/null || echo '?')"
  note "kernel   : $(uname -r)"
  note "os       : $(grep -h PRETTY_NAME /etc/os-release 2>/dev/null | cut -d'"' -f2)"
  note "host     : $(hostname)   usuario: $(whoami)"
  note "fecha    : $(date -Is)"

  sec "2 · INTERFACES Y RUTAS"
  if [ -n "$(ip -br addr 2>/dev/null)" ]; then
    ip -br addr 2>/dev/null | sed 's/^/  /'
  else
    ip addr 2>/dev/null | sed 's/^/  /'
  fi
  note ""
  ip route 2>/dev/null | sed 's/^/  /'
  iface=$(wifi_iface)
  gw=$(default_gw)
  if [ -z "$gw" ]; then
    bad "NO hay ruta por defecto (no hay salida a internet)."
  else
    ok "ruta por defecto -> $gw (vía $(default_dev))"
  fi

  sec "3 · MODO DE RED ACTUAL"
  local serial apssid
  serial=$(cat /proc/device-tree/serial-number 2>/dev/null | tr -d '\0')
  if [ -n "$serial" ]; then
    apssid="HW-$(printf '%s' "$serial" | cut -c1-8)"
    note "hotspot del robot : $apssid   (contraseña: hiwonder)"
    note "                  el firmware usa 'HW-' + los 8 primeros del serial"
  else
    note "hotspot del robot : HW-<serial del robot>   (contraseña: hiwonder)"
  fi
  if in_ap_range >/dev/null; then
    ok "el robot está en MODO AP (hotspot propio $(in_ap_range))"
    note "en este modo el robot NO tiene internet, aunque tenga IP."
    note "si tu VNC entra por esta IP, al pasar a modo LAN se caerá la sesión."
  else
    ok "el robot NO está en el rango del hotspot propio (192.168.149.0/24)"
  fi
  if [ -n "$iface" ] && iface_is_ap "$iface"; then
    ok "$iface está configurada como punto de acceso (AP)"
  elif [ -n "$iface" ]; then
    ok "$iface está en modo cliente (STA)"
  else
    warn "no hay ninguna interfaz WiFi activa"
  fi

  sec "4 · HARDWARE WI-FI"
  if has lsusb; then
    local usb
    usb=$(lsusb 2>/dev/null)
    note "USB conectado:"
    echo "$usb" | sed 's/^/    /'
    if echo "$usb" | grep -qiE '0bda:|realtek|mediatek|atheros|ralink|mt76|8812|8821|8822'; then
      ok "hay un adaptador WiFi USB conectado"
      echo "$usb" | grep -iE '0bda:|realtek|mediatek|atheros|ralink' | sed 's/^/    chip: /'
    fi
  fi
  note ""
  if lsmod 2>/dev/null | grep -q '^brcmfmac'; then
    ok "brcmfmac CARGADO -> el WiFi INTEGRADO de la Pi está disponible"
  else
    warn "brcmfmac NO cargado -> el WiFi integrado está desactivado"
  fi
  local cfg
  for cfg in /boot/firmware/config.txt /boot/config.txt; do
    if [ -f "$cfg" ]; then
      if grep -q 'dtoverlay=disable-wifi' "$cfg" 2>/dev/null; then
        bad "$cfg tiene 'dtoverlay=disable-wifi' (integrado apagado a propósito)"
        note "si el USB no tiene driver, la opción es QUITAR esa línea y rebootar."
      else
        ok "$cfg sin 'dtoverlay=disable-wifi' (integrado habilitado)"
      fi
    fi
  done
  for f in /etc/modprobe.d/*.conf; do
    [ -f "$f" ] || continue
    grep -q 'blacklist brcmfmac' "$f" 2>/dev/null && \
      warn "$f tiene 'blacklist brcmfmac'"
  done

  sec "5 · INTERFACES INALÁMBRICAS (iw dev)"
  if has iw; then
    iw dev 2>/dev/null | sed 's/^/  /'
  else
    note "(iw no instalado)"
  fi
  if has rfkill; then
    note "rfkill:"
    rfkill list 2>/dev/null | sed 's/^/    /'
  fi

  sec "6 · REDES WI-FI VISIBLES"
  if has nmcli; then
    local scan
    scan=$(nmcli -t -f SSID,BANDSIGNAL,SECURITY device wifi list --rescan yes 2>/dev/null)
    if [ -n "$scan" ]; then
      echo "$scan" | sed 's/^/  /'
      ok "$(echo "$scan" | grep -c ':') redes visibles"
    else
      warn "nmcli no ve redes (puede que el radio esté en modo AP o apagado)"
    fi
  else
    note "(sin nmcli: la imagen de Hiwonder gestiona el WiFi con sus scripts)"
  fi

  sec "7 · SERVICIOS DE HIWONDER"
  local s
  for s in wifi.service hw_wifi.service NetworkManager.service; do
    if systemctl list-unit-files 2>/dev/null | grep -q "^${s}"; then
      note "$(printf '%-22s' "$s") activo: $(systemctl is-active "$s" 2>/dev/null)  |  arranque: $(systemctl is-enabled "$s" 2>/dev/null)"
    fi
  done
  if systemctl list-unit-files 2>/dev/null | grep -q '^wifi.service'; then
    note "→ para pasar a modo LAN/STA:  sudo systemctl restart wifi.service"
  fi
  if systemctl list-unit-files 2>/dev/null | grep -q '^hw_wifi.service'; then
    note "→ para volver al hotspot:      sudo systemctl restart hw_wifi.service"
  fi

  sec "8 · CONFIGURACIÓN DE HIWONDER"
  local cf
  cf=$(conf_files)
  if [ -n "$cf" ]; then
    for f in $cf; do
      note "$f:"
      grep -nE '^\s*#?\s*HW_WIFI_(MODE|STA_SSID|STA_PASSWORD|AP_SSID|AP_GATEWAY)' "$f" 2>/dev/null \
        | sed -E 's/(PASSWORD\s*=\s*).*/\1'"'"'***'"'"'/' | sed 's/^/    /'
    done
  else
    warn "no encuentro ningún fichero con HW_WIFI_MODE en $CONF_DIR"
    note "mira dónde está el toolbox:  find / -name 'wifi_conf.py' 2>/dev/null"
  fi

  sec "9 · CABLE DE RED (eth0)"
  if ip -br link show eth0 2>/dev/null; then
    if ip -br link show eth0 2>/dev/null | grep -q 'state UP'; then
      ok "eth0 tiene enlace (cable conectado)"
      note "IP eth0: $(iface_ips eth0 | tr '\n' ' ')"
    else
      warn "eth0 está ABAJO (sin cable, o cable sin enlace)"
    fi
  else
    note "no hay eth0"
  fi

  sec "10 · DNS E INTERNET"
  note "resolv.conf:"; sed 's/^/    /' /etc/resolv.conf 2>/dev/null | head -5
  if getent hosts integrate.api.nvidia.com >/dev/null 2>&1; then
    ok "el DNS resuelve integrate.api.nvidia.com"
  else
    bad "el DNS NO resuelve (puede ser solo DNS lo que falla)"
  fi
  if ping -c 2 -W 3 1.1.1.1 >/dev/null 2>&1; then
    ok "hay salida a internet (ping 1.1.1.1)"
  else
    warn "sin ping a 1.1.1.1 (puede estar bloqueado por el router; usa curl)"
  fi
  code=$(has_internet)
  if [ "$code" = "200" ]; then
    ok "API de NVIDIA accesible (HTTP 200) → INTERNET PLENO, el LLM puede funcionar"
  else
    bad "API de NVIDIA NO accesible (HTTP ${code:-sin respuesta})"
  fi

  # ── veredicto ──
  sec "VEREDICTO"
  local mode=""
  [ -n "$cf" ] && mode=$(grep -hE '^\s*HW_WIFI_MODE\s*=' $cf 2>/dev/null | head -1 | grep -oE '[0-9]+' | head -1)
  if [ "$code" = "200" ]; then
    ok "El robot YA tiene internet. No hay que cambiar nada."
    note "IP para el resto del proyecto:  $(hostname -I 2>/dev/null)"
  elif [ -z "$gw" ]; then
    if in_ap_range >/dev/null; then
      bad "El robot está en MODO AP (hotspot propio): por diseño NO tiene internet."
      printf '\n'
      note "OPCIÓN 1 (la que quieres) — entrar en tu router:"
      note "  bash tonypi_wifi.sh sta --ssid \"TU_RED\" --pass \"TU_CLAVE\""
      printf '\n'
      note "OPCIÓN 2 (la más rápida) — cable de red al router:"
      note "  enchufa el RJ45 del robot al router; luego:"
      note "  bash tonypi_wifi.sh status"
    else
      bad "Sin ruta por defecto: revisa el cable de red o el servicio de WiFi."
      note "  sudo systemctl restart wifi.service   # y vuelve a hacer probe"
    fi
  else
    bad "Hay ruta por defecto pero no sale internet: problema de DNS o del router."
    note "  ping $(default_gw)   # si falla, el router no le da salida"
    note "  nmcli dev show $(default_dev) | grep DNS   # revisa los DNS que le da el router"
  fi

  if [ -n "$iface" ] && lsmod 2>/dev/null | grep -q '^brcmfmac'; then
    printf '\n'
    ok "El WiFi INTEGRADO de la Pi está disponible: NO necesitas el módulo USB."
  fi
  printf '\n'
  note "Si quieres el detalle completo de cada vía, lee GUIA_WIFI.md"
}

# ════════════════════════════════════════════════════════════════════
#  WRITE · reescribe el fichero de configuración de Hiwonder
# ════════════════════════════════════════════════════════════════════
write_conf() {
  local target="$1" mode="$2" ssid="$3" pass="$4"
  python3 - "$target" "$mode" "$ssid" "$pass" <<'PY'
import re, sys, pathlib

target, mode, ssid, pw = sys.argv[1:5]      # 'pass' es palabra reservada en Python
path = pathlib.Path(target)
src = path.read_text(encoding="utf-8", errors="replace")

values = {
    "HW_WIFI_MODE": str(int(mode)),          # debe quedar como ENTERO, no texto
}
if str(int(mode)) != "3":
    # en modo 3 (AP + eth0) las credenciales del router no se usan: se dejan
    # como estaban, por si el usuario luego cambia al modo 2
    values["HW_WIFI_STA_SSID"] = repr(ssid)
    values["HW_WIFI_STA_PASSWORD"] = repr(pw)

out, seen = [], set()
for line in src.splitlines():
    m = re.match(r"^(\s*)(#\s*)?(HW_WIFI_[A-Z0-9_]+)\s*=", line)
    if m and m.group(3) in values:
        key = m.group(3)
        if key in seen:          # elimina definiciones duplicadas
            continue
        seen.add(key)
        out.append("%s%s = %s" % (m.group(1), key, values[key]))
    else:
        out.append(line)

missing = [(k, v) for k, v in values.items() if k not in seen]
if missing:
    idx = len(out)
    for i, line in enumerate(out):           # insertar antes del bloque __main__
        if line.startswith("if __name__"):
            idx = i
            break
    block = [""] + ["%s = %s" % (k, v) for k, v in missing]
    out = out[:idx] + block + out[idx:]

path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
}

# ════════════════════════════════════════════════════════════════════
#  STA · entrar en tu router (modo LAN)
# ════════════════════════════════════════════════════════════════════
do_sta() {
  local ssid="$SSID" pass="$PASS" delay="$DELAY" no_watchdog="$NO_WATCHDOG" mode="$MODE"

  [ "$mode" = "2" ] || [ "$mode" = "3" ] || die "--mode debe ser 2 (cliente) o 3 (AP + internet por eth0)"
  if [ "$mode" = "2" ]; then
    [ -n "$ssid" ] || die "falta --ssid (el nombre de tu WiFi)"
    if [ -z "$pass" ]; then
      # se pide oculta: asi la clave no queda en el historial del shell
      printf "Contraseña de la red '%s' (vacio si es abierta): " "$ssid"
      read -r -s pass
      echo
      if [ -z "$pass" ]; then
        warn "red ABIERTA (sin contraseña): se intentará así"
      fi
    fi
  fi

  local cf
  cf=$(conf_files)
  [ -n "$cf" ] || die "no encuentro wifi_conf.py en $CONF_DIR"

  echo "== MODO LAN/STA =="
  if [ "$mode" = "3" ]; then
    note "modo 3: el robot KEEPA su hotspot y comparte el internet que le llega por eth0"
    note "       (el hotspot 'HW-...' sigue vivo -> tu VNC/SSH no se cae nunca)"
    note "       recuerda: el cable RJ45 del robot tiene que estar al router"
  else
    note "modo 2: el robot entra en tu router como cliente y pide IP por DHCP"
  fi
  note "red     : $ssid"
  note "clave   : $(mask_pw "$pass")"

  # 1 · copia de seguridad
  rm -rf "$BACKUP_DIR"; mkdir -p "$BACKUP_DIR"
  local f base
  for f in $cf; do
    base=$(basename "$f")
    cp -p "$f" "$BACKUP_DIR/$base"
  done
  ok "copia guardada en $BACKUP_DIR"

  # 2 · reescribir configuración
  for f in $cf; do
    write_conf "$f" "$mode" "$ssid" "$pass" || die "fallo reescribiendo $f"
    note "$(basename "$f"): HW_WIFI_MODE = $mode, SSID y contraseña escritos"
  done
  grep -hE '^\s*HW_WIFI_(MODE|STA_SSID)' $cf 2>/dev/null \
    | sed -E 's/(PASSWORD\s*=\s*).*/\1'"'"'***'"'"'/' | sed 's/^/    /'

  # 3 · sudo (para el reinicio y el vigilante)
  if has sudo; then
    sudo -v 2>/dev/null || warn "sudo pide contraseña: ejecútalo tú con sudo para el reinicio"
  fi

  # 4 · vigilante de vuelta atrás
  if [ "$no_watchdog" = "0" ]; then
    # en modo 2 vigilamos el WiFi (wlan0); en modo 3 vigilamos el cable (eth0)
      if [ "$mode" = "3" ]; then CHECK_IF="eth0"; else CHECK_IF="$(wifi_iface)"; fi
    {
      echo "#!/usr/bin/env bash"
      echo "sleep $delay"
      echo "iface=\$(iw dev 2>/dev/null | awk '/^Interface /{print \$2; exit}')"
      echo "ip=\$(ip -4 -o addr show '$CHECK_IF' 2>/dev/null | awk '{print \$4}' | cut -d/ -f1 | grep -vE '^(127\\.|169\\.254\\.|192\\.168\\.149\\.)' | head -1)"
      echo "dev=\$(ip route 2>/dev/null | awk '/^default/{print \$5; exit}')"
      echo "if [ -z \"\$ip\" ] || [ -z \"\$dev\" ]; then"
      echo "  echo \"[watchdog] sin IP de LAN -> vuelvo al modo AP\""
      for f in $cf; do
        echo "  cp -f '$BACKUP_DIR/$(basename "$f")' '$f'"
      done
      echo "  sudo -n systemctl restart hw_wifi.service >/dev/null 2>&1 || sudo -n systemctl restart wifi.service >/dev/null 2>&1"
      echo "  echo \"[watchdog]rollback hecho\""
      echo "else"
      echo "  echo \"[watchdog] OK: IP \$ip via \$dev — se queda en modo LAN\""
      echo "fi"
    } > "$WATCHDOG_SCRIPT"
    chmod +x "$WATCHDOG_SCRIPT"
    setsid nohup bash "$WATCHDOG_SCRIPT" >>"$HOME/tonypi_wifi_watchdog.log" 2>&1 &
    echo $! > "$WATCHDOG_PID"
    ok "vigilante activo: si en ${delay}s no hay IP, vuelve solo al modo AP"
    note "para cancelarlo si todo va bien:  bash tonypi_wifi.sh cancel-watchdog"
  else
    note "vigilante desactivado (--no-watchdog)"
  fi

  # 5 · reiniciar el servicio de WiFi y VERIFICAR que el cambio ha tomado
  # (en el TonyPi v1.0 el servicio que lee HW_WIFI_MODE puede ser wifi.service
  #  o hw_wifi.service según la imagen: se prueban los dos y se comprueba)
  local restarted=0 attempt wif ethip
  {
    echo "=== $(date -Is) · cambio a modo $mode en curso ==="
    echo "ssid=$ssid"
    echo "servicio/estado pendientes..."
  } > "$RESULT_LOG"
  for attempt in "wifi.service" "hw_wifi.service"; do
    systemctl list-unit-files 2>/dev/null | grep -q "^${attempt}" || continue
    if sudo -n systemctl restart "$attempt" 2>/dev/null || sudo systemctl restart "$attempt" 2>/dev/null; then
      ok "servicio '$attempt' reiniciado"
      restarted=1
      sleep 12
      if [ "$mode" = "3" ]; then
        # en modo 3 el WiFi sigue en AP (eso es lo correcto): lo que tiene que
        # funcionar es el cable
        local ethip
        ethip=$(iface_ips eth0 | head -1)
        if [ -n "$ethip" ]; then
          ok "eth0 tiene IP ($ethip) -> el robot ya tiene internet por cable"
        else
          warn "eth0 sigue sin IP: enchufa el cable RJ45 del robot al router"
        fi
      else
        wif=$(wifi_iface)
        if [ -z "$wif" ]; then
          warn "no hay interfaz WiFi despues del reinicio"
        elif iface_is_ap "$wif"; then
          warn "'$attempt' reiniciado pero $wif SIGUE en modo AP"
          warn "ese servicio no es el que lee HW_WIFI_MODE; pruebo con el otro"
        else
          lanip=$(iface_ips "$wif" 2>/dev/null | grep -vE '^(127\.|169\.254\.|192\.168\.149\.)' | head -1)
          if [ -z "$lanip" ]; then
            warn "$wif en modo cliente pero SIN IP de LAN: se asocio pero no hay DHCP"
            warn "  revisa: banda 2.4 GHz, WPA2-Personal, red existente y sin portal cautivo"
          else
            ok "$wif en modo cliente (STA) con IP $lanip"
          fi
          break
        fi
      fi
    fi
  done
  [ "$restarted" = "1" ] || warn "no pude reiniciar el servicio (revisa sudo / el nombre del servicio)"

  echo
  echo "== ESPERANDO AL ROBOT =="
  sleep 8
  do_status

  {
    echo "=== $(date -Is) · cambio a modo $mode ==="
    echo "ssid=$ssid"
    echo "modo=$mode"
    echo "servicio reiniciado : $([ "$restarted" = "1" ] && echo si || echo NO)"
    echo "interfaz wifi       : ${wif:-ninguna}"
    echo "tipo de interfaz    : $([ -n "$wif" ] && (iface_is_ap "$wif" && echo 'sigue en AP' || echo 'cliente (STA)'))"
    echo "ip en wlan0         : $(iface_ips wlan0 2>/dev/null | tr '\n' ' ')"
    echo "ip en eth0          : $(iface_ips eth0 2>/dev/null | tr '\n' ' ')"
    echo "todas las ips       : $(hostname -I 2>/dev/null)"
    echo "gateway             : $(default_gw)"
    echo "nvidia_http         : $(has_internet)"
  } > "$RESULT_LOG"
  note "resultado guardado en el robot: $RESULT_LOG"

  printf '\n'
  if [ "$mode" = "3" ]; then
    note "MODO 3: tu sesión NO se cae. El hotspot 'HW-...' sigue igual."
    note "1) Comprueba el cable:  ip -br addr show eth0   y   ping -c3 1.1.1.1"
    note "2) El robot ya tiene internet; el PC puede salir por el hotspot del robot."
    note "3) Para volver al modo AP puro:  bash tonypi_wifi.sh ap"
  else
    note "ATENCIÓN: tu sesión VNC/SSH se va a caer (el robot cambia de red)."
    note "1) Mira la IP nueva arriba o en la tabla de DHCP de tu router."
    note "2) Vuelve a conectar VNC a esa IP (usuario 'pi')."
    note "3) Si todo va bien:  bash tonypi_wifi.sh cancel-watchdog"
    note "4) Si no vuelve:      bash tonypi_wifi.sh ap   (o botón KEY1 del robot)"
  fi
}

# ════════════════════════════════════════════════════════════════════
#  AP · volver al hotspot propio
# ════════════════════════════════════════════════════════════════════
do_ap() {
  echo "== VOLVIENDO AL MODO AP (hotspot propio) =="
  if [ -d "$BACKUP_DIR" ]; then
    local f base
    for f in "$BACKUP_DIR"/*; do
      [ -f "$f" ] || continue
      base=$(basename "$f")
      for d in "$CONF_DIR/$base" "$CONF_DIR"; do
        if [ -f "$d/$base" ]; then
          cp -f "$f" "$d/$base" && ok "restaurado $(basename "$d/$base")"
          break
        fi
      done
    done
  else
    warn "no hay copia de seguridad ($BACKUP_DIR)"
  fi
  sudo -n systemctl restart hw_wifi.service 2>/dev/null || sudo systemctl restart hw_wifi.service 2>/dev/null \
    || sudo -n systemctl restart wifi.service 2>/dev/null || sudo systemctl restart wifi.service 2>/dev/null \
    || warn "no pude reiniciar el servicio de WiFi"
  sleep 8
  echo
  note "hotspot esperado: SSID que empieza por 'HW' · contraseña 'hiwonder'"
  note "IP del robot en AP: 192.168.149.1"
  note "para watchers:  bash tonypi_wifi.sh cancel-watchdog"
}

# ════════════════════════════════════════════════════════════════════
#  STATUS · resumen rápido
# ════════════════════════════════════════════════════════════════════
do_status() {
  local iface code
  iface=$(wifi_iface)
  echo "== ESTADO DE RED =="
  note "interfaces : $(ip -br addr 2>/dev/null | awk 'NR>1{printf "%s(%s) ", $1, $3}')"
  note "wi-fi      : ${iface:-ninguna}$( [ -n "$iface" ] && iface_is_ap "$iface" && echo ' [MODO AP]')"
  note "gateway    : $(default_gw)"
  note "internet   : ping $(ping -c 1 -W 2 1.1.1.1 >/dev/null 2>&1 && echo OK || echo no)"
  code=$(has_internet)
  note "nvidia api : ${code:-sin respuesta}$( [ "$code" = "200" ] && echo '  ✓ LLM listo')"
  note "ip         : $(hostname -I 2>/dev/null)"
}

# ════════════════════════════════════════════════════════════════════
#  CANCEL-WATCHDOG
# ════════════════════════════════════════════════════════════════════
do_cancel_watchdog() {
  if [ -f "$WATCHDOG_PID" ]; then
    local pid; pid=$(cat "$WATCHDOG_PID")
    if kill "$pid" 2>/dev/null; then ok "vigilante detenido (pid $pid)"; else note "el vigilante ya no está en marcha"; fi
    rm -f "$WATCHDOG_PID"
  else
    note "no hay vigilante registrado"
  fi
  pkill -f "$WATCHDOG_SCRIPT" 2>/dev/null && ok "procesos restantes detenidos" || true
}

# ════════════════════════════════════════════════════════════════════
#  MODO REMOTO (--host): se ejecuta en el robot por SSH
# ════════════════════════════════════════════════════════════════════
run_remote() {
  say "Conectando por SSH a $USER_NAME@$HOST"
  ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new "$USER_NAME@$HOST" true 2>/dev/null \
    || die "no responde por SSH: $USER_NAME@$HOST (si es modo AP prueba 192.168.149.1)"
  scp -q "$0" "$USER_NAME@$HOST:/tmp/tonypi_wifi.sh" 2>/dev/null \
    || die "no se pudo copiar el script al robot"

  # entrecomillado seguro para valores con espacios, comillas y símbolos
  q() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"; }

  local remote="$CMD"
  [ -n "$SSID" ] && remote="$remote --ssid $(q "$SSID")"
  # si no hay clave, la pide el robot (no viaja en la linea de comando)
  [ -n "$PASS" ] && remote="$remote --pass $(q "$PASS")"
  [ "$MODE" != "2" ] && remote="$remote --mode $(q "$MODE")"
  [ "$NO_WATCHDOG" = "1" ] && remote="$remote --no-watchdog"
  [ "$DELAY" != "$DEFAULT_WATCHDOG_DELAY" ] && remote="$remote --watchdog-delay $(q "$DELAY")"

  say "Ejecutando en el robot: bash /tmp/tonypi_wifi.sh $remote"
  ssh -t "$USER_NAME@$HOST" "bash /tmp/tonypi_wifi.sh $remote"
}

# ════════════════════════════════════════════════════════════════════
#  FIND-IP · localizar el robot en la red actual
# ════════════════════════════════════════════════════════════════════
do_find_ip() {
  echo "== BUSCANDO EL ROBOT EN ESTA RED =="

  # 1) mDNS: el hostname del robot es 'raspberrypi'
  local mip
  mip=$(getent hosts raspberrypi.local 2>/dev/null | awk '{print $1; exit}')
  if [ -n "$mip" ]; then
    ok "por mDNS: raspberrypi.local -> $mip"
    note "  ssh pi@$mip"
    note "  bash tonypi_wifi.sh --host $mip cancel-watchdog"
    return 0
  fi
  note "mDNS no resuelve (normal en algunos hotspots)"

  # 2) escaneo de la subred local buscando el puerto 9030 del JSON-RPC
  local gw base found ip lip
  gw=$(default_gw)
  if [ -n "$gw" ]; then
    base=$(printf '%s' "$gw" | awk -F. '{print $1"."$2"."$3}')
  else
    lip=$(hostname -I 2>/dev/null | awk '{print $1}')
    if [ -n "$lip" ]; then
      base=$(printf '%s' "$lip" | awk -F. '{print $1"."$2"."$3}')
      note "sin ruta por defecto: uso la subred de mi IP local ($lip)"
    else
      warn "no hay ruta por defecto ni IP local: conectate a la red del robot"
      return 1
    fi
  fi
  note "la puerta de enlace es $gw -> escaneo $base.0/24 en el puerto 9030"
  note "(el puerto 9030 es el JSON-RPC del TonyPi: solo el robot lo abre)"

  found=$(for i in $(seq 1 254); do echo "$base.$i"; done \
    | xargs -P 32 -I{} sh -c 'timeout 1 bash -c "echo > /dev/tcp/{}/9030" 2>/dev/null && echo {}' 2>/dev/null)

  if [ -z "$found" ]; then
    warn "nada responde en 9030 en $base.0/24"
    note "¿el PC esta en la misma red que el robot? (si el robot se movio al"
    note "hotspot del movil, conecta el movil al PC tambien)"
    return 1
  fi

  # 2b) verificar que quien responde en el 9030 es de verdad el TonyPi:
  #     le hacemos una llamada JSON-RPC 'echo' y exigimos una respuesta valida
  local rpc='{"jsonrpc":"2.0","method":"echo","params":["ping"],"id":1}'
  local hit=0
  while read -r ip; do
    [ -n "$ip" ] || continue
    local resp
    resp=$(curl -s -m 4 -X POST -H 'Content-Type: application/json' \
      -d "$rpc" "http://$ip:9030/" 2>/dev/null)
    case "$resp" in
      *'"jsonrpc"'*|*'"result"'*|*'"error"'*)
        ok "$ip responde como TonyPi (JSON-RPC) -> ese es el robot"
        note "  ssh pi@$ip"
        note "  bash tonypi_wifi.sh --host $ip cancel-watchdog"
        hit=1
        ;;
      *)
        note "$ip tiene el 9030 abierto pero no contesta JSON-RPC (descartado)"
        ;;
    esac
  done <<EOF
$found
EOF
  [ "$hit" = "1" ] && return 0
  warn "hay dispositivos con el 9030 abierto, pero ninguno responde como TonyPi"
  return 1
}

# ════════════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════════════
CMD=""
HOST=""
USER_NAME="${TONYPI_USER:-pi}"
SSID=""
PASS=""
MODE=2
DELAY="$DEFAULT_WATCHDOG_DELAY"
NO_WATCHDOG=0

while [ $# -gt 0 ]; do
  case "$1" in
    --host)           HOST="$2"; shift 2 ;;
    --user)           USER_NAME="$2"; shift 2 ;;
    --ssid)           SSID="$2"; shift 2 ;;
    --pass|--password) PASS="$2"; shift 2 ;;
    --mode)           MODE="$2"; shift 2 ;;
    --watchdog-delay) DELAY="$2"; shift 2 ;;
    --no-watchdog)    NO_WATCHDOG=1; shift ;;
    -h|--help|help)   CMD="help"; shift ;;
    *)
      if [ -z "$CMD" ]; then CMD="$1"; shift
      else die "opción desconocida: $1"; fi
      ;;
  esac
done
[ -n "$CMD" ] || CMD="probe"

if [ -n "$HOST" ]; then
  run_remote
  exit $?
fi

case "$CMD" in
  probe|diagnostico|diag) do_probe ;;
  sta|lan)                   do_sta ;;
  ap|hotspot)                do_ap ;;
  status|estado)             do_status ;;
  find-ip|buscar)            do_find_ip ;;
  cancel-watchdog)           do_cancel_watchdog ;;
  help)                      sed -n '3,30p' "$0" | sed 's/^# \{0,1\}//' ;;
  *) die "comando desconocido: $CMD  (usa: probe | sta | ap | status | find-ip | cancel-watchdog)" ;;
esac

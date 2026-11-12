#!/usr/bin/env bash
# =============================================================================
#  find_robot.sh — encuentra la IP real del robot TonyPi desde el PC
#
#  POR QUÉ ESTE SCRIPT
#  En WSL2, `ip route` te devuelve la red VIRTUAL de WSL (172.30.x.x), no la red
#  real del robot. Y en Windows hay varios adaptadores (Ethernet, WiFi, vEthernet
#  de WSL, Docker...) → barrerlos todos busca donde no es y además barre redes
#  que no tienen nada que ver.
#
#  La versión anterior barria el /24 de CADA IP de Windows. Esta barre SOLO el
#  adaptador que tiene puerta de enlace (el que sale a internet = la red donde
#  puede estar el robot) y avisa claramente si no lo encuentra.
#
#  USO
#    bash tools/find_robot.sh                 # busca en la red activa
#    bash tools/find_robot.sh 192.168.1.50    # comprueba una IP concreta
#    bash tools/find_robot.sh --mac d8:3a:dd:6f:05:03   # busca por MAC
# =============================================================================
set -uo pipefail

RPC_PORT="${TONYPI_RPC_PORT:-9030}"
TARGET=""
WANT_MAC=""

while [ $# -gt 0 ]; do
  case "$1" in
    --mac)  WANT_MAC="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) TARGET="$1"; shift ;;
  esac
done

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
err()  { printf '  \033[31m✗\033[0m %s\n' "$*"; }
head_(){ printf '\n\033[1m%s\033[0m\n' "$*"; }

is_wsl() { grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null; }

# --- redes candidatas: SOLO los adaptadores con puerta de enlace --------------
active_networks() {
  if is_wsl; then
    powershell.exe -NoProfile -Command \
      "Get-NetIPConfiguration | Where-Object { \$_.IPv4DefaultGateway -ne \$null -and \$_.IPv4Address -ne \$null } | \
       ForEach-Object { \$_.IPv4Address.IPAddress + '|' + \$_.InterfaceAlias + '|' + \$_.IPv4DefaultGateway.NextHop }" \
      2>/dev/null | tr -d '\r'
  else
    ip -4 route show default 2>/dev/null | awk '{print $5"|" $1 "|" $3}' | while IFS='|' read -r dev gw _; do
      ip -4 addr show "$dev" 2>/dev/null | awk -v d="$dev" -v g="$gw" '/inet /{split($2,a,"/"); print a[1]"|"d"|"g; exit}'
    done
  fi
}

# --- todas las IP de Windows (para diagnóstico) -------------------------------
all_ips() {
  if is_wsl; then
    powershell.exe -NoProfile -Command \
      "Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | \
       Where-Object { \$_.IPAddress -notlike '169.254*' } | \
       ForEach-Object { \$_.IPAddress + '|' + \$_.InterfaceAlias }" 2>/dev/null | tr -d '\r'
  else
    ip -4 addr show scope global 2>/dev/null | awk '{print $2}' | cut -d/ -f1
  fi
}

port_open() {
  local ip="$1"
  timeout 2 bash -c "exec 3<>/dev/tcp/$ip/$RPC_PORT" 2>/dev/null && return 0
  return 1
}

probe_rpc() {
  curl -sS -m 3 -X POST "http://$1:$RPC_PORT/" \
    -H 'Content-Type: application/json' \
    -d '{"jsonrpc":"2.0","method":"GetRunningFunc","params":[],"id":1}' 2>/dev/null | grep -q '"result"'
}

sweep_net() {
  local net="$1"
  seq 1 254 | sed "s|^|$net.|" | \
    xargs -P 48 -I{} timeout 1 bash -c 'exec 3<>/dev/tcp/{}/'"$RPC_PORT"' 2>/dev/null && echo {}' 2>/dev/null
}

echo "═══════════════════════════════════════════════════════════"
echo "  Buscar el robot TonyPi"
echo "═══════════════════════════════════════════════════════════"

# --- caso 1: IP concreta --------------------------------------------------
if [ -n "$TARGET" ]; then
  head_ "Comprobando $TARGET"
  if port_open "$TARGET"; then
    ok "puerto $RPC_PORT abierto"
    if probe_rpc "$TARGET"; then
      ok "responde JSON-RPC → ESTE ES TU ROBOT"
      echo
      echo "  TONYPI_HOST=$TARGET"
      exit 0
    fi
    warn "el puerto abre pero no habla JSON-RPC"
  else
    err "puerto $RPC_PORT cerrado en $TARGET"
  fi
  exit 1
fi

# --- caso 2: por MAC (el dato más fiable) ---------------------------------
if [ -n "$WANT_MAC" ]; then
  head_ "Buscando la MAC $WANT_MAC en la tabla ARP"
  if is_wsl; then
    FOUND=$(powershell.exe -NoProfile -Command \
      "arp -a" 2>/dev/null | tr -d '\r' | grep -i "${WANT_MAC//:/-}" | head -1)
  else
    FOUND=$(ip neigh 2>/dev/null | grep -i "${WANT_MAC}" | head -1)
  fi
  if [ -n "$FOUND" ]; then
    ok "encontrada: $FOUND"
    IP=$(echo "$FOUND" | grep -oE '([0-9]{1,3}\.){3}[0-9]{1,3}' | head -1)
    if [ -n "$IP" ] && probe_rpc "$IP"; then
      ok "$IP responde JSON-RPC"
      echo
      echo "  TONYPI_HOST=$IP"
      exit 0
    fi
  else
    warn "no aparece en la tabla ARP (puede estar en otra red o sin tráfico reciente)"
  fi
fi

# --- caso 3: barrido de la red activa --------------------------------------
head_ "Redes por las que sale este PC (con puerta de enlace)"
NETS="$(active_networks)"
if [ -z "$NETS" ]; then
  warn "no detecto ningun adaptador con puerta de enlace"
  err "este PC no tiene salida a internet por ninguna via"
  echo "      (sin internet no hay LLM: revisa WiFi/Ethernet)"
  exit 1
fi
echo "$NETS" | while IFS='|' read -r ip alias gw; do
  echo "    $ip  ($alias)  ->  $gw"
done

SEARCHED=""
FOUND_HOST=""
for entry in $NETS; do
  ip="${entry%%|*}"; rest="${entry#*|}"; alias="${rest%%|*}"
  case "$alias" in *WSL*|*"Virtual"*|*Docker*|*vEthernet*) continue ;; esac
  net=$(echo "$ip" | awk -F. '{print $1"."$2"."$3}')
  SEARCHED="$SEARCHED $net.0/24"
  echo "    barriendo $net.0/24 ..."
  for host in $(sweep_net "$net"); do
    echo "      $host:$RPC_PORT abierto"
    if probe_rpc "$host"; then
      FOUND_HOST="$host"
      break
    fi
  done
  [ -n "$FOUND_HOST" ] && break
done

if [ -n "$FOUND_HOST" ]; then
  ok "ESTE ES TU ROBOT: $FOUND_HOST"
  echo
  echo "  TONYPI_HOST=$FOUND_HOST"
  echo
  echo "  sed -i \"s|^TONYPI_HOST=.*|TONYPI_HOST=$FOUND_HOST|\" .env"
  exit 0
fi

head_ "No lo encuentro"
echo "  Busqué en:$SEARCHED"
echo
echo "  Motivos habituales:"
echo "   · el robot esta en OTRA red (ej. el hotspot del iPhone 172.20.10.0/24,"
echo "     o tu router 192.168.1.0/24). Conectate a ESA red y repite."
echo "   · el robot esta apagado o reiniciandose (espera ~60 s)."
echo "   · el robot sigue en modo AP: su IP es 192.168.149.1, pero solo si tu PC"
echo "     esta conectado a SU hotspot (HW-<serial>)."
echo "   · otra maquina en la red tiene el puerto $RPC_PORT abierto (no es el robot)."
echo
echo "  Todas las IP de este PC (por si el barrido no cuadra):"
all_ips | sed 's/^/    /'
exit 1

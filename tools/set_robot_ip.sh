#!/usr/bin/env bash
# =============================================================================
#  set_robot_ip.sh — apunta el proyecto al robot y lo verifica
#
#  Deja el proyecto listo para hablar con el robot:
#    · escribe TONYPI_HOST (y los puertos) en el .env
#    · actualiza el alias 'tonypi' de ~/.ssh/config
#    · comprueba que el robot responde por :9030 (JSON-RPC) y :8080 (cámara)
#
#  USO
#    bash tools/set_robot_ip.sh 172.20.10.2
#    bash tools/set_robot_ip.sh              # te lo pregunta
#
#  La IP se saca del propio robot:
#    ip -4 -o addr show wlan0
# =============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/.env"
SSH_CONFIG="$HOME/.ssh/config"

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
err()  { printf '  \033[31m✗\033[0m %s\n' "$*"; }
head_(){ printf '\n\033[1m%s\033[0m\n' "$*"; }

IP="${1:-}"
if [ -z "$IP" ]; then
  read -r -p "IP del robot: " IP
fi
if ! echo "$IP" | grep -qE '^([0-9]{1,3}\.){3}[0-9]{1,3}$'; then
  err "IP no válida: '$IP'"
  exit 1
fi

echo "═══════════════════════════════════════════════════════════"
echo "  Apuntando el proyecto al robot $IP"
echo "═══════════════════════════════════════════════════════════"

# --- 1. .env ------------------------------------------------------------------
head_ "1. $ENV_FILE"
if [ ! -f "$ENV_FILE" ]; then
  err "no existe $ENV_FILE"
  [ -f "$ROOT/.env.example" ] && { cp "$ROOT/.env.example" "$ENV_FILE"; chmod 600 "$ENV_FILE"; ok "creado desde .env.example"; }
fi

set_env() {
  local key="$1" val="$2"
  if grep -qE "^[[:space:]]*${key}=" "$ENV_FILE" 2>/dev/null; then
    sed -i "s|^[[:space:]]*${key}=.*|${key}=${val}|" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$val" >> "$ENV_FILE"
  fi
}

set_env TONYPI_HOST "$IP"
set_env TONYPI_RPC_PORT "9030"
set_env TONYPI_MJPG_PORT "8080"
chmod 600 "$ENV_FILE" 2>/dev/null || true
ok "TONYPI_HOST=$IP   (permisos 600)"

# --- 2. alias de SSH ----------------------------------------------------------
head_ "2. $SSH_CONFIG"
if [ -f "$SSH_CONFIG" ] && grep -q "^Host tonypi$" "$SSH_CONFIG"; then
  sed -i "/^Host tonypi$/,/^$/ s|^\s*HostName .*|    HostName $IP|" "$SSH_CONFIG"
  ok "alias 'tonypi' -> $IP"
else
  warn "no hay alias 'tonypi' en ~/.ssh/config (opcional)"
  echo "      si lo quieres:"
  echo "        printf '\\nHost tonypi\\n    HostName $IP\\n    User pi\\n' >> ~/.ssh/config"
fi

# --- 3. verificación ----------------------------------------------------------
head_ "3. ¿Responde el robot?"
if ping -c2 -W2 "$IP" >/dev/null 2>&1; then
  ok "ping $IP responde"
else
  warn "el ping a $IP no responde"
  echo "      · ¿el PC está en la MISMA red que el robot (ej. 'iPhone de Cordoba')?"
  echo "      · comprueba por dónde sale el tráfico:  ip route get $IP"
  echo "      · si están en redes distintas: 'host de destino inaccesible'"
fi

RPC=$(curl -sS -m 6 -o /dev/null -w '%{http_code}' "http://$IP:9030/" 2>/dev/null)
if [ "$RPC" = "200" ] || [ "$RPC" = "500" ] || [ "$RPC" = "405" ]; then
  ok "puerto 9030 responde (HTTP $RPC)"
else
  warn "puerto 9030 no responde (HTTP ${RPC:-000})"
  echo "      · comprueba en el robot:  systemctl is-active tonypi.service"
fi

SNAP=$(curl -sS -m 8 -o /tmp/_snap.jpg -w '%{http_code}' "http://$IP:8080/?action=snapshot" 2>/dev/null)
SIZE=$(stat -c%s /tmp/_snap.jpg 2>/dev/null || echo 0)
if [ "${SNAP:-000}" = "200" ] && [ "$SIZE" -gt 5000 ]; then
  ok "cámara OK (snapshot de $SIZE bytes)"
  rm -f /tmp/_snap.jpg
else
  warn "snapshot: HTTP ${SNAP:-000}, $SIZE bytes"
  echo "      · si sale 0 bytes, la cámara no está sirviendo (reinicia tonypi.service)"
fi

head_ "4. Listo"
echo "  .env      → TONYPI_HOST=$IP"
echo "  verifica  → grep TONYPI .env"
echo
echo "  Siguiente paso (fase 5): dejar el robot en reposo"
echo "    curl -sS -m 5 -X POST http://$IP:9030/ -H 'Content-Type: application/json' -d '{\"jsonrpc\":\"2.0\",\"method\":\"UnloadFunc\",\"params\":[],\"id\":1}'"
echo "    → debe responder  {\"jsonrpc\":\"2.0\",\"result\":[true,[0]],\"id\":1}"
echo "═══════════════════════════════════════════════════════════"

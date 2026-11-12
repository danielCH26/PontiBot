#!/usr/bin/env bash
# =============================================================================
#  test_movimientos.sh — prueba los movimientos del robot por JSON-RPC (sin LLM)
#
#  Sirve para separar los fallos:
#    · ¿el robot obedece?          → este script
#    · ¿el LLM pide bien la tool?   → voice_agent.py --text "..."
#
#  USO
#    bash tools/test_movimientos.sh                    # usa TONYPI_HOST del .env
#    bash tools/test_movimientos.sh 172.20.10.2
#    bash tools/test_movimientos.sh 172.20.10.2 wave bow
# =============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROBOT=""
POS="${2:-}"

# --- IP: argumento > .env > 192.168.149.1 --------------------------------------
if [ -n "${1:-}" ] && echo "$1" | grep -qE '^([0-9]{1,3}\.){3}[0-9]{1,3}$'; then
  ROBOT="$1"; shift
  ACTIONS=("$@")
else
  ACTIONS=("$@")
  if [ -f "$ROOT/.env" ]; then
    ROBOT=$(grep -E "^TONYPI_HOST=" "$ROOT/.env" | head -1 | cut -d= -f2 | tr -d ' \r"'"'"'')
  fi
  [ -z "$ROBOT" ] && ROBOT="192.168.149.1"
fi
if [ -n "$POS" ]; then ACTIONS=("$@"); fi
[ ${#ACTIONS[@]} -eq 0 ] && ACTIONS=(wave bow chest stand)

RPC_URL="http://$ROBOT:9030/"

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
err()  { printf '  \033[31m✗\033[0m %s\n' "$*"; }
head_(){ printf '\n\033[1m%s\033[0m\n' "$*"; }

rpc() {  # rpc <method> <json-params>
  curl -sS -m 12 -X POST "$RPC_URL" -H 'Content-Type: application/json' \
    -d "{\"jsonrpc\":\"2.0\",\"method\":\"$1\",\"params\":$2,\"id\":1}" 2>&1
}

echo "═══════════════════════════════════════════════════════════"
echo "  Test de movimientos del robot → $ROBOT"
echo "═══════════════════════════════════════════════════════════"

# --- 1. ¿responde? ------------------------------------------------------------
head_ "1. Conectividad"
PING=$(rpc "GetRunningFunc" "[]")
if echo "$PING" | grep -q '"result"'; then
  ok "JSON-RPC responde: $PING"
else
  err "no responde: $PING"
  echo
  echo "  · ¿el PC está en la misma red que el robot?"
  echo "  · ¿el servicio del robot está vivo?  systemctl is-active tonypi.service"
  if [ "$ROBOT" = "192.168.149.1" ]; then
    echo
    echo "  OJO: 192.168.149.1 es la IP del HOTSPOT del robot (modo AP)."
    echo "     Si el robot esta en modo STA (en tu router o en el hotspot del iPhone),"
    echo "     su IP es otra. Pasasela como argumento:"
    echo "       bash tools/test_movimientos.sh 172.20.10.2"
    echo "     y deja el .env al dia para que no vuelva a pasar:"
    echo "       bash tools/set_robot_ip.sh 172.20.10.2"
  fi
  exit 1
fi

# --- 2. El robot está en reposo? ---------------------------------------------
head_ "2. Estado del robot"
if echo "$PING" | grep -qE '"result":\s*\[true,\s*\[0\]\]'; then
  ok "en reposo (RunningFunc = 0)"
else
  warn "GetRunningFunc no devuelve 0 (ese metodo miente en este firmware) → ejecuta UnloadFunc"
fi

# --- 3. Movimientos -----------------------------------------------------------
head_ "3. Movimientos"
for action in "${ACTIONS[@]}"; do
  printf "  %-12s " "$action"
  RESP=$(rpc "RunAction" "[\"$action\", 1]")
  if echo "$RESP" | grep -q '"result"'; then
    ok "$action → $RESP"
    sleep 3
  else
    err "$action → $RESP"
    echo "      (si dice 'accion desconocida', mira la lista con:"
    echo "       python3 -c 'import sys; sys.path.insert(0,\"pc\"); from tonypi_client import NAMED_ACTIONS; print(list(NAMED_ACTIONS))')"
    break
  fi
done

# --- 4. Parar ---------------------------------------------------------------
head_ "4. Parada de emergencia"
STOP=$(rpc "StopActionGroup" '["stopActionGroup"]')
if echo "$STOP" | grep -q '"result"'; then ok "StopActionGroup → $STOP"; else warn "$STOP"; fi

# --- 5. Snapshot (visión) ----------------------------------------------------
head_ "5. Cámara (visión)"
SNAP=$(curl -sS -m 8 -o /tmp/_test_snap.jpg -w '%{http_code}' "http://$ROBOT:8080/?action=snapshot" 2>&1)
SIZE=$(stat -c%s /tmp/_test_snap.jpg 2>/dev/null || echo 0)
if [ "$SNAP" = "200" ] && [ "$SIZE" -gt 5000 ]; then
  ok "snapshot OK ($SIZE bytes)"
else
  warn "snapshot: HTTP $SNAP, $SIZE bytes"
fi
rm -f /tmp/_test_snap.jpg

echo
echo "═══════════════════════════════════════════════════════════"
echo "  Si el robot se movió → el canal de control funciona."
echo "  Ahora prueba el cerebro (sin micro):"
echo "    cd pc && python3 voice_agent.py --text 'saluda y haz una reverencia'"
echo "═══════════════════════════════════════════════════════════"

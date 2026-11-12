#!/usr/bin/env bash
# =============================================================================
#  nvidia_check.sh — comprueba la clave y el modelo contra la API de NVIDIA
#
#  Qué diagnostica:
#    · la clave (presente, prefijo nvapi-, longitud)
#    · GET  {base}/models            → 200 / 401 / 403 / 429 / 500
#    · POST {base}/chat/completions  → 200 / 401 / 403 / 404 / 429 / 500
#      (con un payload mínimo, para detectar el error 500 "Missing request
#       extension" de axum, que en realidad es un bearer VACÍO)
#
#  USO
#    bash tools/nvidia_check.sh                  # usa el .env de la raíz
#    bash tools/nvidia_check.sh /ruta/al/.env
#    bash tools/nvidia_check.sh --models         # lista el catálogo de tu clave
#    bash tools/nvidia_check.sh --model nvidia/nemotron-3.5-bolt-e4b
#
#  NO imprime la clave: solo la enmascara.
# =============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE=""
LIST_MODELS=0
MODEL_OVERRIDE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --models) LIST_MODELS=1; shift ;;
    --model)  MODEL_OVERRIDE="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *)  ENV_FILE="$1"; shift ;;
  esac
done
[ -n "$ENV_FILE" ] || ENV_FILE="$ROOT/.env"

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
err()  { printf '  \033[31m✗\033[0m %s\n' "$*"; }
head_(){ printf '\n\033[1m%s\033[0m\n' "$*"; }

# --- leer del .env tolerando CRLF, comillas y espacios ------------------------
get() {
  local key="$1" line
  line=$(grep -E "^[[:space:]]*${key}=" "$ENV_FILE" 2>/dev/null | head -1)
  [ -z "$line" ] && { echo ""; return; }
  line="${line#*=}"
  line="${line%$'\r'}"
  line="${line%$'\n'}"
  line="$(echo "$line" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  line="${line%\"}"; line="${line#\"}"
  line="${line%\'}"; line="${line#\'}"
  echo "$line"
}
mask() { local v="$1"; if [ ${#v} -le 12 ]; then echo "$v"; else echo "${v:0:8}…${v: -4}"; fi; }

echo "═══════════════════════════════════════════════════════════"
echo "  NVIDIA check"
echo "═══════════════════════════════════════════════════════════"

# --- 1. Clave -----------------------------------------------------------------
head_ "1. Clave"
KEY="$(get LLM_API_KEY)"
KEY_SRC="$ENV_FILE (LLM_API_KEY)"
if [ -z "$KEY" ]; then
  KEY="${NVIDIA_API_KEY:-}"
  KEY_SRC="entorno (NVIDIA_API_KEY)"
fi
if [ -z "$KEY" ]; then
  KEY="${LLM_API_KEY:-}"
  KEY_SRC="entorno (LLM_API_KEY)"
fi

if [ -z "$KEY" ]; then
  err "No hay clave en $ENV_FILE ni en el entorno."
  echo "     Ponla en .env:  LLM_API_KEY=nvapi-..."
  exit 1
fi

if [ "${KEY:0:6}" != "nvapi-" ]; then
  err "La clave no empieza por 'nvapi-': $(mask "$KEY")"
  echo "     ¿La has pegado con comillas, con un espacio detrás o con un CR al final?"
  echo "     Arregla el .env y vuelve a pasar el script."
  exit 1
fi
if [ ${#KEY} -lt 40 ]; then
  err "La clave es demasiado corta: $(mask "$KEY") (${#KEY} caracteres)"
  exit 1
fi
ok "Clave: $(mask "$KEY")  (${#KEY} caracteres, de $KEY_SRC)"

BASE="$(get LLM_BASE_URL)"
[ -z "$BASE" ] && BASE="https://integrate.api.nvidia.com/v1"
BASE="${BASE%/}"
MODEL="$MODEL_OVERRIDE"
[ -z "$MODEL" ] && MODEL="$(get LLM_MODEL)"
[ -z "$MODEL" ] && MODEL="nvidia/nemotron-3.5-bolt-e4b"
ok "Endpoint: $BASE"
ok "Modelo:   $MODEL"

# --- 2. GET /models -----------------------------------------------------------
head_ "2. GET $BASE/models"
RESP=$(curl -sS -m 30 -w '\n__HTTP__%{http_code}' \
  -H "Authorization: Bearer $KEY" \
  -H "Accept: application/json" \
  "$BASE/models" 2>&1)
CODE=$(echo "$RESP" | sed -n 's/.*__HTTP__\([0-9]\{3\}\)$/\1/p')
BODY=$(echo "$RESP" | sed 's/__HTTP__[0-9]\{3\}$//')

case "$CODE" in
  200)
    ok "HTTP 200 — la clave vale y /v1/models responde"
    if command -v python3 >/dev/null 2>&1; then
      echo "$BODY" | python3 -c "
import json,sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
ids = [m.get('id','') for m in d.get('data',[])]
print('    modelos en el catálogo de tu clave: %d' % len(ids))
asr = [i for i in ids if any(k in i.lower() for k in ('whisper','parakeet','canary','asr','speech','stt','riva'))]
print('    candidatos ASR: %s' % (', '.join(asr[:8]) if asr else 'NINGUNO -> el ASR va local (whisper.cpp) o por OpenAI'))
" 2>/dev/null
    fi
    ;;
  401) err "HTTP 401 — clave no reconocida o sin cabecera Authorization" ;;
  403) err "HTTP 403 — la clave no tiene permiso o la ruta de salida está bloqueada (WAF/geo)" ;;
  404) err "HTTP 404 — endpoint equivocado: revisa LLM_BASE_URL" ;;
  429) warn "HTTP 429 — límite de peticiones (~40/min con el free tier). Reintenta en un momento" ;;
  500) err "HTTP 500 — error del gateway NVIDIA. Suele ser el bearer vacío o una caída de su axum" ;;
  *)   err "HTTP ${CODE:-?} — respuesta inesperada" ;;
esac

if [ "$LIST_MODELS" -eq 1 ]; then
  echo
  echo "    Catálogo:"
  echo "$BODY" | python3 -c "
import json,sys
try: d=json.load(sys.stdin)
except Exception: sys.exit(0)
for m in sorted(d.get('data',[]), key=lambda x: x.get('id','')):
    print('      %s' % m.get('id',''))
" 2>/dev/null
  exit 0
fi

# --- 3. POST /chat/completions ------------------------------------------------
head_ "3. POST $BASE/chat/completions (prueba real)"
PAYLOAD=$(cat <<EOF
{"model":"$MODEL","messages":[{"role":"user","content":"di hola en español"}],
 "max_tokens":24,"temperature":0.1}
EOF
)
RESP2=$(curl -sS -m 45 -w '\n__HTTP__%{http_code}' \
  -X POST "$BASE/chat/completions" \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" 2>&1)
CODE2=$(echo "$RESP2" | sed -n 's/.*__HTTP__\([0-9]\{3\}\)$/\1/p')
BODY2=$(echo "$RESP2" | sed 's/__HTTP__[0-9]\{3\}$//')

case "$CODE2" in
  200)
    ok "HTTP 200 — el modelo responde"
    echo "$BODY2" | python3 -c "
import json,sys
try: d=json.load(sys.stdin)
except Exception:
    print('    (respuesta no JSON)'); sys.exit(0)
ch = d.get('choices') or []
if ch:
    txt = (ch[0].get('message') or {}).get('content','')
    print('    respuesta: %s' % (txt[:90].replace(chr(10),' ') if txt else '(vacía)'))
print('    finish_reason: %s' % ch[0].get('finish_reason'))
" 2>/dev/null
    ;;
  401)
    err "HTTP 401 — clave rechazada"
    echo "$BODY2" | head -3 | sed 's/^/      /'
    ;;
  403)
    err "HTTP 403 — sin permiso o WAF: rota la clave en https://build.nvidia.com/settings"
    echo "$BODY2" | head -3 | sed 's/^/      /'
    ;;
  404)
    err "HTTP 404 — el modelo '$MODEL' no existe PARA TU CUENTA"
    echo "      Ojo: /v1/models lista 85 modelos pero algunos dan 404 con tu clave."
    echo "      Prueba otro:  bash tools/nvidia_check.sh --models"
    echo "$BODY2" | head -3 | sed 's/^/      /'
    ;;
  429)
    warn "HTTP 429 — rate limit (~40 req/min). Espera un poco y repite"
    ;;
  500)
    err "HTTP 500 — error del gateway NVIDIA (axum)"
    echo "$BODY2" | head -4 | sed 's/^/      /'
    if echo "$BODY2" | grep -qi "Missing request extension"; then
      echo "      → esto es un BEARER VACÍO: el .env no se está leyendo bien."
      echo "        Revisa que no haya CRLF ni comillas:  bash tools/env_check.sh"
    fi
    ;;
  *) err "HTTP ${CODE2:-?} — respuesta inesperada"; echo "$BODY2" | head -3 | sed 's/^/      /' ;;
esac

echo
echo "═══════════════════════════════════════════════════════════"
echo "  Si todo está en ✓, la API está lista. El siguiente paso es"
echo "  el auricular BT:   bash tools/bt_headset_pc.sh --detect"
echo "═══════════════════════════════════════════════════════════"

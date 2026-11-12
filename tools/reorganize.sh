#!/usr/bin/env bash
# =============================================================================
#  reorganize.sh — organiza el repo tonypi-mcp en las carpetas destino:
#                    pc/ · tools/ · docs/ · patches/ · robot/
#
#  REGLAS DE SEGURIDAD
#   · Nunca borra nada. Mueve y, antes de mover, deja copia en backup/<fecha>/.
#   · .env NO se toca (se queda en la raíz, chmod 600).
#   · Idempotente: si lo ejecutas dos veces, la segunda no rompe nada.
#   · --dry-run enseña el plan sin tocar un solo fichero.
#
#  USO
#   bash tools/reorganize.sh --dry-run     # ver el plan
#   bash tools/reorganize.sh               # aplicarlo
# =============================================================================
set -euo pipefail

DRY_RUN=0
ROOT=""

usage() {
  cat <<'EOF'
Uso: reorganize.sh [--dry-run] [--root RUTA]

  --dry-run   Muestra lo que haría sin modificar nada.
  --root DIR  Raíz del repo (por defecto: el directorio actual).
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --root) ROOT="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Opción desconocida: $1" >&2; usage; exit 2 ;;
  esac
done

# --- Detectar la raíz del repo ------------------------------------------------
looks_like_repo() {
  [ -n "$1" ] && [ -d "$1" ] && { [ -f "$1/voice_agent.py" ] || [ -f "$1/server.py" ] || [ -d "$1/pc" ]; }
}
if [ -z "$ROOT" ]; then
  if looks_like_repo "$(pwd)"; then
    ROOT="$(pwd)"
  elif looks_like_repo "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; then
    ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  else
    echo "ERROR: no encuentro el repo. Usa --root RUTA o cd dentro de él." >&2
    exit 1
  fi
fi
cd "$ROOT"
ROOT="$(pwd)"

# Carpeta de copia de seguridad (todo lo que se mueva se copia aquí antes)
BACKUP_DIR="$ROOT/backup/$(date +%Y%m%d-%H%M%S)"

echo "═══════════════════════════════════════════════════════════"
echo "  Repo: $ROOT"
[ "$DRY_RUN" -eq 1 ] && echo "  MODO SIMULACIÓN (--dry-run): no se toca nada"
echo "═══════════════════════════════════════════════════════════"

# --- Carpetas destino ---------------------------------------------------------
DIRS=(pc tools tools/legacy docs docs/legacy patches robot)

# --- Tabla de mapa: fichero origen -> destino ---------------------------------
# Formato: "origen|destino_relativo"
MAP=(
  # ---- runtime del PC -------------------------------------------------------
  "voice_agent.py|pc/voice_agent.py"
  "vad.py|pc/vad.py"
  "tool_parse.py|pc/tool_parse.py"
  "prompts.py|pc/prompts.py"
  "mcp_bridge.py|pc/mcp_bridge.py"
  "server.py|pc/server.py"
  "tonypi_client.py|pc/tonypi_client.py"
  # ---- herramientas ---------------------------------------------------------
  "audio_doctor.py|tools/audio_doctor.py"
  "mock_robot.py|tools/mock_robot.py"
  "selftest.py|tools/selftest.py"
  "find_robot.sh|tools/find_robot.sh"
  "nvidia_check.sh|tools/nvidia_check.sh"
  "tonypi_wifi.sh|tools/tonypi_wifi.sh"
  "diag_robot.sh|tools/diag_robot.sh"
  "deploy_to_robot.sh|tools/deploy_to_robot.sh"
  # ---- legacy: ya no aplican al diseño actual -------------------------------
  "setup_pi.sh|tools/legacy/setup_pi.sh"
  "bt_headset.sh|tools/legacy/bt_headset.sh"
  "requirements-pi.txt|docs/legacy/requirements-pi.txt"
  # ---- parches y documentación ----------------------------------------------
  "robot_patch|patches/robot_patch"
  "PLAN.md|docs/PLAN.md"
  "NVIDIA.md|docs/NVIDIA.md"
  "GUIA_WIFI.md|docs/GUIA_WIFI.md"
)

# --- Helpers ------------------------------------------------------------------
MOVED=0; SKIPPED=0; UNKNOWN=0

move_one() {
  local src="$1" dst="$2"
  if [ ! -e "$src" ]; then return 0; fi
  if [ -e "$dst" ]; then
    printf '  · SIN Mover  %-26s → %-34s (ya existe el destino)\n' "$src" "$dst"
    SKIPPED=$((SKIPPED+1))
    return 0
  fi
  printf '  ✓ MOVER      %-26s → %-34s\n' "$src" "$dst"
  if [ "$DRY_RUN" -eq 0 ]; then
    mkdir -p "$(dirname "$dst")" "$BACKUP_DIR"
    cp -a "$src" "$BACKUP_DIR/" 2>/dev/null || true
    mv "$src" "$dst"
    # los .sh deben seguir siendo ejecutables
    case "$dst" in *.sh) chmod +x "$dst" 2>/dev/null || true ;; esac
  fi
  MOVED=$((MOVED+1))
}

# --- Plan ---------------------------------------------------------------------
echo
echo "── Carpetas a crear ──────────────────────────────────────────"
for d in "${DIRS[@]}"; do
  if [ -d "$d" ]; then
    echo "  · ya existe   $d/"
  else
    echo "  + crear       $d/"
    [ "$DRY_RUN" -eq 0 ] && mkdir -p "$d"
  fi
done

echo
echo "── Ficheros a mover ───────────────────────────────────────────"
for entry in "${MAP[@]}"; do
  src="${entry%%|*}"; dst="${entry##*|}"
  move_one "$src" "$dst"
done

# --- .gitignore ---------------------------------------------------------------
GITIGNORE_ENTRIES=(".env" ".venv/" "__pycache__/" "*.pyc" "logs/" "*.log" "backup/")
echo
echo "── .gitignore ─────────────────────────────────────────────────"
if [ -f .gitignore ]; then
  for e in "${GITIGNORE_ENTRIES[@]}"; do
    if grep -qxF "$e" .gitignore 2>/dev/null; then
      echo "  · ya está     $e"
    else
      echo "  + añadir      $e"
      [ "$DRY_RUN" -eq 0 ] && printf '%s\n' "$e" >> .gitignore
    fi
  done
else
  echo "  + crear       .gitignore"
  [ "$DRY_RUN" -eq 0 ] && printf '%s\n' "${GITIGNORE_ENTRIES[@]}" > .gitignore
fi

# --- .env.example -------------------------------------------------------------
if [ ! -f .env.example ]; then
  echo
  echo "── .env.example ───────────────────────────────────────────────"
  echo "  + crear       .env.example"
  if [ "$DRY_RUN" -eq 0 ]; then
    cat > .env.example <<'EOF'
# Plantilla. Copia a .env y rellena. NUNCA subas .env al repo ni lo copies al robot.
NVIDIA_API_KEY=nvapi-TU_CLAVE_AQUI
LLM_MODEL=nvidia/nemotron-3.5-bolt-e4b

# Audio (los escribe tools/bt_headset_pc.sh)
ASR_BACKEND=whispercpp
ASR_DEVICE=bluez_input.XX.XX.XX.XX.XX.mono
TTS_DEVICE=bluez_output.XX.XX.XX.XX.XX

# Robot
ROBOT_HOST=192.168.149.1
ROBOT_RPC_PORT=9030
ROBOT_HTTP_PORT=8080
ROBOT_UNLOAD_ON_START=1
EOF
  fi
fi

# --- .env: no se mueve, pero se avisa de sus permisos --------------------------
echo
echo "── .env ──────────────────────────────────────────────────────"
if [ -f .env ]; then
  PERMS="$(stat -c '%a' .env 2>/dev/null || echo '?')"
  if [ "$PERMS" != "600" ]; then
    warn_msg="  ! .env tiene permisos $PERMS (deberían ser 600)"
    echo "$warn_msg"
    echo "    chmod 600 .env        # en WSL sobre /mnt/c no aplica: NTFS no tiene permisos POSIX"
  else
    echo "  · .env con permisos 600 ✓"
  fi
else
  echo "  · no hay .env en la raíz (créalo con: cp .env.example .env && chmod 600 .env)"
fi

# --- Instalar los ficheros de este paquete -----------------------------------
PKG="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
install_pkg() {
  local rel="$1"
  [ -f "$PKG/$rel" ] || return 0
  local dst="$ROOT/$rel"
  if [ -e "$dst" ]; then
    printf '  · ya existe   %s\n' "$rel"; return 0
  fi
  printf '  + instalar    %s\n' "$rel"
  [ "$DRY_RUN" -eq 0 ] && { mkdir -p "$(dirname "$dst")"; cp "$PKG/$rel" "$dst"; }
}
echo
echo "── Ficheros del paquete ──────────────────────────────────────"
install_pkg "docs/ESTRUCTURA-PROYECTO.md"
install_pkg "docs/GUIA-DESPLIEGUE.md"
install_pkg "tools/bt_headset_pc.sh"
install_pkg "tools/env_check.sh"
install_pkg "tools/check_repo.sh"
install_pkg "tools/wslg_check.sh"
install_pkg "robot/TonyPi_rpc_only.py"
install_pkg "robot/tonypi-rpc.service"

# --- Ficheros sin clasificar -------------------------------------------------
echo
echo "── Sin clasificar (revísalos a mano) ──────────────────────────"
for f in * .[!.]*; do
  [ -f "$f" ] || continue
  case "$f" in
    .env|.env.example|.gitignore|README.md|requirements.txt|pyproject.toml|backup) continue ;;
  esac
  found=0
  for entry in "${MAP[@]}"; do
    [ "${entry%%|*}" = "$f" ] && found=1 && break
  done
  [ "$found" -eq 1 ] && continue
  printf '  ? %s\n' "$f"
  UNKNOWN=$((UNKNOWN+1))
done
[ "$UNKNOWN" -eq 0 ] && echo "  (ninguno)"

# --- Resumen ------------------------------------------------------------------
echo
echo "═══════════════════════════════════════════════════════════"
printf "  Movidos: %d   ·   Omitidos: %d   ·   Sin clasificar: %d\n" "$MOVED" "$SKIPPED" "$UNKNOWN"
if [ "$DRY_RUN" -eq 0 ]; then
  echo "  Copia de seguridad en: $BACKUP_DIR"
  echo
  echo "  SIGUIENTE PASO:  bash tools/bt_headset_pc.sh --detect"
else
  echo
  echo "  (simulación) ejecuta de nuevo sin --dry-run para aplicarlo"
fi
echo "═══════════════════════════════════════════════════════════"

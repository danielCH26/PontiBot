#!/usr/bin/env bash
# =============================================================================
#  check_repo.sh — ¿estoy en la raíz correcta del proyecto y en qué estado está?
#
#  Útil justo después de descomprimir el kit: te dice si el repo está donde
#  debe, si ya está reorganizado y cuál es el siguiente comando.
#
#  USO
#    bash tools/check_repo.sh
#    bash tools/check_repo.sh /ruta/al/repo
# =============================================================================
set -uo pipefail

ROOT="${1:-$(pwd)}"
cd "$ROOT" 2>/dev/null || { echo "No existe el directorio: $ROOT"; exit 1; }
ROOT="$(pwd)"

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
err()  { printf '  \033[31m✗\033[0m %s\n' "$*"; }

echo "═══════════════════════════════════════════════════════════"
echo "  Repo: $ROOT"
echo "═══════════════════════════════════════════════════════════"

# --- 1. ¿Es un repo del proyecto? ---------------------------------------------
echo
echo "1. Ficheros del proyecto"
CORE=(voice_agent.py server.py vad.py prompts.py)
en_raiz=0; en_pc=0; faltan=()
for f in "${CORE[@]}"; do
  if [ -f "$f" ]; then en_raiz=$((en_raiz+1)); ok "$f (en la raíz)"
  elif [ -f "pc/$f" ]; then en_pc=$((en_pc+1)); ok "pc/$f (ya reorganizado)"
  else faltan+=("$f")
  fi
done
for f in "${faltan[@]:-}"; do [ -n "$f" ] && warn "$f NO aparece"; done

if [ "${#faltan[@]}" -gt 0 ] && [ "$en_raiz" -eq 0 ] && [ "$en_pc" -eq 0 ]; then
  err "Esto NO parece el repo tonypi-mcp."
  echo "     ¿Estás en la raíz correcta? Debe contener voice_agent.py y server.py."
  echo "     cd /ruta/a/tu/tonypi-mcp"
fi

# --- 2. Estado de la reorganización -------------------------------------------
echo
echo "2. Estado de la reorganización"
if [ "$en_pc" -gt 0 ] && [ "$en_raiz" -eq 0 ]; then
  ok "REORGANIZADO (el runtime ya está en pc/)"
  ESTADO="reorganizado"
elif [ "$en_raiz" -gt 0 ]; then
  warn "SIN REORGANIZAR (el runtime está en la raíz)"
  ESTADO="sin_reorganizar"
else
  ESTADO="desconocido"
fi

for d in pc tools docs robot patches; do
  if [ -d "$d" ]; then ok "$d/"; else warn "$d/ no existe"; fi
done

# --- 3. Kit de despliegue ------------------------------------------------------
echo
echo "3. Kit de despliegue"
for f in tools/reorganize.sh tools/env_check.sh tools/bt_headset_pc.sh \
         docs/GUIA-DESPLIEGUE.md docs/ESTRUCTURA-PROYECTO.md; do
  if [ -f "$f" ]; then ok "$f"; else warn "$f falta → descomprime el zip en la raíz del repo"; fi
done

# --- 3b. ¿La documentación referencia ficheros que no existen? ----------------
echo
echo "3b. Referencias de la documentación"
missing=0
for doc in README.md docs/*.md; do
  [ -f "$doc" ] || continue
  # se eliminan antes las URLs: sus rutas no son ficheros locales
  refs=$(sed -E 's#https?://[^ )"<>]+##g' "$doc" 2>/dev/null | \
         grep -ohE '(tools|docs|patches|robot|tests)/[a-zA-Z0-9_./-]+\.(sh|py|md|html|service)' | sort -u)
  for r in $refs; do
    if [ ! -f "$r" ]; then
      echo "  ✗ $doc  →  $r  NO EXISTE"
      missing=$((missing+1))
    fi
  done
done
if [ "$missing" -eq 0 ]; then
  ok "todas las rutas citadas en la documentación existen"
else
  err "$missing referencia(s) rotas en la documentación"
fi

# --- 4. Entorno del PC ---------------------------------------------------------
echo
echo "4. Entorno del PC"
if [ -d .venv ]; then
  if [ -x .venv/bin/python3 ]; then
    ok ".venv → $(.venv/bin/python3 -V 2>&1 | awk '{print $2}')"
    PYV=$(.venv/bin/python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null)
    if [ -n "$PYV" ]; then
      MAJ=${PYV%%.*}; MIN=${PYV##*.}
      if [ "$MAJ" -eq 3 ] && [ "$MIN" -ge 10 ]; then ok "Python >= 3.10 ✓ (el SDK mcp lo exige)"
      else err "Python $PYV < 3.10 → el SDK 'mcp' NO se puede instalar"; fi
    fi
    if .venv/bin/python -c "import mcp" 2>/dev/null; then
      ok "SDK mcp instalado → $(.venv/bin/pip show mcp 2>/dev/null | awk '/^Version/{print $2}')"
    else
      err "el SDK 'mcp' no está en el venv"
      echo "      source .venv/bin/activate && pip install -r requirements.txt"
    fi
  else
    err ".venv existe pero no tiene .venv/bin/python3"
  fi
else
  warn "no hay .venv → python3 -m venv .venv && source .venv/bin/activate"
fi

if [ -f .env ]; then
  PERMS=$(stat -c '%a' .env 2>/dev/null || echo '?')
  [ "$PERMS" = "600" ] && ok ".env (600 ✓)" || warn ".env tiene permisos $PERMS → chmod 600 .env"
else
  warn "no hay .env → cp .env.example .env && chmod 600 .env"
fi

if [ -d .git ]; then
  ok "git: repo versionado (vuelta atrás con 'git checkout .')"
else
  warn "sin git → tu vuelta atrás es backup/<fecha>/ (lo deja reorganize.sh)"
  echo "      opcional:  git init && git add -A && git commit -m 'antes de reorganizar'"
fi

# --- 5. Qué hacer ahora -------------------------------------------------------
echo
echo "═══════════════════════════════════════════════════════════"
case "$ESTADO" in
  reorganizado)
    echo "  SIGUIENTE:"
    echo "    bash tools/env_check.sh            # audita el .env"
    echo "    bash tools/bt_headset_pc.sh --detect"
    ;;
  sin_reorganizar)
    echo "  SIGUIENTE:"
    echo "    bash tools/reorganize.sh --dry-run   # mira el plan"
    echo "    bash tools/reorganize.sh             # aplícalo"
    ;;
  *)
    echo "  No se ha detectado el repo. Sitúate en la raíz y repite:"
    echo "    cd /ruta/a/tu/tonypi-mcp && bash tools/check_repo.sh"
    ;;
esac
echo "═══════════════════════════════════════════════════════════"

# Estructura del proyecto TonyPi · qué va en el PC y qué va en el bot

> Versión 1.0 · 2026-11-09 · coherente con el diagrama `arquitectura-bot-tonypi.html`

---

## 1. La regla de oro

> **El robot no ejecuta una sola línea de nuestro proyecto. El PC lo hace todo.**

Consecuencia práctica: el directorio del bot queda **prácticamente vacío** de código nuestro. Lo único que
instalamos en el robot es, opcionalmente, un servicio propio que arranque el JSON-RPC sin el programa de
prueba de fábrica (ver §6 y `GUIA-DESPLIEGUE.md` fase 5).

El motivo es doble y ya está verificado:

| Hecho verificado | Consecuencia |
|---|---|
| El SDK `mcp` exige Python ≥ 3.10; el robot tiene Raspbian Buster (Python 3.7) | El MCP server no puede vivir en el robot |
| El robot solo aporta un servidor JSON-RPC ya hecho, en `:9030` | No hace falta escribirle código: basta hablarle su idioma |

---

## 2. Árbol real (este repo ya viene organizado)

```
pontibot/                          ← RAÍZ (el repo, en tu PC)
│
├── README.md                       ← índice: empieza por aquí
├── .env                            ← SOLO PC · chmod 600 · contiene la clave real
├── .env.example                    ← plantilla sin secretos (SÍ al repo)
├── .gitignore
├── requirements.txt                ← dependencias del PC (Python ≥ 3.10)
├── requirements-pi.txt             ← legacy: para el robot (Python 3.7)
│
├── pc/                             ← ════ TODO EL CÓDIGO QUE SE EJECUTA ════
│   ├── voice_agent.py              ← orquestador: VAD → ASR → LLM → tools → TTS
│   ├── server.py                   ← SERVIDOR MCP · expone las 26 tools del robot
│   ├── mcp_bridge.py               ← cliente MCP (SDK `mcp`, exige Python ≥ 3.10)
│   ├── tonypi_client.py            ← cliente JSON-RPC del robot (habla con :9030)
│   ├── vad.py                      ← captura (parecord/arecord) y salida (paplay/aplay)
│   ├── prompts.py                  ← prompt del sistema (responde en español)
│   ├── tool_parse.py               ← parsea las tool calls de bolt-e4b
│   ├── memory.py                   ← memoria conversacional
│   ├── storage.py                  ← persistencia en disco
│   ├── nvidia_models.py            ← cliente/sondeo de modelos NVIDIA
│   └── audio_doctor.py             ← diagnóstico de audio
│
├── tools/                          ← ════ HERRAMIENTAS (se ejecutan en el PC) ════
│   ├── check_repo.sh               ← ¿estoy en la raíz correcta y en qué estado?
│   ├── env_check.sh                ← audita el .env (enmascara la clave)
│   ├── nvidia_check.sh             ← prueba la clave y el modelo contra la API real
│   ├── find_robot.sh               ← encuentra la IP del robot (barre el /24 en busca del :9030)
│   ├── bt_headset_pc.sh            ← auricular BT del PC → escribe el .env
│   ├── deploy_to_robot.sh          ← push al robot (parche / diseño anterior)
│   ├── tonypi_wifi.sh              ← probe / sta / ap del WiFi del robot
│   ├── mock_robot.py               ← simulador del protocolo (sin robot)
│   ├── selftest.py                 ← 28/28 checks del protocolo
│   ├── test_rpc.py                 ← prueba de RPC contra el robot
│   ├── e2e_mcp_test.py             ← prueba extremo a extremo del MCP
│   ├── nvidia_smoke_test.py        ← prueba real contra la API
│   ├── storage_doctor.py           ← diagnóstico de almacenamiento
│   ├── net_doctor.py               ← diagnóstico de red
│   ├── reorganize.sh               ← migración desde el repo plano (LEGACY)
│   └── legacy/                     ← scripts del diseño anterior
│       ├── setup_pi.sh             ← instala Python nuestro EN el robot
│       └── wifi_dongle_setup.sh
│
├── robot/                          ← ════ LO QUE SE COPIA AL ROBOT (opcional) ════
│   ├── TonyPi_rpc_only.py          ← servicio "solo RPC", sin modo de prueba
│   └── tonypi-rpc.service          ← unidad systemd que lo arranca
│
├── patches/                        ← ════ PARCHES DE FIRMWARE (se aplican EN el robot) ════
│   └── robot_patch/
│       ├── RPCServer_extra.py      ← SetBuzzer / PlayAudio / Speak
│       └── apply_patch.py          ← aplica y revierte el parche
│
├── tests/                          ← ════ TESTS ════
│   ├── test_memory.py
│   ├── test_storage.py
│   ├── test_live_memory.py
│   └── mcp_stub/mcp/               ← stub del SDK `mcp` para testear sin el SDK
│
└── docs/                           ← ════ DOCUMENTACIÓN ════
    ├── GUIA-DESPLIEGUE.md          ← la guía paso a paso
    ├── ESTRUCTURA-PROYECTO.md      ← este documento
    ├── arquitectura-bot-tonypi.html ← el diagrama
    ├── GUIA_WIFI.md
    ├── PLAN.md
    ├── NVIDIA.md
    └── legacy/                     ← guías del diseño anterior
        ├── GUIA_PASO_A_PASO.md
        ├── PASO_A_PASO.md
        ├── README.md
        ├── mcp-config.example.json
        └── nvidia_catalog.json
```

**Por qué el runtime entero vive en `pc/`**: los ficheros se importan entre sí por nombre plano
(`voice_agent` importa `vad`, `prompts`, `tool_parse`, `memory`, `tonypi_client`, `mcp_bridge`; y
`mcp_bridge` localiza `server.py` con `os.path.dirname(__file__)`). Si se separaran, los imports se
romperían. Por eso se ejecutan **desde dentro de `pc/`**:

```bash
cd pc && python3 voice_agent.py
```

Las herramientas de `tools/` y `tests/` añaden `pc/` al `sys.path` con un bloque de rutas al principio del
fichero, así que se pueden lanzar desde cualquier sitio.

---

## 3. Mapa de ficheros (reparto real)

| Fichero | Dónde está | Por qué |
|---|---|---|
| `voice_agent.py` | `pc/` | Es el runtime; hace audio + API, luego solo en el PC |
| `server.py` | `pc/` | El MCP server corre en el PC (el SDK `mcp` exige Python ≥ 3.10) |
| `mcp_bridge.py` | `pc/` | Importa el SDK `mcp` → nunca en el robot (Python 3.7) |
| `tonypi_client.py` | `pc/` | Cliente del `:9030`; lo consume `server.py` |
| `vad.py`, `prompts.py`, `tool_parse.py`, `memory.py`, `storage.py` | `pc/` | Dependencias directas del agente |
| `nvidia_models.py`, `audio_doctor.py` | `pc/` | Dependen de `vad`/`prompts` → misma carpeta |
| `mock_robot.py` | `tools/` | Simulador para desarrollar sin robot |
| `selftest.py`, `test_rpc.py`, `e2e_mcp_test.py`, `nvidia_smoke_test.py`, `storage_doctor.py`, `net_doctor.py` | `tools/` | Utilidades de verificación |
| `deploy_to_robot.sh`, `tonypi_wifi.sh` | `tools/` | Operan sobre el robot por SSH, desde el PC |
| `nvidia_check.sh`, `find_robot.sh`, `check_repo.sh`, `env_check.sh`, `bt_headset_pc.sh` | `tools/` | Utilidades de diagnóstico del PC (las escribimos para este despliegue) |
| `setup_pi.sh`, `wifi_dongle_setup.sh` | `tools/legacy/` | Instalaban nuestro Python **en el robot**: ya no aplica |
| `robot_patch/` | `patches/robot_patch/` | Lo único que se aplica dentro del firmware del robot |
| `tests/` | `tests/` | Tests del agente + stub del SDK `mcp` |
| `PLAN.md`, `NVIDIA.md`, `GUIA_WIFI.md` | `docs/` | Documentación |
| `GUIA_PASO_A_PASO.md`, `PASO_A_PASO.md`, `README.md` viejo | `docs/legacy/` | Guías del diseño anterior (el agente en el robot) |
| `.env` | raíz | **Solo PC.** Clave real, permisos 600 |
| `.env.example` | raíz | Plantilla sin secretos |

## 4. Rutas absolutas en cada máquina

### Tu PC

> `REPO` = la carpeta donde descomprimiste este zip. Ejemplo en WSL:
> `export REPO=/mnt/c/Users/Arias/Desktop/UPB/TonyPiRV3/pontibot`

| Qué | Ruta |
|---|---|
| Repo | `$REPO` (la carpeta `pontibot/`) |
| `.env` (secretos) | `$REPO/.env` |
| Entorno virtual | `$REPO/.venv` (crear dentro del repo) |
| Memoria del agente | `~/.pontibot/memory.json` → en WSL: `/root/.pontibot/memory.json` |
| Logs | `~/.pontibot/agent.log` |

> La memoria del agente (`PONTIBOT_MEMORY`) es portable gracias a `expanduser`: ahora vive en el PC y en el
> robot queda la copia vieja (bórrala, ver fase 7 de la guía).

### El robot (TonyPi v1.0, Raspbian Buster)

| Qué | Ruta | Nota |
|---|---|---|
| Código de fábrica | `/home/pi/TonyPi/` | **Intocable** (salvo el parche) |
| Servicio de fábrica | `/etc/systemd/system/tonypi.service` | **Debe seguir activo**: aloja el JSON-RPC |
| Patch de firmware | `/home/pi/TonyPi/robot_patch/` | Solo si activas el buzzer/audio del robot |
| Servicio "solo RPC" (opcional) | `/home/pi/TonyPi/TonyPi_rpc_only.py` + `/etc/systemd/system/tonypi-rpc.service` | Ver fase 5 |
| Config de WiFi | `~/hiwonder-toolbox/wifi_conf.py` | `HW_WIFI_MODE` debe quedar como **entero** |
| **Nuestro código** | — | **Nada.** El bot no aloja nada nuestro |

---

## 5. Secretos y `.gitignore`

> Si no usas git, este fichero no hace nada por ahora — **no lo borres**: en cuanto hagas `git init`
> ya estará protecting la clave. Y no pasa nada si no lo tienes: la clave vive en `.env`, fuera del zip.

El `.gitignore` debe cubrir como mínimo:

```
.env
.venv/
__pycache__/
*.pyc
logs/
*.log
```

Y el `.env` del PC debe llevar (600):

```bash
NVIDIA_API_KEY=nvapi-...
LLM_MODEL=nvidia/nemotron-3.5-bolt-e4b
ASR_BACKEND=whispercpp          # o openai
ASR_DEVICE=bluez_input.XX.XX.XX.XX.XX.mono
TTS_DEVICE=bluez_output.XX.XX.XX.XX.XX
ROBOT_HOST=192.168.149.1        # o la IP en LAN
ROBOT_RPC_PORT=9030
ROBOT_HTTP_PORT=8080
```

> `ASR_DEVICE` / `TTS_DEVICE` los escribe `tools/bt_headset_pc.sh` en tu PC. Antes estaban pensados para el
> robot: **cambian de sitio**.

---

## 6. Qué NO va al bot, y por qué

| No va al bot | Por qué |
|---|---|
| `server.py` (MCP server) | El SDK `mcp` exige Python ≥3.10; el robot tiene 3.7 |
| `voice_agent.py`, `vad.py` | El audio (micro y bocina) lo hace el PC |
| `mcp_bridge.py` | Ídem: importa el SDK `mcp` |
| `.env` con la clave NVIDIA | La API se llama desde el PC. **Clave fuera del robot** = fuera de un posible 403 por ruta de salida y fuera del disco del robot |
| `setup_pi.sh`, `requirements-pi.txt` | No hay Python nuestro que instalar |
| `bt_headset.sh` (el del robot) | El auricular BT se empareja y usa desde el PC |

Lo único que sí va al bot:

| Sí va al bot | Por qué |
|---|---|
| `patches/robot_patch/` (opcional) | Añade `SetBuzzer`/`PlayAudio`/`Speak` al firmware; el firmware oficial no los tiene |
| `robot/TonyPi_rpc_only.py` + unidad (opcional) | Arranca el JSON-RPC **sin** el programa de juego de fábrica → elimina el "modo de prueba" de raíz |

---

## 7. Cómo ejecutar (resumen)

```bash
export REPO=/ruta/a/tu/tonypi-mcp     # ajústala
cd "$REPO"

# 0) comprobar que estás en la raíz correcta
bash tools/check_repo.sh

# 1) reorganizar (una vez)
bash tools/reorganize.sh --dry-run     # ver el plan
bash tools/reorganize.sh                # aplicarlo

# 2) entorno y configuración
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && chmod 600 .env && $EDITOR .env

# 3) auricular BT (escribe ASR_DEVICE / TTS_DEVICE en el .env)
bash tools/bt_headset_pc.sh --detect

# 4) arrancar el agente
cd pc && python3 voice_agent.py
```

El detalle completo, con verificaciones y rollback, está en **`GUIA-DESPLIEGUE.md`**.

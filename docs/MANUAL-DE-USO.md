# 📘 Manual de uso — PontiBot

> Manual completo del proyecto: cómo ponerlo en marcha, cómo hablarle al robot, cómo diagnosticarlo
> y cómo mantenerlo.
>
> **Tiempo de lectura:** ~15 min · **Nivel:** de cero a primer uso

---

## 📑 Índice

1. [Qué vas a conseguir](#1-qu%C3%A9-vas-a-conseguir)
2. [Requisitos](#2-requisitos)
3. [Puesta en marcha](#3-puesta-en-marcha)
4. [La interfaz de chat](#4-la-interfaz-de-chat)
5. [Modo voz (fase 2)](#5-modo-voz-fase-2)
6. [Usar PontiBot como servidor MCP](#6-usar-pontibot-como-servidor-mcp)
7. [Referencia de las 26 herramientas](#7-referencia-de-las-26-herramientas)
8. [Herramientas de diagnóstico](#8-herramientas-de-diagn%C3%B3stico)
9. [Matriz de fallos](#9-matriz-de-fallos)
10. [Mantenimiento](#10-mantenimiento)
11. [Glosario](#11-glosario)

---

## 1. Qué vas a conseguir

Al final de este manual tendrás:

- Un PC con PontiBot talking con un **TonyPi** real por la red local.
- Una **consola de chat** donde escribes `saluda` o `camina hacia adelante` y el robot lo hace.
- Un **servidor MCP** con 26 herramientas que puedes conectar a cualquier cliente MCP.
- Un kit de **diagnóstico** que te dice exactamente qué falla cuando algo falla.

---

## 2. Requisitos

### En el PC

| | Mínimo | Recomendado |
|---|---|---|
| **Sistema** | Linux / macOS / Windows con WSL2 | Ubuntu 22.04 o WSL2 (Win11) |
| **Python** | 3.10 | 3.11+ |
| **RAM** | 4 GB | 8 GB |
| **Red** | Misma LAN que el robot | — |

### En el robot

| | |
|---|---|
| **Robot** | TonyPi 18 DOF (Hiwonder Standard, Raspberry Pi 4B) |
| **SO** | Raspbian Buster (Python 3.7) — *el robot NO necesita el SDK `mcp`* |
| **Acceso** | SSH por el hotspot de fábrica: `ssh pi@192.168.149.1` |

### Cuentas

- **NVIDIA NIM** — gratis, hasta 40 peticiones/minuto por clave.
  Crea la clave en <https://build.nvidia.com/settings> → *Get API Key*.

---

## 3. Puesta en marcha

### 3.1 Clonar y preparar

```bash
git clone https://github.com/danielCH26/PontiBot.git
cd PontiBot
bash tools/check_repo.sh        # ¿estoy donde debo? ¿qué falta?
```

### 3.2 Entorno de Python

El SDK `mcp` exige **Python ≥ 3.10** (el robot tiene 3.7, por eso el servidor MCP vive en el PC).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3.3 Configurar el `.env`

```bash
cp .env.example .env
chmod 600 .env
$EDITOR .env
```

Las **cinco variables que de verdad importan**:

| Variable | Valor | Por qué |
|---|---|---|
| `LLM_API_KEY` | `nvapi-...` | **No** es `NVIDIA_API_KEY`. Este es el nombre que lee `pc/voice_agent.py` |
| `LLM_MODEL` | `nvidia/nemotron-3.5-bolt-e4b` | El modelo elegido (rápido y con *tool calling*) |
| `TONYPI_HOST` | `192.168.149.1` | IP del robot tal y como la ve **este** PC |
| `TONYPI_RPC_PORT` | `9030` | JSON-RPC del firmware |
| `TONYPI_MJPG_PORT` | `8080` | Snapshot JPEG de la cámara |

> 🔐 El `.env` está en `.gitignore` y **nunca** debe subirse a ningún repositorio.

Comprueba la configuración sin imprimir la clave:

```bash
bash tools/env_check.sh
```

### 3.4 Conectar el robot a la red

El robot arranca en **modo AP** (hotspot propio, `HW-<serial>` / contraseña `hiwonder`) y en ese modo
**no tiene internet**. Para PontiBot eso no importa: el robot solo necesita ser alcanzable.

```bash
bash tools/find_robot.sh              # busca el robot en la red
bash tools/set_robot_ip.sh            # escribe TONYPI_HOST y verifica :9030 y :8080
```

Si tienes el robot en modo AP, `TONYPI_HOST=192.168.149.1` funciona directamente.
Las otras cinco vías (STA nativo, Ethernet, hotspot del móvil, nmcli, dongle USB, internet desde el PC)
están en **[GUIA_WIFI.md](GUIA_WIFI.md)**.

### 3.5 Verificación final

```bash
bash tools/nvidia_check.sh            # ¿la clave funciona de verdad? (200/401/403/404/500)
bash tools/test_movimientos.sh        # ¿el robot obedece al JSON-RPC? (sin LLM)
```

Si ambos pasan, arranca el chat:

```bash
cd pc && python3 voice_agent.py --chat
```

---

## 4. La interfaz de chat

El chat es la **interfaz principal** del proyecto: texto puro, sin micrófono ni TTS necesario.

```text
pontibot> saludar
  -> robot_do_action({"action":"wave"})
     ejecutando wave x1
  pontibot: Saludo. Soy PontiBot.
```

### 4.1 Órdenes que entiende

| Orden | Qué hace | Herramienta MCP |
|---|---|---|
| `saluda` / `salude` | El robot saluda | `robot_do_action` |
| `ponte de pie` | Se levanta (sensor IMU) | `robot_stand_up` |
| `haz una reverencia` | Se inclina | `robot_do_action` |
| `camina hacia adelante` | Avanza | `robot_walk` |
| `haz una sentadilla` | Sentadilla | `robot_do_action` |
| `haz una venia` | Levanta la mano | `robot_do_action` |
| `para` | Detiene el movimiento | `robot_stop` |
| `qué ves` | Usa la cámara y lo describe | `robot_camera_snapshot` |

No hace falta memorizar la lista: **el LLM decide** qué herramienta usar. Y si quieres saber cómo
decide, el chat **muestra la llamada** antes de ejecutarla (las líneas `->`).

### 4.2 Comandos del chat

| Comando | Efecto |
|---|---|
| `/ayuda` (o `?`) | Lista de órdenes y comandos |
| `/herramientas` | Las 26 herramientas MCP disponibles |
| `/memoria` | Qué recuerda de ti |
| `/reset` | Olvida la conversación |
| `/salir` (o `Ctrl+C`) | Salir |

### 4.3 Opciones de arranque

```bash
python3 voice_agent.py --chat                  # chat por consola (interfaz principal)
python3 voice_agent.py --chat --speak          # además, lee la respuesta en voz alta
python3 voice_agent.py --text "saluda"         # una sola orden, sin bucle
python3 voice_agent.py --once                  # una sola intervención por micrófono y sale
python3 voice_agent.py --host 192.168.149.1   # fuerza la IP del robot
python3 voice_agent.py --no-memory             # cada turno empieza de cero
python3 voice_agent.py --reset-memory          # borra lo aprendido y sale
python3 voice_agent.py --max-turns 20          # ventana de contexto (por defecto 12)
```

### 4.4 La memoria

PontiBot recuerda lo que le cuentas, en `~/.pontibot/memory.json`.

```bash
python3 voice_agent.py --reset-memory   # borrar todo
```

La ruta es configurable con `PONTIBOT_MEMORY` (portable: vale igual en el PC y en el robot).

### 4.5 Leer las respuestas en voz alta

`--speak` usa el TTS configurado (`TTS_BACKEND=espeak|piper|openai`).

> ⚠️ Experimental. En Linux necesita `espeak-ng` (`sudo apt install espeak-ng`) o `piper`.
> En WSLg, el sumidero de salida es `RDPSink`; con auricular Bluetooth, `bluez_*`.

---

## 5. Modo voz (fase 2)

La interacción por voz está **implementada y documentada, pero diferida**: el diseño actual prioriza la
consola de chat porque el LLM, el ASR y el TTS viven en el PC y la voz añade latencia.

```bash
python3 voice_agent.py            # habla al micrófono, responde por el altavoz
```

Cadena completa: `micrófono → VAD → ASR → LLM + tools → TTS → altavoz`.

| Pieza | Alternativas | Nota |
|---|---|---|
| **VAD** | `webrtcvad` | Umbral `VAD_THRESHOLD` (0.012 por defecto) |
| **ASR** | `whispercpp` (local) · `local_server` · `openai` | El catálogo de NVIDIA **no** incluye ASR |
| **TTS** | `piper` (natural) · `espeak` (robótico, offline) · `openai` | `piper` da la mejor voz |

Si el bot no te oye:

```bash
bash tools/audio_probe.sh     # mide el RMS real del micrófono
bash tools/wslg_check.sh      # si estás en WSL: ¿hay servidor PulseAudio?
bash tools/bt_headset_pc.sh --detect   # auricular BT → escribe ASR_DEVICE / TTS_DEVICE
```

> 💡 En WSLg el micrófono es `RDPSource` y el altavoz `RDPSink`. La lógica de `pc/vad.py` detecta
> ambos automáticamente; no los fuerces a mano salvo que `audio_probe.sh` lo pida.

---

## 6. Usar PontiBot como servidor MCP

`pc/server.py` es un servidor MCP estándar sobre `stdio`: puedes conectarlo a **Claude Desktop**,
**Claude Code**, un IDE o cualquier cliente MCP.

```bash
cd pc && python3 server.py
```

Configuración de ejemplo (Claude Desktop → `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "pontibot": {
      "command": "python3",
      "args": ["/ruta/absoluta/al/PontiBot/pc/server.py"],
      "env": {
        "TONYPI_HOST": "192.168.149.1",
        "TONYPI_RPC_PORT": "9030",
        "TONYPI_MJPG_PORT": "8080"
      }
    }
  }
}
```

Plantilla lista: [docs/legacy/mcp-config.example.json](legacy/mcp-config.example.json).

---

## 7. Referencia de las 26 herramientas

### Estado y diagnóstico

| Herramienta | Qué hace |
|---|---|
| `robot_ping` | Comprueba que el robot está encendido y responde |
| `robot_status` | Conectividad, función de visión cargada y estado del firmware |
| `robot_list_actions` | Lista los *action groups* disponibles, agrupados por categoría |

### Movimiento

| Herramienta | Qué hace |
|---|---|
| `robot_do_action` | Ejecuta un *action group* por su nombre (`wave`, `bow`, `sit_down`…) |
| `robot_walk` | Camina: `forward`, `backward`, `left`, `right`; también `turn_left`/`turn_right` |
| `robot_stop` | Detiene la acción en curso y para el movimiento |
| `robot_look` | Orienta la cabeza: `pan` y `tilt` (cámara de 2 GDL) |
| `robot_stand_up` | Levanta al robot si está caído, usando el sensor IMU |

### Servos

| Herramienta | Qué hace |
|---|---|
| `robot_read_servos` | Lee la posición actual (0–500) de los 16 servos del cuerpo |
| `robot_set_body_servo` | Control de bajo nivel de un servo (1–16, pulso 0–500, 250 = centro) |
| `robot_power_down_servos` | Corta la alimentación de los servos |

### Visión

| Herramienta | Qué hace |
|---|---|
| `robot_start_vision` | Arranca una función de visión (`color`, `face`, `apriltag`…) |
| `robot_stop_vision` | Detiene y descarga la función de visión activa |
| `robot_vision_status` | Qué función de visión está corriendo |
| `robot_read_camera_rgb` | Lee el color que la cámara está viendo ahora mismo |
| `robot_camera_snapshot` | Captura la imagen de la cámara y la devuelve (para que la vea el LLM) |

### Color y detección

| Herramienta | Qué hace |
|---|---|
| `robot_set_color_threshold` | Ajusta el umbral LAB con el que el robot reconoce un color |
| `robot_get_color_thresholds` | Devuelve los umbrales LAB memorizados |
| `robot_set_detection_point` | Fija el punto objetivo de la detección (coordenadas de imagen) |
| `robot_set_detection_threshold` | Ajusta el umbral de área/color para `kick_ball`, `line_follow`… |

### Audio y archivos

| Herramienta | Qué hace |
|---|---|
| `robot_beep` | Pitido en el buzzer (frecuencia 1000–3000 Hz) |
| `robot_play_audio` | Reproduce un archivo de sonido del robot |
| `robot_say` | Hace que el robot diga un texto (requiere el parche opcional) |
| `robot_list_audio` | Lista los ficheros de audio reproducibles |
| `robot_list_files` | Lista ficheros de un disco o carpeta montada en el robot |
| `robot_read_file` | Lee el contenido de un fichero de texto del robot |

> ⚠️ `robot_beep`, `robot_play_audio` y `robot_say` necesitan el parche opcional del firmware:
> [`patches/robot_patch/apply_patch.py`](../patches/robot_patch/apply_patch.py). Es reversible.

---

## 8. Herramientas de diagnóstico

| Script | Para qué |
|---|---|
| `tools/check_repo.sh` | ¿Estoy en la raíz correcta? ¿Qué pasos quedan? |
| `tools/env_check.sh` | Audita el `.env` (permisos, CRLF, clave, modelo, audio, robot) **sin mostrar la clave** |
| `tools/nvidia_check.sh` | Prueba la clave **contra la API real** y clasifica 200/401/403/404/500 |
| `tools/find_robot.sh` | Encuentra la IP del robot (barrido de red + búsqueda por MAC) |
| `tools/set_robot_ip.sh` | Escribe `TONYPI_HOST`, actualiza el alias SSH y verifica `:9030` y `:8080` |
| `tools/test_movimientos.sh` | Batería de movimientos por JSON-RPC, **sin LLM** (para aislar fallos) |
| `tools/audio_probe.sh` | Mide el RMS del micro y dice si el VAD te oye |
| `tools/bt_headset_pc.sh` | Detecta el auricular BT y escribe `ASR_DEVICE`/`TTS_DEVICE` (`--list`, `--detect`, `--test`) |
| `tools/wslg_check.sh` | Diagnostica por qué no hay audio en WSL y dice qué hacer |
| `tools/net_doctor.py` | Estado de red del robot |
| `tools/storage_doctor.py` | Estado del almacenamiento del robot |
| `tools/tonypi_wifi.sh` | Configura el WiFi del robot: `probe`, `sta`, `ap`, `status` |

### Verificación sin robot

Cada script **levanta el simulador por su cuenta** (no hace falta arrancar `mock_robot.py` a mano):

```bash
python3 tools/selftest.py         # 28/28 checks
python3 tests/test_memory.py      # 32 checks
python3 tests/test_storage.py     # 34 checks
python3 tools/e2e_mcp_test.py     # 33 checks, extremo a extremo
```

---

## 9. Matriz de fallos

| Síntoma | Causa | Solución |
|---|---|---|
| `E04 - Operation timeout!` | El robot tiene una **función de juego** cargada; el hilo principal está ocupado y las RPC expiran | `UnloadFunc` (ver abajo). Es idempotente |
| `Authorization: Bearer ` vacío | La clave no se leyó del `.env` | `bash tools/env_check.sh`; comprueba `LLM_API_KEY` y que no hay CRLF |
| `Missing request extension … axum::Extension` | **No es un error del TonyPi**: es el gateway de NVIDIA con el *bearer* vacío | Igual que el anterior |
| HTTP 403 en `/v1/chat/completions` **desde el robot** | WAF de NVIDIA bloqueando la ruta de salida | El LLM se llama **desde el PC**, nunca desde el robot |
| HTTP 401 | Clave caducada o mal pegada | Regenérala en build.nvidia.com |
| HTTP 404 con un modelo listado | El catálogo de NVIDIA **miente**: lista 85 modelos, algunos dan 404 | `python3 tools/nvidia_models.py` sondea de verdad |
| El robot responde pero **no se mueve** | `bolt-e4b` escribe las llamadas como **texto plano** | `pc/tool_parse.py` lo compensa; no lo elimines |
| El robot contesta en **indonesio** | Ese es el idioma por defecto del modelo | `LLM_LANGUAGE=es` + el prompt de `pc/prompts.py` |
| `GetRunningFunc` siempre devuelve 0 | Está hardcodeado en el firmware | `pc/server.py` lleva su propio registro de visión activa |
| `read_servo_positions` da timeout | El bus de servos no responde (servos sin alimentar) | Alimenta los servos; no bloquea el resto de órdenes |
| Sin internet en el robot | Está en modo AP | **No importa**: el robot no sale a internet. Ver [GUIA_WIFI.md](GUIA_WIFI.md) |
| `apt install` falla con `Temporary failure resolving` | Es **DNS**, no son los repositorios | `setup_pi.sh --fix-repos` ( Buster archivado) |
| `pip` no encuentra `webrtcvad` | La última versión exige Python ≥ 3.10 | Usa `requirements-pi.txt` (fija la 2.0.14, con wheel cp37) |
| El bot no te oye | El micro no está en ALSA (p. ej. auricular BT o WSLg) | `bash tools/audio_probe.sh` |
| `robot_say` no dice nada | El firmware oficial no tiene `Speak` | Aplica el parche opcional |

### Fix-up del "modo de prueba" del firmware

```bash
curl -s -X POST http://192.168.149.1:9030/ -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"UnloadFunc","params":[],"id":1}'
# → {"jsonrpc":"2.0","result":[true,[0]],"id":1}
```

> ⚠️ **Nunca** hagas `systemctl stop tonypi.service`: ese proceso *aloja* el JSON-RPC (`:9030`) y el
> stream MJPG (`:8080`). Para quitar el modo de prueba de raíz existe el servicio opcional
> `tonypi-rpc.service` en [`robot/`](../robot/), que arranca el firmware sin el juego.

---

## 10. Mantenimiento

### Actualizar PontiBot

```bash
git pull
bash tools/check_repo.sh
bash tools/env_check.sh
```

### Ver el log de la memoria

```bash
cat ~/.pontibot/memory.json | python3 -m json.tool
```

### Copia de seguridad del `.env`

```bash
install -m 600 .env ~/pontibot.env.backup
```

> El `.env` contiene la clave. Guárdalo fuera del repositorio y con permisos `600`.

### Parche opcional del firmware (buzzer / audio / hablar)

```bash
# 1. Copia al robot
scp -r patches/robot_patch/ pi@192.168.149.1:~/

# 2. Aplícalo
ssh pi@192.168.149.1 'cd ~/robot_patch && python3 apply_patch.py'

# 3. Deshazlo si algo falla
ssh pi@192.168.149.1 'cd ~/robot_patch && python3 apply_patch.py --revert'
```

### Servicio "solo RPC" en el robot (elimina el modo de prueba)

```bash
scp robot/TonyPi_rpc_only.py robot/tonypi-rpc.service pi@192.168.149.1:~/tonypi/
ssh pi@192.168.149.1 'sudo cp ~/tonypi/TonyPi_rpc_only.py /home/pi/TonyPi/'
ssh pi@192.168.149.1 'sudo cp ~/tonypi/tonypi-rpc.service /etc/systemd/system/'
ssh pi@192.168.149.1 'sudo systemctl enable --now tonypi-rpc'
```

---

## 11. Glosario

| Término | Significado |
|---|---|
| **MCP** | Model Context Protocol — protocolo estándar para exponer herramientas a un LLM |
| **Tool calling** | Capacidad del modelo de pedir que se ejecute una función con argumentos |
| **JSON-RPC 2.0** | Protocolo con el que el firmware de Hiwonder expone las órdenes del robot |
| **Action group** | Movimiento pregrabado del firmware: `wave`, `bow`, `chest`, `squat`, `push_ups`… |
| **IMU** | Sensor de inclinación; sirve para saber si el robot está de pie |
| **LAB** | Espacio de color que usa el robot para detectar colores |
| **AprilTag** | Etiqueta visual para localización/poses |
| **VAD** | Voice Activity Detection — detecta cuándo el usuario está hablando |
| **ASR / TTS** | Reconocimiento de voz / síntesis de voz |
| **WSLg** | Capa de gráficos y audio de WSL2 en Windows 11 |

---

> ¿Encontraste algo que no está en este manual? [Abre una issue](https://github.com/danielCH26/PontiBot/issues) — o
> mira [GUIA-DESPLIEGUE.md](GUIA-DESPLIEGUE.md) para el detalle paso a paso del despliegue.

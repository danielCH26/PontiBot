# PontiBot — el TonyPi con personalidad y memoria

Convierte el **TonyPi de Hiwonder** en **PontiBot**, un servidor de herramientas
**MCP** con voz y memoria, para que cualquier agente con LLM (Claude, ChatGPT con
function calling, un agente propio…) le pueda ordering cosas: moverse, saludar,
mirar a un rostro, seguir un color, chutar un balón o describir lo que ve.

La gracia: **no hay que tocar el robot**. El TonyPi ya publica un servidor
JSON-RPC 2.0 desde su servicio `tonypi.service`. Este proyecto solo lo traduce
a MCP.

---

## 1. Cómo funciona

```
  Claude / Claude Code / cualquier cliente MCP
                │  (stdio, protocolo MCP)
                ▼
        server.py  ← servidor MCP (20 herramientas)
                │  (JSON-RPC 2.0 sobre HTTP, puerto 9030)
                ▼
        ┌───────────────────────────┐
        │  TonyPi (Raspberry Pi)    │
        │  · TonyPi.py (systemd)    │
        │  · RPCServer.py :9030     │
        │  · MjpgServer.py :8080    │
        │  · OpenCV + MediaPipe     │
        │  · 117 action groups      │
        └───────────────────────────┘
```

El servidor MCP puede vivir en tu PC, en un servidor, o en la propia Raspberry
Pi del robot. El robot solo tiene que estar encendido y en la misma red.

| Recurso | Puerto | Qué es |
|---|---|---|
| JSON-RPC | 9030 | Control: acciones, servos, visión, umbrales |
| MJPEG / snapshot | 8080 | `/?action=snapshot` devuelve un JPEG de lo que ve la cámara |

---

## 2. Instalación

```bash
cd tonypi-mcp
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export TONYPI_HOST=192.168.1.50      # la IP del robot
python test_rpc.py $TONYPI_HOST      # comprueba que responde
```

Sin robot a mano? Levanta el simulador, que replica el protocolo exacto:

```bash
python mock_robot.py
export TONYPI_HOST=127.0.0.1
python selftest.py                   # 24 comprobaciones, 0 fallos
```

---

## 3. Configurar el cliente MCP

Copia `mcp-config.example.json` a la configuración de tu cliente y ajusta
`TONYPI_HOST` y las rutas.

**Claude Desktop** — `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "pontibot": {
      "command": "python3",
      "args": ["/ruta/absoluta/al/tonypi-mcp/server.py"],
      "env": {
        "TONYPI_HOST": "192.168.1.50",
        "PYTHONPATH": "/ruta/absoluta/al/tonypi-mcp"
      }
    }
  }
}
```

**Claude Code**:

```bash
claude mcp add pontibot \
  --env TONYPI_HOST=192.168.1.50 \
  -- python /ruta/absoluta/al/tonypi-mcp/server.py
```

El servidor MCP usa **stdio**, así que cualquier cliente MCP vale.

---

## 4. Catálogo de herramientas

| Herramienta | Qué hace |
|---|---|
| `robot_ping` | Comprueba que el robot responde |
| `robot_status` | Conectividad, visión activa, nº de acciones |
| `robot_list_actions` | Lista los 117 action groups disponibles |
| `robot_do_action(action, times)` | Ejecuta cualquier action group (`wave`, `bow`, `chest`, `push_ups`…) |
| `robot_walk(direction, steps)` | `forward`, `backward`, `left`, `right`, `turn_left`, `turn_right` |
| `robot_stop` | Detiene el movimiento |
| `robot_look(pan, tilt)` | Orienta la cabeza (500-2500, 1500 = centro) |
| `robot_read_servos` | Lee los 16 servos del cuerpo |
| `robot_set_body_servo(id, pulse)` | Control de bajo nivel de un servo |
| `robot_start_vision(mode)` | Carga una función de visión |
| `robot_stop_vision` | Descarga la visión activa |
| `robot_vision_status` | Qué visión está corriendo |
| `robot_set_color_threshold(...)` | Ajusta el umbral LAB de un color |
| `robot_get_color_thresholds` | Lee los umbrales memorizados |
| `robot_read_camera_rgb(mode)` | El color que la cámara está viendo |
| `robot_set_detection_point(mode, x, y)` | Fija el punto objetivo |
| `robot_set_detection_threshold(mode, value)` | Ajusta el umbral de detección |
| `robot_stand_up` | Se levanta tras una caída (IMU) |
| `robot_camera_snapshot` | **Devuelve la imagen de la cámara** (para modelos multimodales) |
| `robot_power_down_servos` | Corta la alimentación de los servos |
| `robot_beep(frequency, repeat)` | Pitido en el buzzer *(requiere el parche opcional)* |
| `robot_play_audio(name)` | Reproduce un `.wav` del directorio `audio/` *(requiere el parche opcional)* |
| `robot_say(text, backend)` | Hace que el robot diga un texto *(requiere el parche opcional)* |

> Las tres últimas **no vienen en el firmware oficial**. Se añaden con el parche
> reversible de `robot_patch/apply_patch.py`.

### Modos de visión

| Modo | Código | Qué hace |
|---|---|---|
| `face_detect` | 6 | Barre la cabeza y saluda a quien ve |
| `color_track` | 5 | Sigue un color con PID |
| `line_follow` | 4 | Sigue una línea |
| `kick_ball` | 2 | Chuta solo con visión |
| `apriltag` | 7 | Detecta tags AprilTag |
| `transport` | 8 | Mueve objetos |
| `gesture` | 3 | Responde a gestos (MediaPipe) |
| `hurdles` / `stairs` | 10 / 11 | Deporte (requiere el Pro) |
| `color_classify` | 12 | Clasifica bloques de color |
| `lab_adjust` | 9 | Ajuste de umbrales |
| `remote_control` | 1 | Control por joystick |

### Ejemplo de prompt

> «Ola TonyPi, mira alrededor, saluda a quien tengas delante y dime qué ves.»

El agente encadena `robot_camera_snapshot` → `robot_do_action("wave")` →
`robot_look(...)` → y describe el frame con el modelo multimodal.

---

## 5. Receta: el LLM

El agente MCP es agnóstico: el modelo lo pone el cliente. Pero si quieres que
**el propio robot** hable, `voice_agent.py` trae el ciclo completo.

### Opción A — NVIDIA NIM (gratis)

`build.nvidia.com` da **unos 85 modelos con endpoint gratis** (OpenAI-compatible,
sin tarjeta, con verificación de teléfono). Se registra una clave `nvapi-...`
en <https://build.nvidia.com/settings>.

```bash
export LLM_API_KEY=nvapi-...
export LLM_BASE_URL=https://integrate.api.nvidia.com/v1
export LLM_MODEL=nvidia/nemotron-3.5-bolt-e4b
```

Modelos recomendados para un robot (rápidos y con tool calling):

| Modelo | Latencia | Notas |
|---|---|---|
| `minimaxai/minimax-m3.1-flash` | 0,2-0,7 s | El más rápido del catálogo |
| `nvidia/nemotron-3.5-lightning-30b-a3b` | ~1-2 s | Equilibrado, 1M de contexto |
| `nvidia/nemotron-3.5-bolt-e4b` | ~0,3 s | Modelo pequeño con visión |
| `z-ai/glm-5.3` | 7-27 s | Razonamiento, mejor para decisiones |

**Límite:** ~40 peticiones/minuto por clave (confirmado por el staff de NVIDIA en
los foros). Sin créditos: la restricción es el rate limit, no el saldo.

### Puesta en marcha con NVIDIA (verificada, no de oidos)

```bash
export NVIDIA_API_KEY=nvapi-...          # https://build.nvidia.com/settings

python nvidia_models.py --list            # que modelos hay AHORA MISMO
python nvidia_models.py --probe           # sondea y recomienda el mejor
python nvidia_smoke_test.py               # prueba de humo completa
```

`--probe` no se fia de ningun blog: comprueba contra la API que cada modelo
(a) responde, (b) devuelve `tool_calls` y (c) acepta imagen. El resultado se
guarda en `nvidia_catalog.json`.

`nvidia_smoke_test.py` da el paso extra que se suele omitir: manda las **23
herramientas reales** de `server.py` con sus esquemas JSON Schema y comprueba
que el modelo elige una válida. Cada proveedor tiene su propio formato de tool
calling, y ahí es donde se rompen las integraciones.

### Opción B — LLM local en la Raspberry Pi

Con `llama.cpp` sobre la Pi 5, medido por terceros:

| Modelo | Velocidad | Veredicto |
|---|---|---|
| Qwen2.5 1.5B Q4 | ~9-10 tok/s | Automatización, **no conversación** |
| Llama 3.2 1B Q4 | ~11 tok/s | Solo intents simples |
| Qwen2.5 3B Q4 | ~4,7-5,2 tok/s | El techo de la Pi 5 |
| Llama 3.2 3B Q4 | ~4,4 tok/s | Límite practicality |
| 7B en Q4 | ~2 tok/s | Inviable para hablar |

Traducción: **una respuesta de 25 palabras tarda 5-8 segundos**, y el contexto
crece el coste. En la Pi 5 sin NPU, un LLM local sirve para *clasificar
intenciones* ("eso es una pelota roja" → comando), no para conversar.

**Recomendación: híbrida.**
- **En el robot:** un SLM pequeño y local (Qwen2.5 1.5B o similar) o incluso
  reglas, para decidir *qué hacer*.
- **En la nube:** el LLM grande (NVIDIA gratis u OpenAI) para *conversar*.

Ojo con la RAM: el kit básico trae Pi 4B 4GB o Pi 5 2/4GB. Para un LLM local
necesitas **Pi 5 8GB** (puedes cambiar la Pi tú mismo: el robot se vende con la
Pi dentro).

---

## 6. Receta: ASR y TTS

Son dos piezas distintas del pipeline de voz:

```
 🎤 audio  ──ASR──▶  texto  ──LLM──▶  texto  ──TTS──▶  🔊 audio
   (oídos)                          (cerebro)              (boca)
```

### ASR (oídos) — de audio a texto

**Whisper** es el modelo de OpenAI que hace eso: transcribe audio a texto. Es
el estándar de facto y funciona con audio de 16 kHz mono (justo lo que te da
un micrófono).

| Backend | Pros | Contras |
|---|---|---|
| **Whisper API** (nube) | Muy preciso, cero instalación | Cuesta dinero por minuto |
| **whisper.cpp** (local) | Gratis, offline, corre en la Pi | `small` tarda ~2-4× el audio en la Pi 5 |
| **NVIDIA Parakeet** | Gratis en NIM, multilingüe | Solo API |
| **Vosk** | Muy ligero | Menos preciso |

Alternativas en la nube: Deepgram, AssemblyAI, Google STT.

```bash
export ASR_BACKEND=openai
export ASR_MODEL=whisper-1
export OPENAI_API_KEY=sk-...
# o bien, local:
export ASR_BACKEND=whispercpp
export WHISPER_MODEL_PATH=/home/pi/models/ggml-small.bin
```

### TTS (boca) — de texto a audio

Es lo contrario: convierte la respuesta del LLM en voz.

| Backend | Pros | Contras |
|---|---|---|
| **OpenAI TTS** (`gpt-4o-mini-tts`) | Natural, conSeveral voces | API de pago |
| **piper** (local) | Gratis, offline, muy natural, rapidísimo | Hay que bajar el modelo (~60 MB) |
| **espeak-ng** (local) | Ya está en la Pi, instantáneo | Voz de robot |

```bash
export TTS_BACKEND=espeak        # el más简单的 para empezar
export TTS_BACKEND=piper         # el mejor relación calidad/precio
export TTS_BACKEND=openai        # el más natural
export TTS_VOICE=alloy
```

---

## 7. Los oídos y la boca: opciones reales

Este es el punto donde se decide el presupuesto. Tres caminos, de más barato a
más caro:

### A) Bluetooth (lo que preguntabas) — sí funciona, con matices

La Pi 5 tiene **Bluetooth 5.0 integrado**, así que **no necesitas comprar
nada**: emparejas tus cascos y ya.

El matiz importante es el perfil:

- **A2DP** = audio de alta calidad, **solo salida**. Es lo que usas para música.
- **HFP/HSP** = calidad de llamada, **entrada y salida**. Es lo que lleva el
  micrófono.

Cuando el micrófono está activo, el sistema cambia a HFP: **mono, ~
telefónico**. Para ASR eso da igual (Whisper está entrenado en 16 kHz mono), y
para el altavoz significa que oirás al robot con calidad de llamada.

En Raspberry Pi OS actual el stack es **PipeWire** (sustituyó a PulseAudio), que
además soporta el modo «duplex» con Opus 5 Pro / FastStream si tu headset lo
trae — ahí sí tienes A2DP y micro a la vez.

```bash
bluetoothctl
  power on
  scan on
  pair AA:BB:CC:DD:EE:FF
  trust AA:BB:CC:DD:EE:FF
  connect AA:BB:CC:DD:EE:FF
```

Verifica el perfil en `pavucontrol` → pestaña *Configuration*.

**Veredicto:** para un robot parlanchín, un headset BT es perfectamente
válido y cuesta US$0. La pega es el *lag* y que a veces hay que reconectar.

### B) Jack de 3,5 mm (lo más simple si el cuerpo lo permite)

La Pi 5 tiene un jack combinado de 4 polos (audio + micro). Un headset con
cable TRRS da **entrada y salida simultáneas, sin latencia y sin pairing**.
El robot ya usa `aplay` para los sonidos, así que el stack está ahí.

Comprueba si el cuerpo del TonyPi deja accesible el jack de la Pi; si no, un
corte mínimo en la carcasa de plástico o un jack USB-C de 4 polos lo resuelve.

### C) Módulos sueltos

- **Micrófono USB** (~US$8-15) → entrada
- **Altavoz USB** o un **MP3 de I2C** (~US$5) → salida
- O el **kit oficial TonyPi AI Upgrade** (~US$199) con la caja WonderEcho Pro:
  micro con cancelación de ruido + altavoz, y abre los capítulos oficiales de
  voz y de modelo grande.

**Comparación con el WonderEcho Pro:** la caja es, en el fondo, una tarjeta de
sonido USB estándar (el software usa `PyAudio` + `portaudio`). La ventaja real
que aporta es el **micro con reducción de ruido** y el firmware con palabra de
activación. Si tu headset tiene buen micro, no lo necesitas.

> Nota: el SDK trae `ASR.py` y `TTS.py`, pero son los módulos **I2C de Hiwonder
> y solo reconocer chino** (codificación GB2312). Para español o inglés,
> `whisper` + `piper`/`espeak` es el camino.

---

## 8. Hallazgos de ingeniería inversa del repo oficial

Cosas que encontré leyendo el código y que **no funcionan como parecen**:

| Hallazgo | Detalle |
|---|---|
| `GetRunningFunc` está **hardcodeado a 0** | `return (True, (0,))` — la línea que devuelve el valor real está comentada. Por eso `robot_vision_status` también lleva su propio registro local |
| `SetLABValue` espera otro formato | El docstring dice `{color: [[min],[max]]}`, pero `lab_adjust.py` lee `{"color":…, "min":[…], "max":[…]}` |
| `SetPWMServo` exige número **par** de argumentos | Convención real: `[duración_ms, nº_servos, servo, pulso, …]`. Un solo servo se llama `[500, 1, 1, 1500]` |
| `SetBusServoPulse` valida `count*2+2 == len(args)` | Igual convención: `[500, 1, 3, 250]` |
| No hay `SetBuzzer` ni reproducción de audio por RPC | El buzzer existe (`board.set_buzzer`) pero no está expuesto. Si lo quieres, hay que parchear `RPCServer.py` en el robot |
| El puerto 9030 no está documentado | Solo se descubre leyendo `RPCServer.py` (`run_simple('', 9030, application)`) |
| `Functions/voice_interaction/` importa `from speech import speech` | Ese módulo **no está en el repo**: viene con la caja de voz. Sin ella, esas lecciones no corren |

Por eso el cliente es tolerante: `_normalize()` desenvuelve las tres formas
que puede devolver el dispatcher (`[ok, datos, método]`, `[[ok, datos]]` y el
dato pelado).

---

## 9. Ficheros

| Fichero | Para qué |
|---|---|
| `server.py` | El servidor MCP (23 herramientas) |
| `tonypi_client.py` | Cliente JSON-RPC del robot, sin dependencias |
| `voice_agent.py` | Ciclo completo de voz: VAD → ASR → LLM → tools → TTS |
| `vad.py` | Detección de voz: el turno corta cuando dejas de hablar |
| `mcp_bridge.py` | Conecta el agente de voz con el catálogo del servidor MCP |
| `prompts.py` | **Personalidad de PontiBot** + reglas de oro del prompt |
| `memory.py` | **Memoria**: hilo de la conversación, perfil persistente y notas |
| `test_memory.py` | 32 pruebas de la memoria (sin red) |
| `test_live_memory.py` | Prueba en vivo de la memoria contra el LLM real |
| `audio_doctor.py` | Diagnóstico del audio del robot |
| `setup_pi.sh` | Instalador en el robot: apt, venv, piper, whisper, systemd |
| `robot_patch/` | Parche reversible del firmware (buzzer + audio por RPC) |
| `mock_robot.py` | Robot simulado con el protocolo real |
| `selftest.py` | 28 comprobaciones del cliente RPC contra el simulador |
| `e2e_mcp_test.py` | **Prueba de extremo a extremo del MCP** (28 checks, con SDK real o stub) |
| `tests/mcp_stub/` | Implementación mínima del protocolo MCP para testear sin instalar el SDK |
| `test_rpc.py` | Comprobación rápida contra el robot real |
| `mcp-config.example.json` | Configuración para tu cliente MCP |
| `deploy_to_robot.sh` | **Despliegue completo en el robot con un comando** |
| `wifi_dongle_setup.sh` | **Diagnóstico y puesta en red del módulo Wi-Fi USB** |
| `GUIA_PASO_A_PASO.md` | **Guía completa de montaje, de 0 a que el robot habla** |
| `.env` | Configuración real (contiene la clave; fuera de git) |
| `.env.example` | Plantilla sin clave |
| **`PLAN.md`** | **Qué se modifica y cómo, paso a paso** |

---

## 10. Puesta en marcha recomendada

0. **Red:** módulo Wi-Fi USB + modo LAN/STA → ver sección 12. Sin esto no hay LLM.
1. `python mock_robot.py` + `python selftest.py` → todo verde sin robot.
2. `pip install -r requirements.txt`, `export TONYPI_HOST=...`, `python test_rpc.py`.
3. Configura el cliente MCP y prueba: «saluda y dime qué ves».
4. Añade audio: headset BT o jack + `espeak-ng` para TTS.
5. LLM: empieza con **NVIDIA NIM gratis** en la nube; si más adelante quieres
  autonomía, mete un SLM local pequeño para las intenciones y deja la conversación
   al modelo grande.

---

## 11. Y lo que falta: la capa de voz

Lo anterior es **la capa de control** (el robot obedece). La **capa de voz** —
lo que convierte al bot en algo con lo que hablas— tiene su propio mapa de
modificaciones: el stack de audio dentro de la Raspberry Pi, el VAD que evita
que te corte a mitad de frase, y el servicio systemd para que arranque solo.

Todo eso está detallado, con comandos y orden, en **[`PLAN.md`](PLAN.md)**.

---

---

## 12. Personalidad y memoria

PontiBot no es un voz que repite lo que le mandas. Tiene **carácter** y **recuerda**.

### La personalidad

Vive en `prompts.py`, en tres bloques separados:

| Bloque | Qué define |
|---|---|
| `PERSONALITY` | Quién es: curioso, con humor seco, cálido sin empalagar, honesto con lo que es (un robot), con iniciativa propia |
| `MECHANICS` | Las reglas de oro de las herramientas: si puedes hacerlo, **hazlo** |
| `VOICE` | Cómo suena por el altavoz: español siempre, frases de menos de 25 palabras, nada de listas ni emojis |

El bloque de la personalidad va **antes** que el de estilo, así el humor seco no
se come la utilidad. Y el prompt de visión (`SCENE_PROMPT`) es aparte: describe
lo que ve sin las reglas de herramientas, que ahí no aplican.

> Cambiar el carácter es editar `PERSONALITY` en `prompts.py`. Nada más.
> Y como el smoke test usa **el mismo prompt que el robot**, no te fías de
> "me suena bien": lo compruebas.

### La memoria

`memory.py` tiene tres niveles:

| Nivel | Qué guarda | Dónde |
|---|---|---|
| **Hilo actual** | Las últimas `PONTIBOT_MAX_TURNS` intervenciones (pregunta y respuesta) | En memoria |
| **Perfil** | Hechos que se deducen de lo que dice: nombre, cómo llamarle, color favorito, ciudad, a qué se dedica, qué le gusta y qué no | `~/.pontibot/memory.json` |
| **Notas** | Lo que le pides que recuerde («recuerda que el gate va el jueves») | El mismo fichero |

Al arrancar, esos hechos se inyectan en el prompt de sistema, así que PontiBot
saluda por su nombre y usa lo que sabe **sin anunciarlo** («como te dije antes»
queda prohibido en el prompt).

```bash
# ver lo que sabe
python memory.py                      # imprime el resumen
cat ~/.pontibot/memory.json            # el fichero entero

# olvidar todo
python voice_agent.py --reset-memory

# sin memoria (cada turno empieza de cero)
python voice_agent.py --no-memory
```

El fichero se escribe de forma **atómica** (tmp + `rename`) y con permisos
`600`: si se corta la luz a media escritura, la memoria no queda corrupta.

### El bug que había debajo

El agente llevaba el historial en una variable local que se creaba con
`history = history + [...]`. Eso hacía una **lista nueva**: la respuesta del
robot nunca llegaba a la lista del llamante, y **cada turno empezaba desde el
prompt de sistema**. Por eso no recordaba nada.

Ahora el hilo vive en `ConversationMemory` y se guarda **por turnos**
(`[pregunta, (llamada + resultado)*, respuesta]`), así el recorte nunca deja
una llamada a herramienta sin su respuesta.

**Verificado con `python test_memory.py` → 32/32**, incluido el caso clave:
«el turno 2 ve al turno 1».

### Los otros dos bugs que la conversación en vivo destapó

Estos no se ven leyendo el código: aparecen al hablar con el modelo de verdad.

**1. El catálogo local no cuadtaba con el prompt.** El prompt dice
«usa `robot_do_action`» pero el backend `rpc` (el que se usa por defecto)
exponía `gesture`, `move`, `look_at`… Con esos nombres, el modelo llamaba a
herramientas que no existían y **el robot no se movía nunca**. Ahora el
catálogo local usa **los mismos nombres y parámetros** que el servidor MCP
(9 herramientas comunes, verificado), y el prompt vale para los dos backends.

**2. El modelo se imitaba a sí mismo.** Al_FUNCIONANDO correctamente el primer
turno, el historial guardaba solo `assistant: "Saludé."`. En el turno
siguiente, el modelo veía su propio ejemplo y contestaba `"Paré."` **sin
llamar a `robot_stop`**: el robot no se paraba, pero el robot decía que sí.

Se arregla por dos lados:

- La memoria guarda **también** la llamada a la herramienta y su resultado, así
  el modelo ve en el historial el patrón correcto (llamar → resultado →
  confirmar).
- El prompt prohíbe explícitamente afirmar una acción sin haber llamado a la
  herramienta.

**Verificado en vivo contra el simulador**: los 5 turnos (`saludar`, `parar`,
`mirar a la derecha`, `avanzar 3 pasos`, `buscar caras`) llaman a su
herramienta y **el estado del robot cambia** (`action=('wave',1)` → `None` →
`head.pan=2000` → `action=('go_forward',3)`).

### Si el modelo se calla

A veces el modelo vuelve con el contenido vacío, o se queda llamando
herramientas en bucle. Callarse del todo es lo peor que puede hacer un robot,
así que hay dos redes:

- **Detección de bucle**: la misma llamada repetida 3 veces corta el bucle.
- **Respuesta de reserva**: «Hecho.» si hubo herramientas, «Te he oído.
  Repites?» si no.

`LLM_TEMPERATURE` (por defecto `0.6`) permite bajarla si prefieres menos
variación y más previsibilidad.

---

## 13. El módulo Wi-Fi USB

El robot arranca en **modo AP** (hotspot `HW...`, contraseña `hiwonder`), y ese
modo **no tiene internet**: sin internet no hay llamada a la API de NVIDIA y el
robot se queda mudo. Con un **módulo Wi-Fi USB** lo que quieres es que el
módulo sustituya al Wi-Fi integrado y que el robot entre en tu red.

`wifi_dongle_setup.sh` hace el trabajo sucio:

```bash
./wifi_dongle_setup.sh --host 192.168.149.1 diagnose          # ¿lo reconoce el kernel?
./wifi_dongle_setup.sh --host 192.168.149.1 disable-onboard    # el USB toma wlan0
./wifi_dongle_setup.sh --host 192.168.149.1 install-driver     # si falta (necesita internet)
./wifi_dongle_setup.sh --host 192.168.149.1 sta --ssid "MI_WIFI" --pass "MI_PASS"
./wifi_dongle_setup.sh --host 192.168.149.1 verify
```

Los tres puntos que hacen que funcione:

1. **El módulo debe quedarse con el nombre `wlan0`.** El stack de Hiwonder
   (`wifi.service` / `hw_wifi.service`) gestiona un único interfaz. Desactivando
   el integrado con `dtoverlay=disable-wifi` + blacklist de `brcmfmac`, el
   dongle es el único `wlan0` y todo lo demás sigue funcionando igual.
   **No se toca el Bluetooth**: el audio del robot depende de él.
2. **El driver es el punto flaco.** Si el módulo es un Realtek (RTL8812AU,
   RTL8822BU, RTL8821AU…) el kernel de la Pi no lo trae en aarch64 y hay que
   compilarlo con DKMS. `install-driver` usa el driver `rtw88` de `lwfinger`,
   que cubre las 11 familias USB habituales. Para compilar hace falta internet:
   usa el **cable Ethernet** (el TonyPi tiene RJ45) o el Wi-Fi integrado
   mientras instalas.
3. **La configuración se escribe en `~/hiwonder-toolbox/wifi_conf.py`**, que es
   donde la expects Hiwonder: `HW_WIFI_MODE = 2` (STA/LAN) más el SSID y la
   contraseña. El script lo edita sin romper el resto del fichero (comenta las
   líneas anteriores y conserva intactos los ajustes del hotspot `HW...`).

Si algo sale mal, `ap` devuelve al robot al hotspot para recuperarlo.

Detalle completo, con el diagrama del flujo y los errores típicos:
**[`GUIA_PASO_A_PASO.md`](GUIA_PASO_A_PASO.md)**, paso 1.

---

## 14. Despliegue en un comando

> **¿Primera vez? Sigue [`GUIA_PASO_A_PASO.md`](GUIA_PASO_A_PASO.md).** Ojo al paso 1:
> el robot arranca en modo AP (hotspot) y **ese modo no tiene internet**.
> Sin internet no hay LLM, y el robot se queda mudo.


Con el modelo ya decidido (`nvidia/nemotron-3.5-bolt-e4b`) y la clave guardada,
dejar el robot listo es un comando:

```bash
cd tonypi-mcp
./deploy_to_robot.sh --host 192.168.1.50 --with-service --patch
```

El script hace, en orden:

1. Comprueba la conexión SSH.
2. Copia el código (sin `.env` ni `__pycache__`).
3. Escribe el `.env` en el robot con la clave de NVIDIA (permisos `600`).
4. Instala dependencias (`apt`, venv, piper y whisper.cpp si los pides).
5. Aplica el parche opcional del firmware (`--patch`).
6. Instala el servicio systemd (`--with-service`).
7. **Verifica**: `test_rpc.py`, `audio_doctor.py` y una llamada real al LLM
   desde el robot.

Opciones útiles:

| Flag | Qué hace |
|---|---|
| `--with-piper` | TTS natural y local (recomendado frente a espeak) |
| `--with-whisper` | Compila whisper.cpp para ASR local (tarda) |
| `--with-service` | Instala y habilita `pontibot.service` |
| `--patch` | Expone buzzer y audio por RPC |
| `--dry-run` | Solo comprueba que el SSH responde |

La clave se toma de `$NVIDIA_API_KEY` (o `--key`). El `.env` de este repo
**contiene la clave real**: no lo subas a git ni lo compartas. Está en el
`.gitignore`.

### Configuración efectiva

El agente lee el `.env` de su carpeta al arrancar (las variables ya presentes
en el entorno tienen prioridad, así que systemd puede sobreescribirlas con
`Environment=`). Y la unidad systemd incluye:

```ini
EnvironmentFile=-/home/pi/tonypi-mcp/.env
Environment="LLM_BASE_URL=https://integrate.api.nvidia.com/v1"
Environment="LLM_MODEL=nvidia/nemotron-3.5-bolt-e4b"
```

---

## 15. Qué está verificado y qué no

Esto es lo que importa antes de confiarle un robot a un LLM.

### ✅ Verificado (28/28 + 32/32 + 7/7 + 6/6)

| Capa | Prueba | Resultado |
|---|---|---|
| **Servidor MCP de extremo a extremo** | `python e2e_mcp_test.py` | **28/28**. Arranca `server.py` **sin modificar** como proceso, le habla MCP real por stdio (`initialize` → `tools/list` → `tools/call`) y comprueba que las herramientas **ejecutan de verdad** contra el robot: la acción se dispara, la cabeza se mueve, la visión se carga, el texto se envía |
| **Catálogo de herramientas** | dentro de la E2E | 23 herramientas, todas con `inputSchema` y descripción |
| **Errores** | dentro de la E2E | Dirección inválida y herramienta inexistente se gestionan **sin tumbar el servidor** |
| **Memoria (sin red)** | `python test_memory.py` | **32/32**: extracción de hechos, persistencia con permisos `600`, recorte del hilo, y el caso clave «el turno 2 ve al turno 1» |
| **Memoria en vivo** | `python test_live_memory.py` | **7/7 contra el modelo real**: recuerda el nombre y el color favorito, y se identifica como PontiBot (3 ejecuciones seguidas) |
| **Herramientas en vivo** | conversación contra el simulador | Los 5 turnos llaman a su herramienta y **el estado del robot cambia** (saludar → parar → mirar → avanzar → visión) |
| **LLM eligiendo herramientas** | `python nvidia_smoke_test.py` | **6/6** peticiones de control con el modelo real de NVIDIA, con el prompt de personalidad puesto |
| **Visión del LLM** | `nvidia_models.py --probe` | El modelo identifica el color de una imagen de prueba |
| **Llamadas escritas como texto** | `tool_parse.py` | 4 formatos distintos detectados y convertidos |
| **Parche del firmware** | aplicado y revertido sobre el `RPCServer.py` real | **Byte a byte idéntico** al original tras `--undo` |
| **Simulador** | `python selftest.py` | 28/28 |

### ⚠️ Pendiente de verificar en tu máquina

| Qué falta | Cómo se verifica |
|---|---|
| El **SDK oficial** de MCP (aquí PyPI estaba bloqueado, así que usé una implementación mínima del protocolo) | `pip install mcp` y luego `python e2e_mcp_test.py --real-sdk` |
| El **robot físico** | `export TONYPI_HOST=<IP>` y lo mismo: `python e2e_mcp_test.py --real-sdk` |

El modo `--real-sdk` usa el cliente oficial y habla con `server.py` igual que
haría Claude Desktop. Es la prueba definitiva: si pasa contra el robot real,
el MCP está listo.


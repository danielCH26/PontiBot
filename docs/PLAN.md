# Qué se modifica y cómo: el resto que no depende del MCP

El MCP ya está hecho (servidor + 20 herramientas + simulador + tests). Eso es
**la capa de control**: el robot obedece.

Lo que falta es **la capa de voz**, y es donde vive el 80% del trabajo. Este
documento es el mapa exacto: qué fichero tocas, con qué comando, y en qué orden.

---

## 0. Primero: las tres arquitecturas posibles

Antes de tocar nada, decide dónde vive el "cerebro". Esto cambia todo lo demás.

### A. El robot es autónomo

```
🎤 → VAD → ASR → LLM(nube) → RPC directo → 🔊
                    (corre dentro del robot)
```

- **Dónde corre:** todo dentro de la Raspberry Pi del robot.
- **Cómo:** `voice_agent.py --backend rpc`.
- **Ventaja:** el robot funciona solo, sin PC. Nadie lo toca y se conversa con él.
- **Coste:** la Pi 5 hace de ASR. Con whisper.cpp en `small` va lento (el ASR
  local en Pi 5 es el cuello de botella real, no el LLM).
- **Necesitas:** micrófono + altavoz en el robot, y salida a internet.

### B. El PC es el cerebro (esto es el MCP)

```
🎤(PC) → ASR → LLM → MCP → server.py → JSON-RPC → 🤖(robot)
                                                   └→ 🔊(PC)
```

- **Dónde corre:** el LLM y el audio en tu PC; el robot solo obedece.
- **Cómo:** `server.py` + el cliente MCP de Claude (o el tuyo).
- **Ventaja:** el LLM puede ser enorme, el ASR puede ser whisper large, y
  tienes GPU. El robot es un cuerpo puro.
- **Coste:** el robot no habla si el PC está apagado.

### C. Híbrida — la que yo montaría

```
🤖🎤 → VAD → ASR local (whisper.cpp) → texto
                                          ↓
                       🖥️ LLM (nube o local) → texto + acciones
                                          ↓
🤖🔊 ← TTS local (piper) ←──────────────┘   y el robot ejecuta
```

- El robot **escucha y habla solo** (ASR y TTS locales, sin coste ni internet
  para el audio).
- La **conversación** ocurre en el LLM potente (NVIDIA NIM gratis).
- El robot **obedece** vía el mismo JSON-RPC, sin necesidad del MCP.

Esto es exactamente lo que hace `voice_agent.py --backend mcp`: el catálogo de
herramientas llega del servidor MCP, así que el LLM ve las mismas 20 herramientas
que ve Claude, y no hay catálogo duplicado.

> Decisión rápida: si quieres que el robot hable **sin PC delante**, elige A o C.
> Si quieres la máxima potencia y el PC ya está encendido, elige B.

---

## 1. En el robot (Raspberry Pi)

### 1.1 Capa de audio — el sistema operativo

**Qué se toca:** paquetes del sistema + configuración de bluetooth.

```bash
sudo apt install -y alsa-utils bluez bluez-tools \
  pipewire pipewire-audio-client-libraries pulseaudio-utils \
  espeak-ng ffmpeg
```

**Qué pasa:** `arecord` (graba) y `aplay` (reproduce) son la base de todo. El
robot ya los usa: `Joystick.py` llama a `aplay` para los sonidos.

**Bluetooth** (si vas por esa vía):

```bash
bluetoothctl
  power on
  agent on
  default-agent
  scan on
  pair AA:BB:CC:DD:EE:FF
  trust AA:BB:CC:DD:EE:FF
  connect AA:BB:CC:DD:EE:FF
```

**El detalle que muerde:** el micrófono por BT solo funciona con el perfil
**HFP/HSP**, no con A2DP. En `pavucontrol` → *Configuration* tienes que
cambiar el perfil del auricular a "Headset" (o "Hands-Free"), no "High Fidelity".
Cuando el micro está activo, el audio baja a calidad de llamada — para ASR da
igual (Whisper trabaja en 16 kHz mono), pero el altavoz sonará "por teléfono".

**Diagnóstico:** `audio_doctor.py` te dice exactamente qué ve el sistema, cuál
es el micro, cuál el altavoz y si el micro capta algo de verdad. Ejecuta esto
primero, antes de escribir nada de voz.

### 1.2 VAD — para que no te corte y no esperes en balde

**Qué se toca:** `vad.py` (nuevo, ya escrito).

**Cómo:** `pip install webrtcvad-wheels`. Si no está, el módulo cae
automáticamente a un detector de energía RMS que solo usa la stdlib.

**Qué resuelve:** la versión anterior grababa 5 segundos fijos. Ahora el turno
termina cuando tú dejas de hablar (0,9 s de silencio), con 0,4 s de *preroll*
para que no se coma la primera sílaba.

### 1.3 ASR — el oído

**Opción cloud (rápida de montar):**

```bash
export ASR_BACKEND=openai
export ASR_MODEL=whisper-1
export OPENAI_API_KEY=sk-...
```

**Opción local (gratis, offline, la que recomiendo para la Pi):**

```bash
bash setup_pi.sh --with-whisper     # compila whisper.cpp + descarga ggml-small.bin
export ASR_BACKEND=whispercpp
export WHISPER_MODEL_PATH=$HOME/models/ggml-small.bin
```

**Opción servidor local (la más cómoda):** whisper.cpp trae un servidor con
API compatible con OpenAI. Lo dejas corriendo en la Pi y el resto de programas
lo consultan igual que OpenAI:

```bash
whisper-server --model $HOME/models/ggml-small.bin --host 127.0.0.1 --port 8081
export ASR_BACKEND=local_server
export ASR_SERVER_URL=http://127.0.0.1:8081
```

> **Alternativa gratis que no habías considerado:** NVIDIA tiene
> `parakeet-tdt-0.6b` con **endpoint gratuito** en build.nvidia.com. Es ASR
> multilingüe (25 idiomas) sin pagar nada. Si no quieres compilar nada, usa
> eso con `ASR_BACKEND=openai` pero apuntando a `LLM_BASE_URL` de NVIDIA.

### 1.4 TTS — la boca

```bash
bash setup_pi.sh --with-piper        # instala piper + voz española
export TTS_BACKEND=piper
```

O lo más simple, que ya viene en la Pi:

```bash
export TTS_BACKEND=espeak           # instantáneo, voz de robot
```

O la mejor calidad, en la nube:

```bash
export TTS_BACKEND=openai
export OPENAI_API_KEY=sk-...
```

**Tabla de decisión:**

| Backend | Instalación | Calidad | Latencia | Coste |
|---|---|---|---|---|
| `espeak` | `apt install espeak-ng` | 🤖 | ~0 | 0 |
| `piper` | `pip install piper-tts` + modelo | 😊 | ~0,3 s | 0 |
| `openai` | nada | 😃 | ~0,5 s | API |

### 1.5 El agente

**Qué se toca:** `voice_agent.py` (reescrito).

**Los dos detalles que hacen que funcione de verdad en un robot:**

1. **Half-duplex.** Mientras el robot habla, el micrófono está ciego. Sin esto
   el robot se oye a sí mismo por el altavoz, el VAD detecta "voz" y entra en
   bucle. En el código, el TTS se reproduce *después* de cerrar la captura.

2. **El prompt.** Le digo al LLM que use las herramientas en vez de prometer
   cosas, y que responda en frases cortas. Sin ese prompt, el modelo dice
   "¡Claro! Voy a saludar" y no llama a ninguna herramienta.

### 1.6 Servicio systemd (para que arranque solo)

**Qué se toca:** `/etc/systemd/system/pontibot.service` (nuevo).

```bash
bash setup_pi.sh --with-service
sudo systemctl enable --now pontibot
journalctl -u pontibot -f      # ver logs
```

### 1.7 Parche opcional del firmware

**Qué se toca:** `/home/pi/TonyPi/RPCServer.py` del robot.

El firmware oficial **no expone por RPC** el buzzer ni la reproducción de audio.
Con el parche añades `SetBuzzer`, `PlayAudio` y `Speak`:

```bash
ssh pi@<IP> 'cd ~/tonypi-mcp/robot_patch && python3 apply_patch.py'
sudo systemctl restart tonypi.service
```

El script hace copia de seguridad con timestamp, valida que el archivo siga
siendo Python correcto antes de escribir, y es idempotente. Para deshacerlo:
`python3 apply_patch.py --undo` (verificado: devuelve el archivo **byte a byte
idéntico** al original).

Con el parche, el MCP gana tres herramientas: `robot_beep`, `robot_play_audio`
y `robot_say`. Son opcionales: sin el parche, esas herramientas devuelven un
aviso claro en vez de romper.

---

## 2. En el PC

| Qué | Estado | Cómo |
|---|---|---|
| Servidor MCP | ✅ hecho | `server.py` |
| Catálogo de 20 herramientas | ✅ hecho | incl. `robot_beep`/`robot_say` |
| Cliente JSON-RPC | ✅ hecho | `tonypi_client.py` |
| Config del cliente MCP | ✅ hecho | `mcp-config.example.json` |
| Clave del LLM | ⬜ falta | `build.nvidia.com/settings` → `nvapi-...` |
| Cliente MCP de Claude | ⬜ falta | `claude mcp add tonypi --env TONYPI_HOST=... -- python .../server.py` |

---

## 3. Orden de ejecución

**Fase 1 — Sin tocar el robot (30 min).**
```
python mock_robot.py        # terminal 1
python selftest.py          # terminal 2 -> 28/28
```
Ya tienes el MCP funcionando contra el simulador.

**Fase 2 — Conectar el robot real (15 min).**
```bash
export TONYPI_HOST=<IP_DEL_ROBOT>
python test_rpc.py $TONYPI_HOST
```
Sin esto, el MCP no hace nada útil.

**Fase 3 — Audio (1 h, la parte larga).**

O con el script de despliegue, que hace las fases 3 a 7 de una vez:

```bash
./deploy_to_robot.sh --host <IP> --with-service --patch --with-piper
```

O a mano, si prefieres ver cada paso:

```bash
scp -r tonypi-mcp pi@<IP>:~/
ssh pi@<IP> 'cd ~/tonypi-mcp && bash setup_pi.sh'
ssh pi@<IP> 'cd ~/tonypi-mcp && ./.venv/bin/python audio_doctor.py'
```
Decide aquí: ¿jack, BT o USB? El diagnóstico te dice qué hay.

**Fase 4 — Hablar (30 min).**
```bash
ssh pi@<IP>
cd ~/tonypi-mcp
export LLM_API_KEY=nvapi-...
export LLM_BASE_URL=https://integrate.api.nvidia.com/v1
export LLM_MODEL=nvidia/nemotron-3.5-bolt-e4b
export TTS_BACKEND=espeak
./.venv/bin/python voice_agent.py
```

**Fase 5 — Parche y automatizar (20 min).**
```bash
ssh pi@<IP> 'cd ~/tonypi-mcp/robot_patch && python3 apply_patch.py && sudo systemctl restart tonypi.service'
bash setup_pi.sh --with-service
```

---

## 4. Lo que ya está resuelto con NVIDIA

La conexión al LLM **ya está verificada** contra la API con tu clave:

| Dato | Valor |
|---|---|
| Endpoint | `https://integrate.api.nvidia.com/v1` |
| Modelo | `nvidia/nemotron-3.5-bolt-e4b` |
| Latencia chat / tools / visión | 0,43 s / 0,29 s / 0,57 s |
| Elección de herramienta | **6/6** peticiones de control correctas |
| Límite del free tier | ~40 peticiones/minuto por clave |

La clave está guardada cifrada como secreto `NVIDIA_API_KEY`.

**Pendiente de esta parte:** solo el arranque en el robot. En el servicio
systemd basta con:

```ini
Environment="LLM_API_KEY=nvapi-..."
Environment="LLM_BASE_URL=https://integrate.api.nvidia.com/v1"
Environment="LLM_MODEL=nvidia/nemotron-3.5-bolt-e4b"
Environment="LLM_LANGUAGE=es"
```

Detalles, manías del modelo y cómo verificarlos: **`NVIDIA.md`**.

## 5. Lo que NO hay que tocar

- **El repo oficial de Hiwonder**: se queda como está. El único cambio opcional
  es el parche en `RPCServer.py`, y es reversible.
- **El SDK de Hiwonder**: todo el control pasa por el puerto 9030, que ya está
  ahí.
- **El servicio `tonypi.service`**: no hay que tocarlo (salvo reiniciar tras el
  parche).

---

## 6. Los tres problemas que te van a morder (y cómo los resolví)

**1. El robot se oye a sí mismo.**
*Solución:* half-duplex estricto. El micrófono se cierra antes de que suene el
altavoz. Si aun así hay eco, un headset con micrófono direccional o separar el
mic del altavoz 30 cm lo resuelve.

**2. La Pi 5 es lenta para el ASR.**
*Solución:* `small` es el equilibrio; `base` va más rápido y con menos
precisión. Si aun así no da la talla, mueve el ASR al PC (arquitectura B) y
deja en la Pi solo el TTS.

**3. El LLM promete en vez de actuar.**
*Solución:* el prompt del sistema + bajar la temperatura + descriptions de
herramientas que dicen explícitamente "usa la herramienta en vez de decir que
lo harás". Si aun así falla, baja `max_tokens` y sube el número de vueltas del
bucle de herramientas (hoy 6).

---

## 7. Ficheros de esta entrega

| Fichero | Para qué |
|---|---|
| `vad.py` | Detección de voz + grabación que corta al dejar de hablar |
| `voice_agent.py` | Agente reescrito: VAD, half-duplex, backends `rpc` y `mcp` |
| `mcp_bridge.py` | Conecta el agente con el servidor MCP (catálogo compartido) |
| `audio_doctor.py` | Diagnóstico del audio del robot |
| `setup_pi.sh` | Instalador completo en el robot (apt, venv, piper, whisper, systemd) |
| `robot_patch/apply_patch.py` | Parche reversible del firmware (buzzer + audio) |
| `robot_patch/RPCServer_extra.py` | El bloque de código que se inserta |
| `nvidia_models.py` | Sondeo de los modelos NVIDIA: chat, tool calling y visión |
| `nvidia_smoke_test.py` | Prueba de humo con las 26 herramientas reales + 6 casos semánticos |
| `prompts.py` | El prompt del sistema (compartido entre agente y test) + la personalidad |
| `memory.py` | Memoria: hilo por turnos, perfil persistente y notas |
| `test_memory.py` | 32 pruebas de la memoria, sin red |
| `test_live_memory.py` | Prueba en vivo de la memoria contra el LLM real |
| `tool_parse.py` | Convierte llamadas a herramientas escritas como texto en llamadas reales |
| `mock_robot.py` | Simulador con el protocolo real (ya soporta los métodos parcheados) |
| `selftest.py` | 28 comprobaciones automáticas |
| `NVIDIA.md` | Resultados verificados contra la API + manías del modelo |


---

## 8. Personalidad y memoria de PontiBot

**Qué se toca:** `prompts.py` (nuevo bloque `PERSONALITY`), `memory.py` (nuevo),
`voice_agent.py` (bucle + memoria), `test_memory.py` y `test_live_memory.py` (nuevos).

### 8.1 La personalidad

Tres bloques en `prompts.py`, en este orden:

| Bloque | Contenido |
|---|---|
| `PERSONALITY` | Identidad, carácter y limites (curioso, humor seco, honesto con lo que es) |
| `MECHANICS` | Reglas de oro de las herramientas, incluida la prohibicion de afirmar acciones sin llamar a la herramienta |
| `VOICE` | Como suena: espanol, frases cortas, sin listas ni emojis |

`build_system_prompt(profile, notes)` inyecta lo que el bot sabe de la persona.

### 8.2 La memoria

`memory.py` guarda tres cosas:

1. **El hilo**, por turnos (`[pregunta, (llamada + resultado)*, respuesta]`), con
   las ultimas `PONTIBOT_MAX_TURNS` unidades.
2. **El perfil** (nombre, como llamarle, color favorito, ciudad, ocupacion,
   gustos y disgustos), extraido con regex del español.
3. **Las notas** ("recuerda que..."), en el mismo fichero.

Persistencia: JSON con escritura atomica (tmp + `os.replace`) y permisos `600`,
en `~/.pontibot/memory.json` (o `PONTIBOT_MEMORY`).

### 8.3 Lo que hubo que arreglar

| Bug | Sintoma | Arreglo |
|---|---|---|
| `history = history + [...]` | Cada turno empeza desde cero | `ConversationMemory` con estado explicito |
| Catalogo local con otros nombres | El modelo llamaba a herramientas inexistentes: el robot no se movia | Nombres y parametros identicos al servidor MCP |
| Historial sin las llamadas | El modelo respondia "Paré." sin llamar a `robot_stop` | La memoria guarda llamada + resultado, y el prompt lo prohibe explicitamente |
| Respuesta vacia o bucle de herramientas | El robot se callaba | Deteccion de bucle (3 repeticiones) + respuesta de reserva |

**Como se verifica:** `python test_memory.py` (32/32, sin red),
`python test_live_memory.py` (7/7 contra el LLM real) y la conversacion contra
el simulador, donde se comprueba que el ESTADO del robot cambia en cada turno.

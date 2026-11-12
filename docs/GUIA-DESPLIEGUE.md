# Guía de despliegue paso a paso · TonyPi con el LLM en el PC

> Versión 1.1 · 2026-11-09 · 12 fases (0-11), 40 pasos verificables
> Complementa a `ESTRUCTURA-PROYECTO.md` (qué va en cada sitio). Esta guía explica **cómo llegar ahí**.

---

## Rutas: una sola variable

Toda la guía usa `$REPO`. **Defínela una vez** y úsala en todas las terminales:

```bash
export REPO=/ruta/donde/descomprimiste/pontibot   # ej.: /mnt/c/Users/Arias/Desktop/UPB/TonyPiRV3/pontibot
cd "$REPO"
```

| Si tu repo está… | `REPO` es… |
|---|---|
| En WSL sobre Windows | `/mnt/c/Users/<TU_USUARIO>/Desktop/<...>/pontibot` |
| En Linux nativo | `/home/<TU_USUARIO>/pontibot` |
| En macOS | `/Users/<TU_USUARIO>/pontibot` |

> Este zip **es** el proyecto completo y **ya viene organizado** (`pc/`, `tools/`, `robot/`, `patches/`,
> `tests/`, `docs/`). No hay que mover nada: lo único es descomprimirlo y empezar.
> Comprueba que estás en el sitio correcto con `bash tools/check_repo.sh`.

## Mapa de conexiones: cuándo te desconectas del robot

| Fase | Tu WiFi | SSH al robot | RPC :9030 |
|---|---|---|---|
| 0 | te conectas al hotspot `HW-…` | abres sesión (contraseña) | — |
| 1-3 | sigues en el hotspot | sigues dentro | — |
| **4** | **vuelves a tu WiFi de casa** ⚠️ | **se cae** (el robot cambió de red) ⚠️ | se corta un momento |
| 5 | tu WiFi | `ssh tonypi` con la **IP nueva** | `UnloadFunc` por HTTP (sin SSH) |
| 6-9 | tu WiFi | solo si tocas el robot | siempre |

> **Te desconectas UNA vez, en la fase 4, y es a propósito**: es el cambio del robot a tu router.
> A partir de ahí, todo lo demás va por la LAN y **el hotspot `HW-…` no vuelve a hacer falta**.
>
> Cuando pase, actualiza dos cosas para que todo siga igual:
> ```bash
> # 1) el alias de SSH, con la IP nueva
> sed -i "s|HostName .*|HostName <IP_NUEVA>|" ~/.ssh/config
> # 2) la variable que usa el agente
> sed -i "s|^TONYPI_HOST=.*|TONYPI_HOST=<IP_NUEVA>|" .env
> ```

Lo que **no** te desconecta (para que no te asustes):

- **`UnloadFunc`** (fase 5): es HTTP, no SSH. No toca la red ni reinicia nada.
- **Instalar el servicio "solo RPC"** (fase 5.4 opción B): el robot reinicia *sus servicios*, pero tu sesión
  SSH sigue viva; solo el puerto 9030 tarda unos segundos en volver.
- **La limpieza del despliegue viejo** (fase 7): borra ficheros en el robot, no toca la red.

## Cómo leerla

Cada paso tiene la misma forma:

- **Qué** — la acción, en una frase.
- **Comando** — lo que copias y pegas (o "no aplica").
- **Verificación** — cómo sabes que funcionó. Si no da lo esperado, hay un **"Si falla"** con el siguiente paso.
- **⏱** — el tiempo que suele tardar.

Los pasos marcados ⚠️ son los que **más seSaltan** y más caro sale: el 403 de NVIDIA, el micrófono mudo y el
robot en modo de prueba.

---

## INTERFAZ ACTUAL: chat por consola

```bash
cd pc && python3 voice_agent.py --chat
```

Escribes la orden y el bot responde por texto (mismo LLM, mismas 26 herramientas, mismo robot).
**No necesita micrófono, ni TTS, ni VAD** → todo lo de audio queda intacto para cuando se retome.

Comandos del chat: `/ayuda` · `/herramientas` · `/memoria` · `/reset` · `/salir`.

---

## Fase 0 · Primer contacto con el robot (antes de tocar nada)

Esta fase es la que te da acceso al robot. Empieza por aquí: **todas las fases siguientes asumen que ya
puedes hacer `ssh pi@192.168.149.1`.**

### 0.1 Enciende el robot y conéctate a su hotspot

1. Enciende el robot (interruptor de la placa). Los **LED1 y LED2 se encienden** y el **LED2 parpadea cada
   2 segundos** → ha arrancado.
2. **Espera ~60 segundos** (arranque de Raspbian Buster).
3. El robot **suena un pitido** y **se pone de pie** (acción `stand_slow`). Es el arranque de fábrica, no un
   fallo: sigue así.
4. En el PC, busca una WiFi que empiece por **`HW`**. El nombre real es `HW-<8 primeros del serial>`
   (p. ej. `HW-1A2B3C4D`).
5. **Contraseña de la WiFi: `hiwonder`** (la de fábrica, verificada en la doc de Hiwonder).

> ⚠️ **En WSL2 no puedes conectar a WiFi desde la distro.** Conéctate desde **Windows** (Configuración →
> WiFi). WSL comparte la red de Windows, así que desde WSL ya verás esa conexión.

> El robot en modo AP **no tiene internet** (el DNS apunta a `127.0.0.1`). Da igual para esta fase: por
> SSH entra igual. Lo que sí necesita internet es tu **PC**, no el robot.

### 0.2 Entra por SSH (usuario `pi` + contraseña)

```bash
ssh pi@192.168.149.1
```

La primera vez pregunta:

```
The authenticity of host '192.168.149.1' can't be established.
ED25519 key fingerprint is SHA256:...
Are you sure you want to continue connecting (yes/no/[fingerprint])?   →  yes
pi@192.168.149.1's password:
```

**La contraseña depende de la versión de Raspberry Pi** (dato de la doc oficial de Hiwonder):

| Tu robot | Contraseña |
|---|---|
| **Raspberry Pi 4B** ← el tuyo (TonyPi v1.0) | `raspberry` |
| Raspberry Pi 5 (TonyPi Pro / v2.0) | `raspberrypi` |

**Verificación**: entras en el prompt del robot:

```
Linux raspberrypi 4.14.79-v7+ ...
Last login: ...
pi@raspberrypi:~ $ hostname
raspberrypi
```

**Si dice `Permission denied`**: casi siempre es la contraseña equivocada (4B = `raspberry`, no
`raspberrypi`). Si la cambiaste en el pasado, usa la tuya.

### 0.3 Deja de teclear la contraseña (5 minutos, hazlo ahora)

```bash
# 1) genera una clave si no tienes una
ssh-keygen -t ed25519 -C "tonypi"      # Enter para todo, o ponle contraseña si quieres

# 2) cópiala al robot
ssh-copy-id pi@192.168.149.1

# 3) alias en tu ~/.ssh/config
cat >> ~/.ssh/config <<'EOF'

Host tonypi
    HostName 192.168.149.1
    User pi
EOF

# 4) prueba
ssh tonypi 'hostname && echo OK'
```

**Verificación**: `OK` sin pedir contraseña.

> Con `ssh tonypi` todo lo de esta guía se puede escribir como `ssh tonypi 'comando'`.
> Si más adelante el robot pasa a modo LAN y cambia de IP, solo edita el `HostName` del alias.

### 0.4 Inventario: qué hay instalado y qué arrancó

```bash
ssh tonypi 'hostname; cat /etc/os-release | head -2; python3 -V;   systemctl list-units --type=service --state=running | grep -Ei "tonypi|pontibot|wifi|hw_wifi"'
```

**Verificación esperada**:

- `Raspbian GNU/Linux ... 10 (buster)` y `Python 3.7.x` → es tu v1.0, tal y como esperamos.
- `tonypi.service` **active** → el robot expone el JSON-RPC. Si no lo está, el robot no tiene canal de
  control: arráncalo con `ssh tonypi 'sudo systemctl start tonypi.service'` antes de seguir.

### 0.5 Comprueba que los servos están conectados y con alimentación

```bash
ssh tonypi 'sudo systemctl status tonypi.service --no-pager | head -20'
```

**Verificación**: en el log de arranque verás el pitido y la acción `stand_slow` (el robot se pone de pie).

**Si falla**: apaga el robot, comprueba que los servos del bus están **enchufados** (mux/SSP) y que el
interruptor de la placa está en ON. Un robot con los servos sin alimentar recibe las órdenes y no se mueve:
es el fallo más confundente que hay, porque el RPC responde 200 y el robot no se mueve.

### 0.6 Decide dónde va a correr el agente

| Tu PC | Ruta | Audio |
|---|---|---|
| Linux nativo o macOS | Directo en el PC | Auricular BT vía PulseAudio (o CoreAudio) |
| **WSL2 sobre Windows** (tu caso actual) | En WSL, **con puente de audio** | Ver fase 3 |

> ⚠️ En WSL2 el auricular Bluetooth **no existe** dentro de la distro: vive en Windows. Sin el puente de la
> fase 3, `parecord` no verá el micrófono y el bot "no oye". Es el fallo nº1 de este montaje.

### 0.7 Copia de seguridad antes de tocar nada (el robot es pequeño)

El disco del robot estaba al **95 %** lleno en el último despliegue. Antes de escribir nada:

```bash
ssh tonypi 'df -h / ; du -sh /home/pi/TonyPi 2>/dev/null'
```

**Verificación**: si `/` está por encima del 85 %, libera espacio antes de continuar
(`sudo apt clean && sudo journalctl --vacuum-size=50M`).

---

---

## Fase 1 · Verificar el entorno

> El proyecto **ya viene organizado** en este zip (`pc/`, `tools/`, `robot/`, `patches/`, `tests/`, `docs/`).
> Esta fase no mueve nada: comprueba que todo está en su sitio.

### 1.1 Comprueba que estás en la raíz correcta

```bash
cd "$REPO"
bash tools/check_repo.sh
```

**Verificación esperada**:

```
1. Ficheros del proyecto
  ✓ pc/voice_agent.py (ya reorganizado)
  ✓ pc/server.py (ya reorganizado)
2. Estado de la reorganización
  ✓ REORGANIZADO (el runtime ya está en pc/)
3. Kit de despliegue
  ✓ tools/reorganize.sh
  ✓ tools/env_check.sh
  ✓ tools/bt_headset_pc.sh
  ✓ tools/check_repo.sh
```

Si en lugar de eso dice "SIN REORGANIZAR", estás en una copia antigua del repo: vuelve a descomprimir
este zip.

> `tools/reorganize.sh` se queda en el repo por si algún día tienes que **migrar una copia antigua**
> (plana, con todo en la raíz) a esta estructura. Con el repo actual no hace falta: lo detecta y no toca
> nada.

### 1.2 Punto de vuelta (opcional, 20 s)

```bash
git init && git add -A && git commit -m "estado inicial"
```

`git init` es **local**: no publica nada, no pide cuenta ni internet. Si no quieres git, el
`reorganize.sh` deja igualmente una copia en `backup/<fecha>/`.

## Fase 2 · Configurar el PC

### 2.1 Crear el entorno virtual (Python ≥ 3.10)

> ⚠️ **En Ubuntu/WSL esto falla si no instalas el módulo `venv` primero.** Es el error más habitual:
> `ensure you have python3-full installed` / `No module named venv`.

```bash
cd "$REPO"

# 1) el módulo venv (en Ubuntu 24.04 es python3.12-venv, trae el metapaquete python3-venv)
sudo apt update
sudo apt install -y python3-venv python3-full

# 2) el entorno virtual
python3 --version          # debe ser ≥ 3.10 (el SDK `mcp` lo exige)
python3 -m venv .venv
source .venv/bin/activate

# 3) dependencias DENTRO del venv
python -m pip install --upgrade pip
pip install -r requirements.txt
```

**Verificación**:

```bash
which python          # → $REPO/.venv/bin/python   (no /usr/bin/python)
pip show mcp          # → Name: mcp  Version: 2.3.0
python -c "import mcp; print('mcp OK')"
```

> **Sobre el error `externally-managed-environment`**: es PEP 668. Ubuntu 24.04 marca el Python del sistema
> como gestionado por apt y `pip` se niega a escribir ahí. **No lo resuelvas con
> `--break-system-packages`**: la solución es usar el venv (pasos 2 y 3). Si aún así lo necesitas,
> `pip install --break-system-packages -r requirements.txt` funciona, pero ensucia el Python del sistema.
>
> `requirements.txt` solo pide `mcp>=2.0` (hoy va por la 2.3.0); todo lo demás usa la stdlib y `urllib`.
>
> Si la descarga va lenta: `pip install -i https://pypi.org/simple -r requirements.txt`.

### 2.2 Instalar dependencias

```bash
pip install -r requirements.txt
```

**Verificación**: `python3 -c "import mcp, webrtcvad; print('ok')"` → `ok`.

### 2.3 Ajustar el `.env` del PC

El `.env` **viene con la clave real** y con la configuración del diseño actual. Solo tienes que ajustar la
IP del robot:

```bash
chmod 600 .env
$EDITOR .env          # ajusta TONYPI_HOST (por defecto 192.168.149.1, el modo AP)
```

Claves que usa el código (verificadas en `pc/voice_agent.py` y `pc/server.py`):

```bash
LLM_API_KEY=nvapi-...                      # ← el agente lee ESTE nombre
LLM_BASE_URL=https://integrate.api.nvidia.com/v1
LLM_MODEL=nvidia/nemotron-3.5-bolt-e4b
TONYPI_HOST=192.168.149.1                  # IP del robot (modo AP)
TONYPI_RPC_PORT=9030
TONYPI_MJPG_PORT=8080
ASR_BACKEND=whispercpp                     # o local_server / openai
TTS_BACKEND=espeak                         # o piper / openai
ASR_DEVICE=                                # lo pone bt_headset_pc.sh
TTS_DEVICE=                                # lo pone bt_headset_pc.sh
PONTIBOT_MEMORY=~/.pontibot/memory.json
```

> ⚠️ **El nombre de la variable de la clave es `LLM_API_KEY`**, no `NVIDIA_API_KEY`.
> (`nvidia_models.py` y `nvidia_smoke_test.py` aceptan cualquiera de las dos, pero `voice_agent.py` solo
> lee `LLM_API_KEY`.)

### 2.3b Auditar el `.env`

```bash
bash tools/env_check.sh
```

**Verificación**: te dice qué está bien y qué hay que arreglar, sin mostrar la clave. Comprueba permisos
(600), **fin de línea CRLF de Windows** (que deja la clave con un `\r` y provoca el 401), prefijo `nvapi-`,
modelo, backend de ASR, dispositivos de audio y si falta la ruta del robot.

> ⚠️ Tu `.env` actual está escrito para el diseño **anterior** (agente dentro del robot). Lo que hay que
> rehacer: `ASR_DEVICE` y `TTS_DEVICE` los escribió el `bt_headset.sh` **en el robot**, así que nombran el
> auricular de la Raspberry, no el de tu PC.

### 2.4 Validar la clave contra la API (⚠️ paso crítico)

```bash
bash tools/nvidia_check.sh
```

**Verificación esperada**: `HTTP 200` y la lista de modelos. 

**Si falla**:

| Código | Causa | Solución |
|---|---|---|
| 401 | Clave vacía o mal formada | `grep NVIDIA_API_KEY .env` y comprueba que no tenga CRLF ni comillas |
| 403 | La clave no tiene saldo/permiso o la ruta de salida está bloqueada | Rota la clave en build.nvidia.com/settings |
| 500 + `Missing request extension` | Cabecera `Authorization: Bearer` vacía | Es el error del gateway de NVIDIA, no tuyo |
| 404 | Modelo inexistente para tu clave | `bash tools/nvidia_check.sh --models` y elige uno del catálogo |

> **La clave vive solo en el PC.** Si alguna vez funcionó en el robot, es porque el diseño era otro.

---

## Fase 3 · Audio del PC (micrófono y bocina)

### 3.1 Comprobar si hay servidor PulseAudio y qué dispositivos ve

```bash
pactl info | head -5
pactl list short sources
pactl list short sinks
```

**Verificación**: deben aparecer un `source` y un `sink` de tipo `bluez_` (auricular BT).

### 3.2 ⚠️ Si estás en WSL2: el puente de audio

**Buena noticia: no tienes que instalar PulseAudio en Windows.** Si tienes WSLg (viene con WSL2 en
Windows 11 y en Windows 10 reciente), **ya hay un servidor PulseAudio dentro de WSL** que te trae el
micro y los altavoces de Windows:

- `PULSE_SERVER=unix:/mnt/wslg/PulseServer` (ya viene en el entorno)
- Fuente de entrada (micro): **`RDPSource`**
- Sumidero de salida (altavoces): **`RDPSink`**

Lo único que instalas en WSL son las **herramientas de cliente**:

```bash
sudo apt update
sudo apt install -y pulseaudio-utils
```

**⚠️ Si tienes `PULSE_SERVER` apuntando a otro sitio**, el síntoma es `Connection failure: Connection
refused` aunque WSLg esté perfectamente instalado. Comprueba y corrige:

```bash
grep -rn PULSE_SERVER ~/.bashrc ~/.profile /etc/environment 2>/dev/null
sed -i '/PULSE_SERVER/d' ~/.bashrc
echo 'export PULSE_SERVER=unix:/mnt/wslg/PulseServer' >> ~/.bashrc
source ~/.bashrc
pactl info | grep -E "Default Sink|Default Source"
```

**Primero, el diagnóstico** (un comando y te dice qué te falta y qué hacer):

```bash
bash tools/wslg_check.sh
```

**Requisito imprescindible**: en Windows, el auricular BT debe ser el **dispositivo de entrada por
defecto** (Ajustes → Sistema → Sonido → Entrada) y estar conectado **con el perfil de manos libres
(HFP)**: con solo A2DP tienes audio pero **no micrófono**.

**Verificación**:

```bash
pactl info | grep -E "Server Name|Default Sink|Default Source"
#  Server Name: pulseaudio
#  Default Sink: RDPSink
#  Default Source: RDPSource

pactl list short sources
```

Prueba real de que entra el micro (habla durante 3 s):

```bash
parec -d RDPSource --format=s16le --rate=16000 --channels=1 --file-format=wav /tmp/mic.wav &
sleep 3; kill %1
sox /tmp/mic.wav -n stat 2>/dev/null | grep RMS
```

**Si `pactl info` falla con "Connection refused"** (tienes cliente pero el servidor de WSLg está
muerto — es el error más común):

```bash
wsl --shutdown        # desde PowerShell: cierra TODAS las sesiones WSL
# luego vuelve a abrir la distro
wsl --update          # actualiza WSLg
```

Y comprueba en Windows: **Ajustes → Privacidad y seguridad → Micrófono** → activa "Permitir que las
aplicaciones de escritorio accedan al micrófono" (WSLg captura el micro como un cliente RDP de
escritorio).

> ⚠️ **Latencia**: el audio travels por el canal RDP de WSLg, así que hay ~100-200 ms extra respecto al
> audio nativo. Se nota al hablar, pero no rompe el bot.

---

**Plan B — si WSLg no te da audio** (WSL1, o WSLg roto): instalar PulseAudio **en Windows**.

> El build clásico de OpenSUSE (el que ponía la wiki de freedesktop) **ya no existe**: la URL
> `download.opensuse.org/repositories/multimedia:/audio:/pulseaudio:/windows/` devuelve *"Resource is no
> longer available"*. El sucesor vivo es **[pgaskin/pulseaudio-win32](https://github.com/pgaskin/pulseaudio-win32)**
> (release `v5`, con `pasetup.exe` y `pulseaudio.zip`).

1. Descarga `pasetup.exe` de <https://github.com/pgaskin/pulseaudio-win32/releases/tag/v5> e instálalo
   (o descomprime `pulseaudio.zip` en `C:\pulseaudio`).
2. En `C:\pulseaudio\etc\pulse\default.pa`, descomenta y ajusta:
   ```
   load-module module-native-protocol-tcp auth-ip-acl=127.0.0.1;172.16.0.0/12 auth-anonymous=1
   load-module module-waveout sink_name=output source_name=input
   ```
3. En `C:\pulseaudio\etc\pulse\daemon.conf`: `exit-idle-time = -1` (que no se apague solo).
4. Arranca `C:\pulseaudio\bin\pulseaudio.exe -D`.
5. En WSL: `export PULSE_SERVER=tcp:$(ip route | awk '/default/{print $3}')` (esa IP es el host Windows).
6. Cortafuegos de Windows (PowerShell como administrador):
   ```powershell
   New-NetFirewallRule -DisplayName "PulseAudio WSL" -Direction Inbound -Action Allow `
     -Protocol TCP -LocalPort 4713 -Profile Private
   ```

**Plan C — el agente nativo en Windows**: si nada de lo anterior convence, ejecuta el agente en Windows
con Python y `sounddevice` (WASAPI). Funciona igual con el robot; solo hay que cambiar `vad.py` para
hablar WASAPI en vez de PulseAudio. Te lo preparo si lo necesitas.

### 3.3 Configurar el auricular y escribir las rutas en el `.env`

```bash
bash tools/bt_headset_pc.sh --detect
```

El script: lista sources/sinks → elige el `bluez_` → lo pone como sink por defecto → escribe
`ASR_DEVICE` y `TTS_DEVICE` en el `.env` → mide el RMS de una captura de 2 s.

**Verificación esperada**:

```
ASR_DEVICE=bluez_input.XX.XX.XX.XX.XX.mono
TTS_DEVICE=bluez_output.XX.XX.XX.XX.XX
RMS=0.0234   ← si sale 0.0, el micrófono NO está ozugando
```

### 3.3b Medir de verdad el micro (si el agente se queda en bucle de escucha)

```bash
bash tools/audio_probe.sh
```

Graba 5 s y te dice en qué zona estás:

| RMS | Significado | Qué hacer |
|---|---|---|
| < 0.003 | **Silencio total**: el micro no llega | Permisos de micro en Windows · auricular como entrada por defecto · `wsl --shutdown` |
| 0.003 – 0.012 | Llega pero **por debajo del umbral** | Habla más fuerte, o baja el umbral: `VAD_THRESHOLD=0.005` en el `.env` |
| > 0.012 | El micro funciona | El problema es otro |

El umbral del VAD es `0.012` (energía RMS) y el turno se corta a los 12 s: por eso el agente se queda
imprimiendo "escuchando..." si nunca detecta voz. **Todos los parámetros del VAD se ajustan en el `.env`:**
`VAD_THRESHOLD`, `VAD_MAX_SECONDS`, `VAD_SILENCE_TO_END`, `VAD_SILENCE_TO_START`, `VAD_AGGRESSIVENESS`.

### 3.4 Probar entrada y salida

```bash
bash tools/bt_headset_pc.sh --test
```

**Verificación**: oyes un tono y el RMS del micro sube cuando hablas.

**Si falla con `arecord: no such device`**: estás en ALSA, no en PulseAudio. `vad.py` ya detecta el
dispositivo, pero el script escribe el nombre equivocado → copia el nombre exacto de `pactl list short sources`.

> El auricular **debe soportar HFP/HSP** (manos libres). Con solo A2DP tienes audio pero **no micrófono**.

---

## Fase 4 · Red: que el PC llegue al robot

### 4.1 Elige el modo de red del robot

| Modo | Cómo | ¿Necesita SSH? | Cuándo |
|---|---|---|---|
| **AP (hotspot)** | El robot crea `HW-<serial>`; el PC se conecta a él | **No** (ya estás conectado de la fase 0). IP **fija**: `192.168.149.1` | El robot ya está así de fábrica |
| **STA (router)** | `bash tools/tonypi_wifi.sh --host 192.168.149.1 sta --ssid X --pass Y` | **Sí, una vez** (por el hotspot) | ✅ **El recomendado aquí** |
| **Modo 3** | `bash tools/tonypi_wifi.sh --host 192.168.149.1 --mode 3` | **Sí, una vez** | Robot con cable eth0: mantiene hotspot **y** sale a internet |

#### ⚠️ Por qué te recomiendo STA y no quedarte en AP

El modo AP **no tiene internet** (el DNS del robot apunta a `127.0.0.1`) — pero el problema no es el robot,
es **tu PC**: al conectarte al hotspot `HW-…` tu portátil **deja de estar en tu WiFi de casa** (una sola
radio WiFi), así que **el PC se queda sin internet**… y el LLM y la API los llama el PC.

| | Robot en AP | Robot en tu router (STA) |
|---|---|---|
| Internet del PC | ❌ se pierde al conectar al hotspot | ✅ sigue en tu WiFi |
| Llamadas a la API | ❌ fallarían | ✅ |
| SSH al robot | ✅ por 192.168.149.1 | ✅ por su IP de LAN |
| TONYPI_HOST | `192.168.149.1` | la IP que te dé el router (ej. `192.168.1.50`) |

> Con cable Ethernet en el PC, el modo AP también valdría (la radio WiFi seguiría en tu router).

#### El cambio a STA, paso a paso (SSH por el hotspot)

```bash
# 1) desde el PC, conectado al hotspot del robot
bash tools/tonypi_wifi.sh --host 192.168.149.1 sta --ssid "TU_WIFI" --pass "TU_CLAVE"
```

**Qué va a pasar**: el script edita `~/hiwonder-toolbox/wifi_conf.py` en el robot
(`HW_WIFI_MODE = 2`, ojo: como **entero**, no como texto `'2'`), reinicia el servicio de WiFi y **tu sesión
SSH se cae** — es normal, el robot acaba de cambiar de red.

**Seguridad**: el script deja un watchdog; si el robot no consigue IP de LAN en unos segundos, **vuelve
solo al modo AP**. Para cancelarlo: `bash tools/tonypi_wifi.sh --host <IP> cancel-watchdog`.
Escape físico si te quedas sin acceso: botón **KEY1** de la placa, mantener pulsado hasta que parpadee el
LED azul → vuelve a modo AP.

**Verificación**: cuando el robot ya esté en tu router, tu IP será la del router (no 192.168.149.1). Si no
sabes cuál es, `bash tools/find_robot.sh` la encuentra sola, y `ssh <IP> 'hostname'` confirma que es el
robot.

#### ⚠️ "Compartir conexión a Internet (USB)" no me aparece en Windows

Ese desplegable solo existe si **Windows ve el iPhone como un adaptador de red**. Si no aparece:

| Causa | Cómo se comprueba | Solución |
|---|---|---|
| **El cable USB es solo de carga** (no de datos) | El móvil no muestra "Confiar en este ordenador" | Cambia de cable: uno de datos |
| El iPhone no tiene el hotspot activado | En el iPhone: *Ajustes → Punto de acceso personal* → "Permitir que otros se conecten" | Actívalo **con el cable USB ya conectado** |
| Windows no ha instalado el driver del iPhone | Administrador de dispositivos → *Adaptadores de red* → debe aparecer "Apple Mobile Device Ethernet" o "iPhone USB" | Si no aparece: otro cable, otro puerto USB, o *Propiedades → Instalar* |
| El cable es de un puerto USB que no da datos (solo carga) | — | Puerto trasero del PC, no el del cargador |

**Alternativas que no dependen del tethering por USB:**

| Alternativa | Coste | Cómo |
|---|---|---|
| **Ethernet al router** (lo más limpio) | un adaptador USB-RJ45 (~10 €) | PC por cable al router (internet) + WiFi al hotspot del robot. Las dos cosas a la vez, sin tocar el robot |
| **Un adaptador WiFi USB** | ~10 € | WiFi interno → tu router (internet) + el dongle → hotspot del robot |
| **El robot en tu router (STA)** | 0 € | Ya lo intentas: solo falta que el router le dé IP (ver 4.2b) |

> **Comprueba primero cómo tiene internet tu PC ahora mismo** (la API de NVIDIA ya te funcionaba, así que
> tiene internet por alguna parte):
>
> ```bash
> # en WSL: por dónde sale el tráfico
> ip route get 1.1.1.1
> ```
> ```powershell
> # en PowerShell: qué adaptadores están activos y cuál da la salida a internet
> Get-NetIPConfiguration | Select-Object InterfaceAlias,IPv4Address,IPv4DefaultGateway
> Get-NetAdapter | Where-Object Status -eq 'Up' | Select-Object Name,InterfaceDescription,Status
> ```
>
> Si ya hay un adaptador con puerta de enlace (Ethernet o un segundo WiFi), **el robot puede quedarse en su
> hotspot sin tocar nada**: `TONYPI_HOST=192.168.149.1` y a correr.

#### Automático: `set_robot_ip.sh` (escribe el .env, el alias SSH y verifica)

```bash
# desde el PC, ya en la MISMA red que el robot
bash tools/set_robot_ip.sh 172.20.10.2
```

Hace todo de una vez: escribe `TONYPI_HOST` (y los puertos) en el `.env` con permisos 600, actualiza el
alias `tonypi` de `~/.ssh/config`, hace `ping` al robot y comprueba que responden **:9030** (JSON-RPC) y
**:8080** (snapshot de la cámara). Si algo falla, te dice exactamente qué.

> La IP se lee en el propio robot con: `ip -4 -o addr show wlan0`
> (p. ej. `inet 172.20.10.2/28 brd 172.20.10.15 scope global dynamic`)

#### Manual: actualizar el `.env` y el alias de SSH (en tu PC, en tu red de casa)

El `.env` y el `~/.ssh/config` están **en tu PC**, así que los editas donde estés. Lo único que importa es
el **valor**: la IP del robot **tal y como se ve desde tu red actual**.

| Situación | Valor que va en `TONYPI_HOST` |
|---|---|
| El robot ya está en tu router (STA) | su IP de LAN, p. ej. `192.168.1.50` |
| El robot sigue en su hotspot (AP) | `192.168.149.1` (fija) |

**Automático** (encuentra la IP y la escribe):

```bash
IP=$(bash tools/find_robot.sh | grep -oE 'TONYPI_HOST=[0-9.]+' | cut -d= -f2)
echo "IP detectada: $IP"
sed -i "s|^TONYPI_HOST=.*|TONYPI_HOST=$IP|" .env
sed -i "s|HostName .*|HostName $IP|" ~/.ssh/config
grep '^TONYPI_HOST=' .env
```

> ⚠️ `find_robot.sh` barre la red **de tu PC**, así que úsalo cuando tu PC esté en la red donde quieres
> encontrar al robot: en tu WiFi de casa si lo pasaste a STA, o en el hotspot si lo dejaste en AP.
> Si no encuentra nada, `ping -c2 192.168.149.1` (AP) o mira la IP del robot en el panel de tu router.

### 4.2 Averiguar la IP real del robot (⚠️ trampa de WSL)

```bash
bash tools/find_robot.sh
```

**Verificación**: imprime la IP del robot tal y como la ve la red real.

> En WSL, `ip route` te devuelve la red **virtual** de WSL (172.30.x.x), no la del robot. Por eso existe
> `find_robot.sh`: le pide a Windows **qué adaptador tiene puerta de enlace** (el único por el que sales a
> internet = la red donde puede estar el robot) y barre **solo ese /24**. Antes barría el /24 de *cada*
> IP de Windows, incluidas las de WSL, Docker y las que no tienen nada que ver.

**Si sabes la MAC del robot, el método infalible** (no depende de subredes):

```bash
# la MAC del robot está en su log: d8:3a:dd:6f:05:03
bash tools/find_robot.sh --mac d8:3a:dd:6f:05:03
```

Equivalente en Windows (PowerShell), que es donde vive la tabla ARP real:

```powershell
arp -a | findstr "d8-3a-dd-6f-05-03"
```

> **"Host de destino inaccesible"** significa que tu PC **no tiene ruta** hacia esa subred. O sea: el robot
> está en otra red (por ejemplo el hotspot del iPhone, `172.20.10.0/24`) y tú estás en otra (tu router,
> `192.168.1.0/24`). Conéctate a la misma red que el robot y repite.

### 4.1b ⭐ La vía oficial: la app de Hiwonder (LAN Mode)

Antes de pelearte con el script, prueba **la app**, que es el camino que soporta el propio fabricante:

1. Abre la app de Hiwonder (WonderPi / Hiwonder) en el móvil.
2. *Avanzado → TonyPi → + → **Conexión directa (AP)*** para añadirlo la primera vez.
3. Luego: *+ → **Modo LAN*** → elige tu WiFi de casa (la del router, **no** el hotspot del iPhone) y
   escribe la contraseña.
4. El robot entra en tu router, pide IP por DHCP y la app te muestra su **número de IP**.

Ventaja: la app escribe el fichero de configuración **exactamente donde lo espera el firmware** de tu
versión, y reinicia el servicio correcto. Por eso a veces el script no funciona y la app sí.

> ⚠️ La app necesita el robot en AP para la primera configuración; después ya está en LAN.

### 4.2b Si el robot NO cambia de modo: diagnóstico

```bash
# 1) qué ve el robot ahora mismo
bash tools/tonypi_wifi.sh --host 192.168.149.1 probe

# 2) qué configuración quedó escrita (OJO: el fichero se llama hw_wifi.py / hw_remote.py,
#    no wifi_conf.py — este robot no lo tiene)
ssh pi@192.168.149.1 'grep -rnE "HW_WIFI_MODE|STA_SSID" ~/hiwonder-toolbox/*.py'

# 3) qué pasó en el intento (log del script y del watchdog)
ssh pi@192.168.149.1 'cat ~/tonypi_wifi_result.log; echo ---; tail -15 ~/tonypi_wifi_watchdog.log 2>/dev/null'

# 3b) ¡los logs del intento están en el BOOT ANTERIOR! (el robot reinició y el
#     journal de este boot empieza DESPUÉS del intento)
ssh pi@192.168.149.1 'sudo journalctl --list-boots'
ssh pi@192.168.149.1 'sudo journalctl -b -1 -u hw_wifi.service --no-pager | tail -40'

# 3c) y el log propio de wpa_supplicant (aquí va el motivo real del fallo)
ssh pi@192.168.149.1 'sudo cat /var/log/wpa_supplicant*.log 2>/dev/null | tail -20'

# 3d) ¿qué ejecuta el servicio y qué fichero manda?
ssh pi@192.168.149.1 'systemctl cat hw_wifi.service'

# 4) interfaz y servicios de WiFi
ssh pi@192.168.149.1 'ip -4 addr show | grep "inet "; systemctl list-unit-files | grep -i wifi'
```

#### Causas más probables (de más a menos frecuente)

| # | Causa | Cómo se ve | Solución |
|---|---|---|---|
| 1 | **El router tiene 2.4 + 5 GHz con el MISMO SSID** | El robot se queda en AP sin errores | Separa los SSIDs (o desactiva la banda de 5 GHz). El TonyPi v1.0 (Pi 4B) **solo es 2.4 GHz** |
| 2 | **WPA3-only o WPA2-Enterprise** | No se conecta | Necesita **WPA2-Personal**. Cambia el tipo de seguridad del router |
| 3 | **`sudo` pidió contraseña y no la tecleaste** | El log dice "sudo pide contraseña" | Vuelve a lanzarlo y teclea la clave cuando la pida |
| 4 | **El watchdog hizo rollback** | El log dice "sin IP de LAN → vuelvo al modo AP" | El robot **sí** cambió y volvió: el router no le dio IP. Revisa el punto 1 y 2, y sube el margen: `--watchdog-delay 300` |
| 5 | **Portal cautivo** | Se conecta pero no hay internet | Apaga el portal o usa otra red |
| 6 | El servicio que lee `HW_WIFI_MODE` no arrancó | `iw dev wlan0 info` dice "type AP" | El script prueba los dos servicios; si falla, reinicia a mano: `sudo systemctl restart wifi.service` |

#### Plan manual (si el script no funciona): la config por SSH

```bash
# 1) copia de seguridad
ssh pi@192.168.149.1 'cp ~/hiwonder-toolbox/wifi_conf.py ~/wifi_conf.py.bak'

# 2) escribir el modo 2 (ENTERO, no texto) con tu SSID y clave
#    OJO: hay que tocar TODOS los ficheros que tengan HW_WIFI_MODE
#    (hw_wifi.py y hw_remote.py); si solo se toca uno, el otro lo revierte.
ssh pi@192.168.149.1 'python3 - <<EOF
import re, pathlib
p = pathlib.Path.home() / "hiwonder-toolbox" / "wifi_conf.py"
s = p.read_text()
s = re.sub(r"^\s*HW_WIFI_MODE\s*=.*$", "HW_WIFI_MODE = 2", s, flags=re.M)
s = re.sub(r"^\s*HW_WIFI_STA_SSID\s*=.*$", "HW_WIFI_STA_SSID = \"TU_WIFI\"", s, flags=re.M)
s = re.sub(r"^\s*HW_WIFI_STA_PASSWORD\s*=.*$", "HW_WIFI_STA_PASSWORD = \"TU_CLAVE\"", s, flags=re.M)
p.write_text(s)
EOF
grep -E "HW_WIFI_MODE|STA_SSID" ~/hiwonder-toolbox/wifi_conf.py'

# 3) reiniciar el servicio de WiFi (la sesión SSH se caerá)
ssh pi@192.168.149.1 'sudo systemctl restart wifi.service'
```

> Tras reiniciar, el robot pide IP por DHCP a tu router. Si a los ~30 s no la tiene, vuelve al AP (por seguridad
> del firmware). Míralo con `ssh pi@192.168.149.1 'ip -4 addr show'` antes de que se caiga, o busca la IP en el
> panel de tu router.

#### ⚠️ Si el ping al robot falla: comprueba en qué red está el PC

```bash
# en WSL: por qué interfaz sale el tráfico hacia el robot
ip route get 172.20.10.2
```

Sale algo como `172.20.10.2 via 192.168.1.1 dev eth0 src 192.168.1.42` → el **`src`** es la red del PC.
Si tu PC está en `192.168.1.x` y el robot en `172.20.10.x`, **no hay ruta entre ellos**: conéctate a la
misma red que el robot (por ejemplo la WiFi "iPhone de Cordoba") y repite.

En Windows (PowerShell), donde vive la tabla ARP real:

```powershell
Get-NetIPConfiguration | Where-Object {$_.IPv4Address} | Select-Object InterfaceAlias,IPv4Address,IPv4DefaultGateway
arp -a | findstr "d8-3a-dd-6f-05-03"
```

### 4.3 Probar conectividad en los dos puertos

```bash
ROBOT=<IP_DEL_ROBOT>
ping -c 3 $ROBOT
curl -s -o /dev/null -w 'rpc=%{http_code}\n' http://$ROBOT:9030/
curl -s -o /tmp/snap.jpg -w 'snapshot=%{http_code} bytes=%{size_download}\n' "http://$ROBOT:8080/?action=snapshot"
```

**Verificación esperada**: `snapshot=200 bytes=…` con un JPEG de **tamaño > 5 KB** (si sale 0 bytes, la cámara
no está arrancada → fase 5.3).

---

## Fase 5 · ⚠️ El "modo de prueba": neutralizar el arranque de fábrica

**Esta es la fase que más problemas causa. Léela entera.**

### 5.1 Qué hace el robot al arrancar (verificado en el firmware)

`tonypi.service` → `/home/pi/TonyPi/TonyPi.py` → al importar `RPCServer.py` ocurre esto, **en este orden**:

1. `ctl.set_buzzer(1900, 0.1, 0.9, 1)` → **un pitido** (1900 Hz, 0,1 s).
2. `ColorTrack.initMove()` → prepara el seguimiento de color.
3. `AGC.runActionGroup('stand_slow')` → **el robot se pone de pie** (acción de arranque, ~1-2 s).

Y a partir de ahí, el hilo principal del robot hace esto en bucle:

```python
if Running.RunningFunc > 0 and Running.RunningFunc <= 12:
    img = Running.CurrentEXE().run(cam.frame.copy())   # ← programa de juego
```

`RunningFunc` es un entero 0-12: 0 = reposo; 1-12 = un juego (control remoto,踢球, gestos, seguimiento de
línea, tracking de color, cara, AprilTag, transporte, ajuste LAB, hurdles, escaleras, clasificación de color).

### 5.2 Por qué esto rompe nuestro MCP server (el motivo real)

Las llamadas RPC **no se ejecutan en el hilo del servidor**: se encolan en una `Queue` y las consume el
**hilo principal** (`runbymainth` → `QUEUE.put(...)` → espera el resultado con un tope de **200 × 0,01 s = 2 s**).

Consecuencia: **si hay una función de juego cargada, el hilo principal está ocupado y nuestras llamadas
expiran con `E04 - Operation timeout!`** — el MCP server devuelve error y el LLM cree que el robot falló.

Y ojo con dos trampas del firmware:

| Trampa | Qué hacer |
|---|---|
| `GetRunningFunc` **siempre devuelve 0** (la llamada real está comentada en el firmware: `return (True, (0,))`) | **No confíes en él.** Llévalo como si siempre dijera 0 |
| El juego se autocancela si pasan 7 s sin `Heartbeat` | Enviar `Heartbeat` mantiene vivo un juego → no lo hagas nunca |

### 5.3 Diagnóstico: ¿estoy realmente en reposo?

```bash
ROBOT=<IP_DEL_ROBOT>
curl -s -X POST http://$ROBOT:9030/ -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"UnloadFunc","params":[],"id":1}'
```

**Verificación esperada**:

```json
{"jsonrpc": "2.0", "result": [true, [0]], "id": 1}
```

`UnloadFunc` es **idempotente**: si no hay nada cargado, devuelve lo mismo sin romper nada. **Ejecútalo
siempre después de cada arranque del robot.**

### 5.4 Elige cómo dejarlo resuelto

#### Opción A — Mantener el servicio de fábrica (mínimo-invasive) ✅ recomendada para empezar

- `tonypi.service` **sigue activo** → el JSON-RPC `:9030` y el MJPG `:8080` siguen vivos.
- Tras cada arranque, el PC ejecuta `UnloadFunc` una vez (fase 8, paso 8.2).
- El robot seguirá haciendo el pitido + `stand_slow` al arrancar: es el arranque de fábrica y **no molesta**
  (ocurre antes de que hablemos).

**Limitación**: si algo carga una función (el toolbox de Hiwonder, una demo), hay que llamar a `UnloadFunc`
y esperar. Se puede automatizar (fase 8.2) pero no es determinista al 100 %.

#### Opción B — Servicio propio "solo RPC" (determinista) ✅ recomendada para producción

Un servicio que arranca **el mismo RPCServer y el mismo MJPG**, pero **sin el bucle de juego**, con
`RunningFunc` forzado a 0 para siempre.

```bash
# 1) Copiar el main de fábrica y aplicar el cambio
ssh tonypi 'cp /home/pi/TonyPi/TonyPi.py /home/pi/TonyPi/TonyPi_rpc_only.py'

# 2) Subir el fichero preparado (ver robot/TonyPi_rpc_only.py del paquete)
scp robot/TonyPi_rpc_only.py tonypi:/home/pi/TonyPi/

# 3) Instalar la unidad
scp robot/tonypi-rpc.service tonypi:/etc/systemd/system/
ssh tonypi 'sudo systemctl daemon-reload && \
  sudo systemctl disable tonypi.service && \
  sudo systemctl enable --now tonypi-rpc.service'

# 4) Verificar
ssh tonypi 'systemctl is-active tonypi-rpc.service; ss -ltnp | grep -E "9030|8080"'
```

**Verificación esperada**: `active` + `LISTEN ... :9030` + `LISTEN ... :8080`.

**Rollback de la opción B** (vuelve al servicio de fábrica):

```bash
ssh tonypi 'sudo systemctl disable --now tonypi-rpc.service && \
  sudo systemctl enable --now tonypi.service'
```

> ⚠️ `TonyPi_rpc_only.py` está derivado del `TonyPi.py` de Hiwonder para **Pi 5**. Tu robot es un v1.0
> (Buster, Python 3.7). **Compara antes de instalar**:
> `diff /home/pi/TonyPi/TonyPi.py robot/TonyPi_rpc_only.py` y ajusta solo las rutas/módulos que difieran.
> El cambio clave son 3 líneas: se elimina la rama `Running.CurrentEXE().run(...)` y se fuerza
> `Running.RunningFunc = 0`.

### 5.5 ⚠️ No hagas esto

```bash
sudo systemctl stop tonypi.service     # ❌ NO
```

Aparcarlo mata **el propio servidor JSON-RPC y el de vídeo**, porque viven en ese mismo proceso. Es lo que
recomienda el curso oficial de Hiwonder para sus demos (que ejecutan su propio programa), pero **no** es
válido para nuestro diseño: nous quedamos sin canal de control.

### 5.6 Esperar al arranque antes de mandar la primera orden

El robot tarda ~60 s en arrancar y la acción `stand_slow` coge los servos 1-2 s. Espera a que el puerto
responda:

```bash
until curl -s -o /dev/null http://$ROBOT:9030/; do sleep 2; done; echo "RPC listo"
```

---

## Fase 6 · Prueba del canal de control (sin LLM)

### 6.0 Batería de movimientos (sin LLM, para aislar fallos)

```bash
bash tools/test_movimientos.sh                 # usa TONYPI_HOST del .env
bash tools/test_movimientos.sh 172.20.10.2 wave bow chest
```

Comprueba conectividad, que el robot esté en reposo, ejecuta varios action groups, para el movimiento y
verifica la cámara. **Si aquí el robot se mueve → el canal de control funciona** y cualquier fallo
posterior es del LLM, no de la red.

### 6.1 Comprobar que el robot ejecuta una orden

```bash
curl -s -X POST http://$ROBOT:9030/ -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"RunAction","params":["bow",1],"id":2}'
```

**Verificación**: el robot se inclina y la respuesta es `result: [true, []]`.

### 6.2 Comprobar la visión

```bash
curl -s -o /tmp/snap.jpg -w '%{http_code} %{size_download}\n' "http://$ROBOT:8080/?action=snapshot"
file /tmp/snap.jpg
```

**Verificación**: `JPEG image data` con > 5 KB.

> Detalle fino del firmware: `/?action=snapshot` sirve la variable `img_show`, **la misma** que el stream. Y
> cualquier otra ruta (p. ej. `http://robot:8080/`) pone `img_show = None`. Por eso el servicio debe seguir
> refrescando `img_show` en su bucle aunque quitemos el juego. Si el snapshot devuelve 0 bytes, es eso.

### 6.3 Probar el protocolo completo sin robot

```bash
python3 tools/mock_robot.py &      # simulador con el protocolo real
python3 tools/selftest.py           # 28/28 checks
```

**Verificación**: `28/28 OK`.

---

## Fase 7 · Limpieza del despliegue anterior (el robot ya no aloja nada)

El diseño anterior metía el agente de voz y **la clave de NVIDIA** en el robot. Hay que quitarlo.

### 7.1 Inventario de lo que quedó en el robot

```bash
ssh tonypi 'systemctl is-active pontibot.service 2>/dev/null; ls -la /home/pi/tonypi-mcp 2>/dev/null; \
  ls -la ~/.pontibot 2>/dev/null'
```

### 7.2 Desactivar y borrar el servicio del agente

```bash
ssh tonypi 'sudo systemctl disable --now pontibot.service 2>/dev/null; \
  sudo rm -f /etc/systemd/system/pontibot.service; sudo systemctl daemon-reload'
```

### 7.3 Borrar nuestro código y la clave del robot

```bash
ssh tonypi 'sudo rm -rf /home/pi/tonypi-mcp ~/.pontibot; \
  grep -rl "nvapi-" /home/pi 2>/dev/null | head'
```

**Verificación**: el último comando **no debe imprimir nada**. Si imprime una ruta, la clave sigue en el
robot: bórrala.

### 7.4 ⚠️ Rota la clave si el zip o el repo se compartieron

```bash
bash tools/nvidia_check.sh
```

**Verificación**: 200 con la clave nueva. La clave antigua, revocada en build.nvidia.com/settings, ya no
sirve para nada porque el robot no la tiene.

### 7.5 El parche de firmware (opcional)

Solo si quieres que el robot **suene** (buzzer) o **hable** por su altavoz. En el diseño actual el audio
sale por el PC, así que es opcional:

```bash
bash tools/deploy_to_robot.sh --host $ROBOT --patch
```

**Verificación**: el robot acepta `SetBuzzer` y `PlayAudio` por RPC.

> El parche es **reversible** (`PLAN.md` documenta cómo revertirlo).

---

## Fase 8 · Arrancar el bot

### 8.1b Probar el cerebro sin micrófono (texto en vez de voz)

```bash
cd pc && python3 voice_agent.py --text "saluda y haz una reverencia"
```

Ejercita TODO el circuito salvo la captura de audio: LLM → tool call → MCP → JSON-RPC → robot. Si el
robot se mueve con esto, el problema (si lo hay) está solo en el micro.

### 8.1 Prueba manual primero

```bash
cd "$REPO"
source .venv/bin/activate
cd pc && python3 voice_agent.py
```

**Verificación en el log**:

```
[audio] fuente=bluez_input.…  RMS=0.021
[asr] whisper.cpp base —  "ponte de pie"
[llm] nvidia/nemotron-3.5-bolt-e4b — tool_calls=1
[mcp] → robot_do_action(pose="stand")
[rpc] POST :9030 RunAction → [true, []]
[tts] …
```

### 8.2 Que el robot quede en reposo automáticamente tras cada arranque (opción A)

Añade al `.env`:

```bash
ROBOT_UNLOAD_ON_START=1
```

…y en el arranque del agente, antes de la primera llamada, el agente manda `UnloadFunc` al `:9030` y espera
respuesta. Es el **fix-up barato** que cubre el 95 % de los casos.

### 8.3 Dejarlo arrancando solo en el PC (opcional)

Como servicio de usuario en el PC (no del robot):

```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/pontibot.service <<EOF
[Unit]
Description=PontiBot · agente de voz TonyPi
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$REPO/pc
ExecStart=$REPO/.venv/bin/python3 voice_agent.py
Environment=PULSE_SERVER=tcp:127.0.0.1:4713
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

# OJO: systemd NO lee tu .bashrc → expande $REPO antes de generar el unit.
systemctl --user daemon-reload
systemctl --user enable --now pontibot.service
systemctl --user status pontibot.service
```

> El heredoc usa `EOF` **sin comillas** a propósito: así `$REPO` se expande a tu ruta real al crear el servicio. En WSL, `systemctl --user` requiere un login
> persistente (`loginctl enable-linger $USER`).

---

## Fase 9 · Verificación extremo a extremo (checklist)

| # | Comprobación | Cómo | Esperado |
|---|---|---|---|
| 1 | El robot arranca solo y hace el pitido + se pone de pie | Encender y mirar | Un pitido, se pone de pie |
| 2 | El JSON-RPC responde | `curl … :9030/` | `200` |
| 3 | `UnloadFunc` deja el robot en reposo | fase 5.3 | `[true, [0]]` |
| 4 | El robot ejecuta una orden | `RunAction bow` | Se inclina, `[true, []]` |
| 5 | La cámara entrega snapshot | fase 6.2 | JPEG > 5 KB |
| 6 | El micro del PC suena | `bt_headset_pc.sh --test` | RMS > 0.01 al hablar |
| 7 | La API responde desde el PC | `nvidia_check.sh` | `200` |
| 8 | El ASR transcribe | Hablar al micro | Texto en el log |
| 9 | El LLM llama a una tool | Pedir "ponte de pie" | `tool_calls=1` en el log |
| 10 | El robot se mueve | Mirar el robot | Se pone de pie |
| 11 | El bot **responde por el altavoz** | Oír | Voz en español |
| 12 | La clave **no** está en el robot | fase 7.3 | Sin salida |

---

## Fase 10 · Rollback

| Quiero | Comando |
|---|---|
| Volver al diseño anterior (agente en el robot) | `deploy_to_robot.sh --host $ROBOT --with-service` y seguir la guía antigua |
| Volver al servicio de fábrica | `sudo systemctl disable --now tonypi-rpc.service && sudo systemctl enable --now tonypi.service` |
| Quitar el parche de firmware | Ver `PLAN.md` (sección de reversión) |
| Parar el bot en el PC | `systemctl --user stop pontibot.service` |
| Apagar todo | Apagar el robot y `Ctrl+C` en el terminal del agente |

---

## Fase 11 · Matriz de fallos → causa

| Síntoma | Causa probable | Solución |
|---|---|---|
| `E04 - Operation timeout!` en todas las tools | Hay una función de juego cargada: el hilo principal está ocupado | Fase 5.3 (`UnloadFunc`) o opción B de la fase 5.4 |
| `HTTP 403` de NVIDIA | Clave sin saldo o ruta bloqueada | `nvidia_check.sh`; rota la clave. **Si te pasa desde el robot: no debería, la API se llama desde el PC** |
| `Missing request extension … axum::Extension` | Cabecera `Authorization: Bearer` vacía | El `.env` no se está leyendo; revisa `NVIDIA_API_KEY` y que no tenga CRLF |
| El bot no oye (RMS 0.0) | En WSL no hay puente de audio | Fase 3.2 |
| `arecord: no such device` | `vad.py` cayó a ALSA en vez de PulseAudio | Copia el nombre exacto de `pactl list short sources` a `ASR_DEVICE` |
| `curl: (7) connection refused` en `:9030` | `tonypi.service` parado, o el robot en otra red | `systemctl status tonypi.service`; fase 4 |
| `error: externally-managed-environment` | PEP 668: Ubuntu protege el Python del sistema | Usa el venv: `python3 -m venv .venv && source .venv/bin/activate` **antes** de `pip install` |
| `ensure you have python3-full installed` | Falta el módulo `venv` | `sudo apt update && sudo apt install -y python3-venv python3-full` |
| `E: Unable to locate package python3-xyz` | `xyz` era un ejemplo literal del mensaje de Python | Sustituye `xyz` por el paquete real |
| `ssh: Permission denied (publickey,password)` | Contraseña equivocada: **4B = `raspberry`**, Pi 5 = `raspberrypi` | Fase 0.2 |
| Snapshot 0 bytes | `img_show` está a None (alguien pidió `/` en el 8080) o la cámara no arrancó | Refresca `img_show` (fase 5.4 opción B); reinicia el servicio |
| El robot se mueve solo al arrancar | Es `stand_slow`, el arranque de fábrica | Normal, dura 1-2 s. Si *sigue*, hay un juego cargado → fase 5.3 |
| `GetRunningFunc` devuelve 0 pero el robot está ocupado | El firmware miente en ese método | No uses ese método: usa `UnloadFunc` y observa el comportamiento |
| El robot recibe órdenes pero no se mueve | Servos sin alimentación o bus desconectado | Fase 0.5 |

---

## Apéndice · Resumen de rutas tras el despliegue

```
PC  ── ssh/scp ──▶  ROBOT
     .env (600)      /home/pi/TonyPi/            ← fábrica (intocable)
     pc/*.py           /home/pi/TonyPi/TonyPi_rpc_only.py  ← opcional
     tools/*.sh        /etc/systemd/system/tonypi-rpc.service ← opcional
                       patches → /home/pi/TonyPi/robot_patch/ ← opcional
     ~/.pontibot/memory.json
```

```
PC :9030 ◀── JSON-RPC 2.0 ──▶ ROBOT :9030
PC :8080 ◀── HTTP snapshot ──▶ ROBOT :8080
PC ────── HTTPS ──────────────▶ api.nvidia.com/v1  (la única salida a internet)
```


---

## Fase 2 (diferida) · Retomar la interacción por voz

**Todo lo de audio sigue montado y probado; solo falta activarlo cuando quieras.**

| Pieza | Estado | Nota |
|---|---|---|
| `pc/vad.py` | ✅ listo | Detección de voz con energía RMS o webrtcvad; umbral ajustable (`VAD_THRESHOLD`) |
| `pc/voice_agent.py` (modo voz) | ✅ listo | Es el modo por defecto: `--chat` lo desactiva |
| `tools/audio_probe.sh` | ✅ listo | Mide el RMS del micro y dice si el VAD te oye |
| `tools/bt_headset_pc.sh` | ✅ listo | Detecta el auricular BT del PC y escribe `ASR_DEVICE`/`TTS_DEVICE` |
| `ASR` (whisper.cpp) | ⚠️ falta en el PC | `bash tools/setup_pi.sh --with-whisper` lo compila; en el PC es más rápido (x86_64) |
| `TTS` (espeak) | ✅ en el PC | `sudo apt install -y espeak-ng` |
| `.env` (audio) | ✅ configurado | `ASR_DEVICE`, `TTS_DEVICE`, `VAD_*` — se conservan tal cual |

**Lo que falta para la voz** (cuando te apetezca):

1. Que el micro de Windows llegue a WSLg. Es el único punto que no funcionaba: el `RDPSource` de WSLg
   daba `Failed to open audio file`. Causas: permisos de micro en Windows, el auricular no estaba como
   entrada por defecto, o el nombre de la fuente no era `RDPSource` (se comprueba con
   `pactl list short sources`).
2. `whisper` compilado en el PC.
3. `webrtcvad-wheels` instalado (ya está).

Con eso, `python3 voice_agent.py` (sin `--chat`) funciona igual que ahora, pero hablandole.

**Y si algún día quieres que el bot también hable en modo chat**: `--chat --speak`.

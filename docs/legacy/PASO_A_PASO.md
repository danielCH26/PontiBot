# TonyPi + PontiBot · Paso a paso

> **Qué va en tu PC y qué va en el robot, y qué orden ejecutar.**
> Esta guía sustituye a `GUIA_PASO_A_PASO.md` (más antigua, escrita antes de
> conocer la imagen real del robot: es **Raspbian Buster**, no Ubuntu).

---

## 0 · El mapa en 30 segundos

| Qué | Dónde va | Cómo lo mueves |
|---|---|---|
| `tonypi-mcp.zip` (el proyecto) | **PC → Robot** | `scp` por SSH |
| Clave de NVIDIA (`nvapi-…`) | **Robot** (en `.env`) | `deploy_to_robot.sh --key` o escribiéndola a mano |
| `tonypi_wifi.sh` | **PC** (se copia solo al robot si usas `--host`) | automático |
| Config del WiFi (`wifi_conf.py`) | **Robot** | la edita `tonypi_wifi.sh` solo |
| Paquetes del sistema (alsa, ffmpeg, bluez…) | **Robot** | `setup_pi.sh` (necesita internet) |
| `pontibot.service` | **Robot** | `setup_pi.sh --with-service` |
| **Servidor MCP** | **PC** | `python server.py` / config de tu cliente |
| **Agente de voz** | **Robot** (o PC, si prefieres) | `voice_agent.py` |

---

## 1 · Antes de empezar: qué necesitas

**En tu PC:**
- El proyecto: descarga `tonypi-mcp.zip` (adjunto a este mensaje).
- Un cliente SSH (Windows 10+: PowerShell ya lo trae; macOS/Linux: terminal).
- La clave de NVIDIA: la tienes guardada como el secreto **`NVIDIA_API_KEY`**
  en Mavis (panel de secretos) o en el `.env` de la copia anterior del proyecto.

**En el robot:**
- Nada nuevo: ya tiene el proyecto en `/home/pi/tonypi-mcp` (eso es lo que
  estabas ejecutando en la foto).

**Y una decisión de una vez:** ¿de qué audio va a hablar el robot?
- Bluetooth ( WonderEcho / auriculares) → perfil **Headset** en `pavucontrol`.
- Jack 3.5 mm o micro USB → conéctalo y lo verá `audio_doctor.py`.

No lo decidas todavía: `audio_doctor.py` te dirá qué hay conectado.

---

## 2 · Cómo te conectas al robot (3 métodos)

| Método | Para qué | Cuándo funciona |
|---|---|---|
| **VNC** (escritorio remoto) | ver la pantalla, abrir una terminal | siempre |
| **SSH por el hotspot** (`pi@192.168.149.1`, clave `raspberry`) | todo lo que hagas por línea de comandos | **sin internet** ← úsalo ahora |
| **SSH por tu red** (`pi@<IP_NUEVA>`) | lo mismo, ya con internet | después del cambio de red |
| JSON-RPC (puerto 9030) | protocolo del robot: lo usan el MCP y el agente | siempre |

> El hotspot del robot se llama `HW…` y su contraseña es `hiwonder`.
> SSH **sí funciona sobre ese hotspot**, aunque no haya internet: por eso
> puedes diagnósticar y cambiar la red sin haber arreglado nada todavía.

**Comprueba ahora mismo que SSH responde** (desde tu PC):

```bash
ssh pi@192.168.149.1
# clave: raspberry   (usuario: pi)
```

Si entra, tienes control total del robot y todo lo de abajo funciona.

---

## 3 · Fase 1 — Diagnóstico de la red

**EN TU PC** (recomendado; el script se copia solo al robot por SSH):

```bash
bash tonypi_wifi.sh --host 192.168.149.1 probe
```

**O EN EL ROBOT** (terminal de VNC):

```bash
bash ~/tonypi-mcp/tonypi_wifi.sh probe
```

Te dice: interfaces y rutas, si estás en el rango del hotspot, si el WiFi
integrado está cargado (`brcmfmac`), si hay `dtoverlay=disable-wifi`, si hay un
dongle USB, qué servicios de Hiwonder existen, el valor de `HW_WIFI_MODE`, si
el cable de red tiene enlace y si la API de NVIDIA responde.

**Pásame esa salida** y te digo el camino exacto. Pero mientras tanto:

---

## 4 · Fase 2 — Que el robot tenga internet

### Opción A · Cable de red (1 minuto, la más fiable)

1. Enchufa un **RJ45** del robot al router (o a un switch).
2. **EN EL ROBOT:**
   ```bash
   ip -br addr show eth0     # la IP que da el router
   ping -c3 1.1.1.1          # si responde, ya hay internet
   ```

Con esto ya puedes instalar todo. El WiFi es para la movilidad, no te bloquees.

### Opción B · WiFi con tu router

**EN TU PC:**

```bash
bash tonypi_wifi.sh --host 192.168.149.1 sta --ssid "TU_RED"
# te pide la contraseña de forma oculta (no queda en el historial)
```

**O EN EL ROBOT:**

```bash
bash ~/tonypi-mcp/tonypi_wifi.sh sta --ssid "TU_RED"
```

**Qué va a pasar:**

| Momento | Qué ocurre |
|---|---|
| 1 | Se guarda copia de la config y se lanza un **vigilante de 3 minutos** |
| 2 | Se reinicia el servicio de WiFi → **tu sesión SSH/VNC se cae** (normal) |
| 3 | El robot entra en tu red y recibe IP nueva del router |
| 4 | El vigilante confirma que tiene IP y **no toca nada** |

**Si en 3 minutos no consigue IP**, el vigilante **vuelve solo al modo AP** y
recuperas el robot (tu hotspot vuelve). También puedes forzarlo:

```bash
bash ~/tonypi-mcp/tonypi_wifi.sh ap
```

**Escape físico** si el robot se queda inaccesible: botón **KEY1** de la placa,
mantener pulsado hasta que parpadee el LED azul → vuelve al modo AP.

**Reconectar tras el cambio:** lo más rápido es dejar que el script lo busque:

```bash
# desde tu PC, YA conectado a la red donde esta el robot (p.ej. el hotspot
# del movil). Escanea la subred y ademas le pregunta JSON-RPC para confirmar
# que el que responde es el TonyPi:
bash tonypi_wifi.sh find-ip
```

Te imprime la IP y las dos órdenes listas para copiar:

```
  [OK]    192.168.43.57 responde como TonyPi (JSON-RPC) -> ese es el robot
           ssh pi@192.168.43.57
           bash tonypi_wifi.sh --host 192.168.43.57 cancel-watchdog
```

Otras formas de saber la IP:

| Método | Cómo |
|---|---|
| **El móvil** | Ajustes → Punto de acceso → *Dispositivos conectados* → el robot → IP |
| **mDNS** | `ssh pi@raspberrypi.local` (el hostname del robot es `raspberrypi`) |
| **El router** | tabla de DHCP, busca el host `raspberrypi` |

> **Dato importante:** el watchdog dura 3 minutos. Si el robot no consigue IP,
> vuelve solo al modo AP (y tu PC tendrá que volver al hotspot `HW-…` del
> robot). Si tardas en encontrarlo, da más margen:
> `bash tonypi_wifi.sh --host 192.168.149.1 sta --ssid "TU_RED" --watchdog-delay 600`

Cuando vuelvas a conectarte, ya con la IP nueva:

```bash
ssh pi@<IP_NUEVA>
bash ~/tonypi-mcp/tonypi_wifi.sh cancel-watchdog   # ya no hace falta el vigilante
```

> **Ojo:** el Pi 4B solo es 2.4 GHz. Si tu router emite `MiRed` y `MiRed_5G`,
> usa la de 2.4. Si tu red es WPA3-only o de empresa, usa el **hotspot del
> móvil** (2.4 GHz, WPA2): es la solución universal.

---

## 5 · Fase 3 — Poner el código actualizado en el robot

**EN TU PC:**

```bash
# 1. descomprime el zip (si aún no lo has hecho)
unzip tonypi-mcp.zip            # en Windows: Explorador → Extraer todo

# 2. comprueba que llegas por SSH
ssh pi@192.168.149.1 "echo ok"

# 3. copia el proyecto al robot (NO el zip entero, la carpeta ya existe)
scp -r tonypi-mcp/* pi@192.168.149.1:/home/pi/tonypi-mcp/
```

**EN EL ROBOT** (comprueba):

```bash
cd ~/tonypi-mcp && ls | head
# deben aparecer: setup_pi.sh  tonypi_wifi.sh  requirements-pi.txt  ...
```

> ¿Prefieres copiar el zip entero? Alternativa en el robot:
> ```bash
> cd ~ && python3 -m zipfile -e tonypi-mcp.zip . && ls tonypi-mcp
> ```

---

## 6 · Fase 4 — Instalar (OJO: es Buster, hay que arreglar los repos)

**EN EL ROBOT:**

```bash
cd ~/tonypi-mcp
bash setup_pi.sh --fix-repos --with-service
```

Qué hace, en orden:

| Paso | Qué ocurre |
|---|---|
| **Check de red** | si no hay DNS, te lo dice y para (no sigue installing a ciegas) |
| **`--fix-repos`** | Buster está archivado: apunta a `archive.debian.org` / `legacy.raspbian.org`, comenta el repo muerto y desactiva `Check-Valid-Until` |
| **Paquetes** | `alsa-utils`, `ffmpeg`, `espeak-ng`, `pulseaudio`, `bluez`… uno a uno: si falta alguno, avisa y **sigue con los demás** |
| **Venv** | crea `~/tonypi-mcp/.venv` e instala `webrtcvad-wheels==2.0.14` (la única versión con wheel para Python 3.7 + ARM) |
| **`--with-service`** | instala `pontibot.service` y lo habilita al arrancar |
| **Diagnóstico** | ejecuta `audio_doctor.py` y te dice qué audio ve |

> **El SDK de MCP no se instala en el robot**: exige Python ≥ 3.10 y el robot
> tiene 3.7. No hace falta: el agente del robot habla directo con el firmware
> por JSON-RPC (backend `rpc`). El **servidor MCP va en tu PC**.

**Cuánto tarda:** 5–15 min (según la velocidad del mirror y la SD).

---

## 7 · Fase 5 — La clave del LLM

**Ya está hecha.** El `.env` con la clave real viaja dentro del zip y se copia
al robot con permisos `600`. Solo tienes que **comprobar** que llegó:

**EN EL ROBOT:**

```bash
ls -l /home/pi/tonypi-mcp/.env        # debe poner -rw------- (600)
grep LLM_API_KEY /home/pi/tonypi-mcp/.env | sed 's/=.*/= (oculta)/'
```

Si el `.env` no llegó (porque copiaste solo los `.py`), créalo a mano:

```bash
sudo tee /home/pi/tonypi-mcp/.env >/dev/null <<'EOF'
LLM_API_KEY=nvapi-pon-tu-clave-aqui
LLM_BASE_URL=https://integrate.api.nvidia.com/v1
LLM_MODEL=nvidia/nemotron-3.5-bolt-e4b
LLM_LANGUAGE=es
LLM_TEMPERATURE=0.6
ASR_BACKEND=whispercpp
TTS_BACKEND=espeak
PONTIBOT_MEMORY=~/.pontibot/memory.json
PONTIBOT_MAX_TURNS=12
EOF
sudo chmod 600 /home/pi/tonypi-mcp/.env
```

> La clave se puede cambiar en <https://build.nvidia.com/settings> o en el
> panel de secretos de Mavis (`NVIDIA_API_KEY`). Si la cambias, actualiza el
> `.env` del robot y el del zip.

---

## 8 · Fase 6 — Probar que el robot habla

**EN EL ROBOT:**

```bash
cd ~/tonypi-mcp

# 1) ¿ve el audio? (micrófono, altavoz, bluetooth)
./.venv/bin/python audio_doctor.py

# 2) ¿llega la API?
curl -s -o /dev/null -w '%{http_code}\n' https://integrate.api.nvidia.com/v1/models   # 200

# 3) el agente en vivo
set -a; source .env; set +a
./.venv/bin/python voice_agent.py
```

Qué esperar: un saludo («Soy PontiBot. Te escucho.») y que entienda lo que le
digas. Si no oye, mira el resumen del `audio_doctor`: perfil BT equivocado,
micrófono muteado o sin micrófono.

---

## 9 · Fase 7 — El MCP desde tu PC

**EN TU PC** (el robot es el servidor de herramientas; el MCP corre aquí):

```bash
cd tonypi-mcp
export TONYPI_HOST=<IP_DEL_ROBOT>

# prueba rápida del protocolo
python test_rpc.py $TONYPI_HOST
# debe imprimir: OK ping / OK vision / OK servos / OK camara

# prueba del MCP completo
cd tonypi-mcp && python e2e_mcp_test.py --real-sdk
```

**Claude Code:**

```bash
claude mcp add pontibot \
  --env TONYPI_HOST=<IP_DEL_ROBOT> \
  -- python /ruta/a/tonypi-mcp/server.py
```

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "pontibot": {
      "command": "python3",
      "args": ["/ruta/a/tonypi-mcp/server.py"],
      "env": { "TONYPI_HOST": "<IP_DEL_ROBOT>" }
    }
  }
}
```

Prueba: «Hola PontiBot, saluda y dime qué ves.»

> El `server.py` **sí** necesita el SDK de MCP → en tu PC, con Python moderno:
> `pip install mcp`.

---

## 10 · Fase 8 — Que arranque solo

**EN EL ROBOT:**

```bash
sudo systemctl enable --now pontibot
journalctl -u pontibot -f     # ver los logs en vivo
```

---

## 11 · Atajo: todo desde el PC en un comando

Si ya tienes internet en el robot, `deploy_to_robot.sh` hace las fases 3 a 6
seguidas (copia el código, escribe el `.env` con tu clave, detecta Buster y
pasa `--fix-repos` solo, instala, aplica el parche del firmware, instala el
servicio y verifica):

**EN TU PC:**

```bash
cd tonypi-mcp
export NVIDIA_API_KEY=nvapi-pon-tu-clave-aqui
./deploy_to_robot.sh --host <IP_DEL_ROBOT> --with-service --patch
```

Con `--with-piper` tienes voz TTS natural en español (descarga ~60 MB).
Con `--with-whisper` compila el ASR local (40–60 min de compilación).

---

## 12 · Las 8 órdenes, en orden (para imprimir y seguir)

| # | Dónde | Qué copiar |
|---|---|---|
| 1 | **PC** | `ssh pi@192.168.149.1` (clave `raspberry`) |
| 2 | **PC** | `bash tonypi_wifi.sh --host 192.168.149.1 probe` |
| 3 | **PC** | `bash tonypi_wifi.sh --host 192.168.149.1 sta --ssid "TU_RED"` |
| 4 | **PC** | `scp -r tonypi-mcp/* pi@<IP_NUEVA>:/home/pi/tonypi-mcp/` |
| 5 | **Robot** | `cd ~/tonypi-mcp && bash setup_pi.sh --fix-repos --with-service` |
| 6 | **Robot** | `sudo tee /home/pi/tonypi-mcp/.env` → pegar el bloque con `nvapi-…` → `sudo chmod 600 …` |
| 7 | **Robot** | `cd ~/tonypi-mcp && ./.venv/bin/python voice_agent.py` |
| 8 | **PC** | `claude mcp add pontibot --env TONYPI_HOST=<IP> -- python /ruta/server.py` |

---

## 13 · Problemas frecuentes

| Síntoma | Causa | Solución |
|---|---|---|
| `Temporary failure resolving` en apt | sin DNS | Fase 2 (internet) |
| `Unable to locate package X` | Buster archivado | `setup_pi.sh --fix-repos` |
| `E: Unable to locate package pipewire-audio-client-libraries` | ese paquete es de bullseye+ | ya arreglado: en Buster es PulseAudio |
| La sesión SSH se cae al cambiar de red | normal, el robot cambia de red | reconecta a la IP nueva |
| El robot no vuelve tras el cambio | credenciales o red incompatible | `tonypi_wifi.sh ap` o botón KEY1 |
| `pip install mcp` falla en el robot | Python 3.7 < 3.10 | normal: el MCP corre en tu PC |
| El robot habla pero no se mueve | el modelo no llamó a la herramienta | `LLM_TEMPERATURE=0.3` y `nvidia_smoke_test.py` |
| El robot se oye a sí mismo | el altavoz pilla el micro | aleja el micro o usa un headset direccional |
| El modelo responde en indonesio | el prompt no llega | `LLM_MODEL` y `LLM_LANGUAGE=es` en el `.env` |
| `audio_doctor` dice que el micro está mudo | perfil BT equivocado | `pavucontrol` → Configuration → **Headset** |
| La llamada da 429 | rate limit (~40/min) | espera un minuto; el código reintenta solo |

---

## Fuentes

- [TonyPi v1.0 · Network Configuration (Hiwonder)](https://docs.hiwonder.com/projects/TonyPi/en/latest/docs/13_network_configuration.html)
- [TonyPi Pro · Network Configuration Instruction](https://docs.hiwonder.com/projects/TonyPi_Pro/en/latest/docs/14_network_configuration.html)
- [TonyPi · Quick User Experience (modos AP y LAN)](https://docs.hiwonder.com/projects/TonyPi/en/latest/docs/2.quick_user_experience.html)
- [archive.debian.org · buster](https://archive.debian.org/debian/dists/buster/)

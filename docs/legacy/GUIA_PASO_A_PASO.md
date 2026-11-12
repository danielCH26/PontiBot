# Guía paso a paso: montar PontiBot en el TonyPi

> ⚠️ **Usa [`PASO_A_PASO.md`](PASO_A_PASO.md) en su lugar.** Esta guía es de la
> sesión anterior y asume una imagen Ubuntu; la imagen real del TonyPi v1.0 es
> **Raspbian Buster** (Python 3.7, repos archivados), y ahí algunas cosas de
> este documento ya no son ciertas. La nueva guía separa claramente qué va en
> tu PC y qué va en el robot, e incluye el arreglo de Buster.

Todo lo que necesitas para tener al robot hablando, probando y medido.
Tiempo total: ~45 min (sin compilar whisper.cpp) o ~2 h (con whisper local).

---

## Paso 0 — Qué necesitas

- El robot TonyPi, cargado y con la tarjeta SD puesta.
- **El módulo Wi-Fi USB** (y, si hace falta, un **cable Ethernet** para el paso 1.2).
- Tu PC con `ssh` (Mac/Linux Terminal, o Windows con PowerShell + OpenSSH).
- La Wi-Fi de tu casa (el robot tiene que entrar en **esa** red, no en la suya).
- Los ficheros de este proyecto en tu PC (`tonypi-mcp/`).

---

## Paso 0b — Si la red no funciona: diagnostica antes de tocar nada

Si el robot no se conecta, **no sigas probando cosas a ciegas**. Ejecuta esto
(por SSH en modo AP, o desde la consola de WinSCP):

```bash
python3 net_doctor.py
```

Te dice, en un solo comando: qué interfaces tiene, si el módulo USB aparece,
qué redes Wi-Fi ve, cómo está la configuración de Hiwonder, si el cable de red
tiene enlace, y si llega a la API de NVIDIA. Al final hay un **veredicto** con
lo que tienes que hacer.

Copia y pega la salida aquí si quieres que te la interprete.

### El atajo: con cable de red funciona todo

El TonyPi tiene **RJ45**. Si tienes un cable de red:

1. Enchúfalo del robot al router (o a un switch).
2. `ip -br addr show eth0` → la IP.
3. `ping -c 3 1.1.1.1` → si responde, ya tienes internet.

Con eso el LLM funciona, puedes desplegar todo y probar el robot. **El módulo
Wi-Fi es para la movilidad, no es un requisito** — no lo dejes bloquearte.

---

## Paso 1 — Módulo Wi-Fi + salida a internet

> **Este es el paso que más gente se salta, y es la causa número uno de que
> "el robot no habla".** El robot arranca por defecto en **modo AP**: crea su
> propio hotspot (`HW...`, contraseña `hiwonder`) y en ese modo **no tiene
> acceso a internet**. Sin internet no hay llamada a la API de NVIDIA.

### La idea

Con el **módulo Wi-Fi USB** conectado, queremos que el robot:

1. Use el módulo USB **en vez del** Wi-Fi integrado de la Pi.
2. Entre en **tu red de casa** (modo LAN/STA) → así tiene internet **y** tu PC
   puede hablar con él por la red local.

El truco para el punto 1: si hay dos antenas Wi-Fi, el script de Hiwonder puede
seguir manejando la de la Pi. Desactivando el integrado a nivel de hardware
(`dtoverlay=disable-wifi`), **el módulo USB se queda con el nombre `wlan0`** y
todo el stack de Hiwonder (hotspot, modo STA) pasa a moverse sobre él.

### 1.1 — ¿El kernel reconoce el módulo?

Conecta el módulo USB al robot y, desde el PC, entra por SSH al hotspot:

```bash
# conéctate al hotspot HW... del robot primero
ssh pi@192.168.149.1
```

Y ejecuta el diagnóstico (el script está en el proyecto; si aún no lo has
copiado, cópialo):

```bash
./wifi_dongle_setup.sh diagnose
```

Mira dos cosas:

| Lo que ves | Qué significa | Qué hacer |
|---|---|---|
| `iw dev` lista una interfaz (`wlan1` o `wlx...`) | **El driver ya está en el kernel** | Saltas al 1.3, no hace falta instalar nada |
| `iw dev` no lista nada | **Falta el driver** | Pasa al 1.2 |

> Esto no es un problema: la Pi se llama «TonyPi», el módulo se enchufa en un
> puerto USB y el kernel es Linux. Si el módulo es un Realtek (RTL8812AU,
> RTL8822BU, RTL8821AU...) es normal que haga falta compilarlo, porque el
> kernel de la Pi no los trae de fábrica en aarch64.

### 1.2 — Si falta el driver (necesita internet)

Para instalar el driver el robot **necesita internet**, y en modo AP no lo tiene.
Salida: **cable Ethernet**. El TonyPi tiene RJ45.

```bash
# en el robot, con el cable de red conectado al router
sudo apt update
sudo apt install -y raspberrypi-kernel-headers build-essential bc git dkms
./wifi_dongle_setup.sh install-driver    # compila el driver rtw88 (tarda unos minutos)
sudo reboot
```

Alternativa si no puedes cablear: usa el **Wi-Fi integrado** para el internet
mientras instalas (el integrado sí entra en tu red si es 2.4 GHz), y luego
sustituyes por el módulo.

`install-driver` cubre los Realtek más habituales: RTL8811AU, RTL8812AU,
RTL8814AU, RTL8821AU, RTL8812BU, RTL8822BU, RTL8723DU.

### 1.3 — Que el módulo USB tome el control (`wlan0`)

```bash
./wifi_dongle_setup.sh disable-onboard
sudo reboot
```

Esto añade `dtoverlay=disable-wifi` al `config.txt` y pone `brcmfmac` en
blacklist. **No toca el Bluetooth** (el audio del robot lo necesita).

Comprueba:

```bash
iw dev
# debe mostrar una sola interfaz wireless llamada wlan0 = tu módulo USB
```

Si no aparece nada → el driver no está instalado → vuelve al 1.2.

### 1.4 — Meter el robot en tu red

```bash
# desde el PC, por SSH (al hotspot todavía: 192.168.149.1)
./wifi_dongle_setup.sh --host 192.168.149.1 sta --ssid "TU_WIFI" --pass "TU_PASSWORD"
```

Esto escribe `~/hiwonder-toolbox/wifi_conf.py`:

```python
HW_WIFI_MODE = 2                 # 2 = LAN/STA
HW_WIFI_STA_SSID = "TU_WIFI"
HW_WIFI_STA_PASSWORD = "TU_PASSWORD"
```

y reinicia el servicio de Wi-Fi. **Tu sesión SSH se caerá** en ese momento:
eso es normal, el robot ya ha cambiado de red.

### 1.5 — Verificar

```bash
ssh pi@<IP_NUEVA_DEL_ROBOT> 'curl -s -o /dev/null -w "%{http_code}\n" https://integrate.api.nvidia.com/v1/models'
```

Debe devolver `200`. La IP nueva la ves en el router, con `hostname -I` en el
robot, o manteniendo pulsado el icono del robot en la app WonderPi.

### Resumen visual del flujo

```
Robot apagado ──► enciende ──► modo AP (HW..., sin internet)
                                    │
                     PC se une al hotspot, SSH 192.168.149.1
                                    │
                          diagnose ──┤──► falta driver? ──► (Ethernet) ──► install-driver
                                    │                                      │
                                    │◄───── reboot + disable-onboard ◄────┘
                                    │
                          wlan0 = módulo USB
                                    │
                    sta --ssid ... ──┴──► modo LAN, IP en tu red, CON INTERNET
                                    │
                    ahora sí: deploy_to_robot.sh y a hablar
```

### Si algo va mal: vuelve a modo AP

El módulo también puede crear el hotspot (si su driver soporta modo AP):

```bash
./wifi_dongle_setup.sh --host <IP_ACTUAL> ap
```

El robot vuelve a `HW...` / `hiwonder` / `192.168.149.1` (sin internet) y
puedes recuperarlo. Desde el PC, para llegar a él tendrás que unirte al
hotspot.

---

## Paso 2 — Conectar por SSH

```bash
ssh pi@192.168.149.1     # en modo AP
ssh pi@<IP_DEL_ROBOT>    # en modo LAN
```

**Credenciales por defecto** (según la doc de Hiwonder):

| Raspberry Pi | Usuario | Contraseña |
|---|---|---|
| Pi 4B | `pi` | `raspberry` |
| Pi 5 | `pi` | `raspberrypi` |

Si no te acepta la contraseña, prueba la otra. Y cámbiala ya:

```bash
passwd
```

---

## Paso 3 — Dejar tu acceso sin contraseña (opcional pero recomendado)

El script de despliegue hace 8 conexiones SSH. Con clave pública solo tecleas
la contraseña una vez:

```bash
ssh-copy-id pi@<IP_DEL_ROBOT>
```

> En Windows sin `ssh-copy-id`: `type $env:USERPROFILE\.ssh\id_rsa.pub | ssh pi@<IP> "cat >> ~/.ssh/authorized_keys"`.

---

## Paso 4 — Despliegue con un comando

Desde tu PC, en la carpeta del proyecto:

```bash
cd tonypi-mcp
./deploy_to_robot.sh --host <IP_DEL_ROBOT> --with-service --patch
```

Qué hace, en orden:

| # | Paso | Qué hace |
|---|---|---|
| 1 | Conectividad SSH | Comprueba que responde |
| 2 | **Internet** | Verifica que el robot llega a NVIDIA (y avisa si no) |
| 3 | Copia | Manda el código a `/home/pi/tonypi-mcp` |
| 4 | `.env` | Escribe la clave de NVIDIA (permisos `600`) |
| 5 | Dependencias | `apt`, venv, piper (y whisper si lo pides) |
| 6 | Parche | Expone buzzer y audio por RPC (`--patch`) |
| 7 | Servicio | Instala `pontibot.service` (`--with-service`) |
| 8 | Verificación | `test_rpc.py` + `audio_doctor.py` + llamada real al LLM |

Banderas útiles:

```bash
--with-piper      # TTS natural local (mejor que espeak)
--with-whisper    # compila whisper.cpp para ASR local (tarda ~40 min)
--with-service    # arranca solo al encender el robot
--patch           # parche del firmware
--dry-run         # solo comprueba el SSH
```

**La clave**: el script la toma de `$NVIDIA_API_KEY` (o de `$LLM_API_KEY`, que es
la misma). Si no la tienes en la variable, pásala con `--key nvapi-...`.

El `.env` que queda en el robot queda así (permisos `600`):

```
LLM_API_KEY=nvapi-...                          <- la unica clave que hace falta
LLM_BASE_URL=https://integrate.api.nvidia.com/v1
LLM_MODEL=nvidia/nemotron-3.5-bolt-e4b
LLM_LANGUAGE=es
LLM_TEMPERATURE=0.6                           <- 0 = predecible, 1 = creativo
ASR_BACKEND=whispercpp                         <- oidos locales y gratis
TTS_BACKEND=espeak                            <- o piper si lo pides con --with-piper
PONTIBOT_MEMORY=/home/pi/tonypi-mcp/memory.json
PONTIBOT_MAX_TURNS=12
```

No hace falta `NVIDIA_API_KEY` (es la misma clave) ni `OPENAI_API_KEY` (solo si
contratas ASR/TTS de OpenAI).

---

## Paso 4b — Copiar los archivos a mano (sin el script)

Si prefieres pasar tú los ficheros en vez de usar `deploy_to_robot.sh`, o si
el robot todavía no tiene el script, esto es todo:

### Qué copiar

| Fichero | Dónde va en el robot | Para qué |
|---|---|---|
| `tonypi-mcp.zip` | `~/` | El proyecto entero (33+ ficheros) |
| `.env` | `~/tonypi-mcp/.env` | La clave de NVIDIA y la configuración |
| `GUIA_PASO_A_PASO.md` | `~/` | Esta guía, para tenerla a mano |

> El `.env` **no** va dentro del zip (va excluido a propósito, para que la
> clave no se pase a nadie sin querer). Por eso lo copias aparte.

### Los comandos

**Desde tu PC:**

```bash
scp tonypi-mcp.zip .env GUIA_PASO_A_PASO.md pi@<IP_DEL_ROBOT>:~/
```

**Y en el robot:**

```bash
ssh pi@<IP_DEL_ROBOT>

cd ~
python3 -m zipfile -e tonypi-mcp.zip .    # crea ~/tonypi-mcp/
cp .env ~/tonypi-mcp/.env
chmod 600 ~/tonypi-mcp/.env                # la clave solo la lee el usuario pi

cd ~/tonypi-mcp
bash setup_pi.sh --with-service --with-piper
```

Dos detalles:

- **`python3 -m zipfile -e`** en vez de `unzip`: la Pi no siempre trae `unzip`
  instalado, y Python siempre está.
- **El `.env` del robot lleva `TONYPI_HOST=127.0.0.1`**, porque el agente
  corre dentro del robot y se habla a sí mismo por el loopback. Si lo ejecutas
  desde tu PC, pásale `--host <IP_DEL_ROBOT>`.

### Si ya habías desplegado antes

`python3 -m zipfile -e` **sobrescribe** el código pero **no borra** lo que ya
estuviera en la carpeta. Tu `memory.json` (la memoria de PontiBot) se queda
intacto ✓.

### Comprobar que ha ido bien

```bash
cd ~/tonypi-mcp
./.venv/bin/python test_rpc.py 127.0.0.1     # el robot responde
./.venv/bin/python selftest.py              # 28/28
./.venv/bin/python test_memory.py           # 32/32
./.venv/bin/python storage_doctor.py       # estado de los discos
```

### El atajo: el script también sirve

Si prefieres que el script haga todo (copiar, escribir la clave con permisos,
instalar dependencias y verificar), es el Paso 4 y no necesitas nada de esto.

---

## Paso 5 — Verificar que todo está bien

Desde tu PC:

```bash
export TONYPI_HOST=<IP_DEL_ROBOT>

# 1) el robot responde por JSON-RPC
python tonypi-mcp/test_rpc.py $TONYPI_HOST

# 2) el MCP de extremo a extremo (arranca server.py real y lo llama)
cd tonypi-mcp && python e2e_mcp_test.py --real-sdk
```

Lo que deberías ver:

```
OK  ping
OK  vision cargada: 0
OK  servos: [250, 250, ...]
OK  camara: 1834 bytes JPEG
```

Y en la E2E: `OK: 28   FALLOS: 0`.

Si `e2e_mcp_test.py` dice *"Necesitas el SDK oficial"*, instálalo:

```bash
pip install mcp
```

---

## Paso 6 — Probar el MCP desde tu cliente

**Claude Desktop** — edita `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "pontibot": {
      "command": "python3",
      "args": ["/ruta/absoluta/a/tonypi-mcp/server.py"],
      "env": {
        "TONYPI_HOST": "192.168.1.50",
        "PYTHONPATH": "/ruta/absoluta/a/tonypi-mcp"
      }
    }
  }
}
```

**Claude Code**:

```bash
claude mcp add pontibot \
  --env TONYPI_HOST=<IP_DEL_ROBOT> \
  -- python /ruta/absoluta/a/tonypi-mcp/server.py
```

Reinicia el cliente y prueba:

> «Hola PontiBot, saluda y dime qué ves.»

Deberías ver al robot moverse y la respuesta de `robot_camera_snapshot`.

---

## Paso 7 — Probar la voz

Desde tu PC (el robot hace de cerebro; tú pones el micro y el altavoz):

```bash
cd tonypi-mcp
export TONYPI_HOST=<IP_DEL_ROBOT>
python voice_agent.py
```

Habla al micrófono. El ciclo es: **VAD → ASR → LLM → herramientas → TTS**.

Al arrancar te saluda: «Soy PontiBot. Te escucho.» (o «Hola Ana, ya te
conozco.» si ya sabe tu nombre).

Para probarlo **dentro** del robot (micrófono y altavoz del propio robot):

```bash
ssh pi@<IP_DEL_ROBOT>
cd ~/tonypi-mcp
export NVIDIA_API_KEY=...       # o carga el .env: set -a; source .env; set +a
./.venv/bin/python voice_agent.py
```

> **Primero mira qué audio hay.** Antes de nada:
> ```bash
> ssh pi@<IP_DEL_ROBOT> 'cd ~/tonypi-mcp && ./.venv/bin/python audio_doctor.py'
> ```
> Te dice qué micrófono y qué altavoz ve el sistema, si el Bluetooth está en
> perfil HFP y si el micro capta señal de verdad.

### Probar la memoria

```bash
# en el robot, con el agente parado
./.venv/bin/python memory.py                    # qué sabe de ti
cat ~/tonypi-mcp/memory.json                    # el fichero entero

./.venv/bin/python voice_agent.py --reset-memory # olvidar todo y salir
```

Para probarlo **sin robot**, contra el LLM real:

```bash
export LLM_API_KEY=$NVIDIA_API_KEY
python test_live_memory.py     # 7 comprobaciones: ¿recuerda tu nombre?
```

### Cambiar la personalidad

Todo el carácter está en **`prompts.py`**, en el bloque `PERSONALITY`. Cámbialo,
sube el fichero y reinicia el servicio. Y como el smoke test usa el mismo
prompt que el robot, lo compruebas:

```bash
python nvidia_smoke_test.py    # 6/6 = la personalidad no ha roto las herramientas
```

---

## Paso 8 — Dejarlo funcionando solo

```bash
ssh pi@<IP_DEL_ROBOT>
sudo systemctl enable --now pontibot
journalctl -u pontibot -f
```

Con `--with-service` en el paso 4 esto ya quedó hecho.

Para que arranque con el robot: ya se hace (`WantedBy=multi-user.target`).

La memoria se guarda en `~/tonypi-mcp/memory.json` (permisos `600`), así que
**PontiBot recuerda la conversación aunque reinicies el robot**.

---

## Problemas frecuentes

| Síntoma | Causa | Solución |
|---|---|---|
| El robot no habla | Está en modo AP (sin internet) | Paso 1 → modo LAN |
| `iw dev` no muestra nada | El módulo USB no tiene driver | Paso 1.2 (Ethernet + `install-driver`) |
| `iw dev` muestra `wlan1` y `wlan0` | El integrado sigue activo | `disable-onboard` + reboot → el USB queda como `wlan0` |
| `iw dev` muestra `wlan0` pero es el integrado | El blacklist no aplicó | Comprueba `/boot/firmware/config.txt` y `lsmod \| grep brcmfmac` |
| El driver compila pero no aparece la interfaz | Falta el firmware | `cd /tmp/rtw88 && sudo make install_fw` y reinicia |
| `install-driver` dice "no tiene internet" | Estás en modo AP | Conecta el cable Ethernet (RJ45) |
| La sesión SSH se cae al pasar a STA | **Es normal**, el robot cambió de red | Conéctate a la IP nueva |
| `ssh` pide usuario/contraseña | No sabes cuál | `pi` + `raspberry` (4B) o `raspberrypi` (5) |
| `ssh` no conecta | IP equivocada | App WonderPi → mantener pulsado el icono |
| El deployment falla en el paso 2 | El robot no tiene internet | Vuelve al paso 1, modo LAN |
| `test_rpc.py` falla | El servicio del robot no está activo | `sudo systemctl restart tonypi.service` |
| `e2e_mcp_test.py` pide el SDK | Falta el paquete | `pip install mcp` |
| El robot se oye a sí mismo | El altavoz pilla el micro | Half-duplex ya está; aleja el micro o usa un headset direccional |
| El robot habla pero no se mueve | El modelo respondió sin llamar a la herramienta | Bájale la temperatura (`LLM_TEMPERATURE=0.3`) y comprueba `python test_live_memory.py` |
| El robot no recuerda nada | La memoria está desactivada o en otra ruta | `python memory.py`; mira `PONTIBOT_MEMORY` |
| El modelo responde en indonesio | El prompt no está llegando | Comprueba `LLM_MODEL` y `LLM_LANGUAGE=es`; el prompt fuerza el español |
| La llamada a NVIDIA da 429 | Rate limit (~40/min) | Espera un minuto; el código ya reintenta solo |
| `audio_doctor` dice que el micro está mudo | Perfil BT equivocado | `pavucontrol` → Configuration → perfil *Headset*, no *High Fidelity* |
| El TTS suena a robot | `espeak` | Cambia a `TTS_BACKEND=piper` |

---

## Orden de las pruebas (de menos a más)

1. `test_rpc.py` → el robot responde.
2. `e2e_mcp_test.py --real-sdk` → el MCP funciona entero.
3. Cliente MCP → «saluda» → el robot se mueve.
4. `audio_doctor.py` → hay audio.
5. `voice_agent.py` → habla.
6. `systemctl` → habla solo al encender.

Si algo falla, para en el paso en el que falle: cada uno es independiente de los
siguientes y te dice exactamente dónde está el problema.

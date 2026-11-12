# TonyPi · Guía de red: habilitar WiFi y salida a internet

> Documento de referencia para el punto que más atasca el proyecto PontiBot:
> **el robot arranca en modo AP y sin internet, y el LLM no funciona.**
>
> ⚠️ La imagen del TonyPi v1.0 es **Raspbian Buster** (no Ubuntu). Buster está
> archivado: eso tiene consecuencias para `apt` (ver sección 8).

---

## 1. El problema en una frase

El TonyPi arranca en **modo AP (punto de acceso)**: enciende su propio hotspot
(`HW...`, contraseña `hiwonder`, IP `192.168.149.1`) para que te conectes desde el
móvil o el PC. En ese modo **el robot no tiene salida a internet**, por diseño.

Y hay un segundo detalle que hace perder horas: **la configuración de red del
escritorio no sirve**. Los ajustes WiFi de GNOME, `nmcli`, los ajustes del panel
de Ubuntu… todo es ignorado, porque la imagen de Hiwonder gestiona el radio con
scripts propios. La propia documentación lo dice:

> *"Switching to LAN mode cannot be done directly through the system's network
> settings, as the Wi-Fi has custom configurations."*
> — [docs.hiwonder.com · TonyPi](https://docs.hiwonder.com/projects/TonyPi/en/latest/docs/13_network_configuration.html)

La única vía soportada es **editar `~/hiwonder-toolbox/wifi_conf.py`** y
reiniciar el servicio de WiFi.

---

## 2. Diagnóstico: siempre el primero

No toques nada hasta saber en qué situación estás. El script de este repo te da
el estado completo y un veredicto:

```bash
bash tonypi_wifi.sh probe
```

(Es **solo lectura**: no cambia ninguna configuración. Cópialo al robot con
`scp` o pégalo en la terminal VNC.)

Qué te dice, en 10 secciones: modelo de Pi, interfaces y rutas, si estás en el
rango del hotspot (192.168.149.x), si el WiFi integrado está cargado
(`brcmfmac`), si hay `dtoverlay=disable-wifi` en el `config.txt`, si hay un
dongle USB y qué chip es, qué servicios de Hiwonder existen, el valor real de
`HW_WIFI_MODE`, si el cable de red tiene enlace, y si la API de NVIDIA
responde.

### 2.1 · Desde tu PC, sin copiar nada al robot

El script tiene modo remoto: se copia solo al robot y se ejecuta por SSH.
**Funciona aunque el robot no tenga internet**, porque el hotspot AP sí da
SSH. Útil precisamente para el caso "no tengo internet todavía":

```bash
# diagnóstico remoto
bash tonypi_wifi.sh --host 192.168.149.1 probe

# pasar el robot a tu router (desde el PC)
bash tonypi_wifi.sh --host 192.168.149.1 sta --ssid "TU_RED" --pass "TU_CLAVE"

# volver al hotspot
bash tonypi_wifi.sh --host 192.168.149.1 ap
```

El usuario por defecto es `pi` (`--user` para cambiarlo). La contraseña se
transporta correctamente aunque tenga espacios, comillas o símbolos.

> Si tu VNC entra por el hotspot, la IP del robot es `192.168.149.1`. Si entra
> por Ethernet o por tu red, usa la IP que te dé el `probe`.

---

## 3. Las vías, ordenadas de menos a más trabajo

### Vía 1 · Modo LAN/STA nativo ⭐ (la buena)

El robot entra en **tu router** como un cliente normal: recibe IP por DHCP, tiene
internet y tu PC puede hablar con él por la red local.

```bash
bash tonypi_wifi.sh sta --ssid "TU_RED" --pass "TU_CLAVE"
```

O a mano (lo que hace el script por ti):

```bash
cd ~/hiwonder-toolbox
vim wifi_conf.py
#   HW_WIFI_MODE = 2                  # 1 = AP (hotspot), 2 = LAN/STA
#   HW_WIFI_STA_SSID = "TU_RED"
#   HW_WIFI_STA_PASSWORD = "TU_CLAVE"
sudo systemctl restart wifi.service
```

**Requisitos del router** (esto es lo que más falla):

| Tipo de red | ¿Sirve en el TonyPi (Pi 4B)? |
|---|---|
| WPA2-Personal **2.4 GHz** | ✅ ideal |
| WPA2-Personal con SSID único 2.4+5 | ✅ el Pi 4B solo entra por 2.4 GHz |
| 5 GHz únicamente | ❌ el Pi 4B no tiene radio de 5 GHz |
| WPA3-only (sin WPA2) | ❌ brcmfmac no lo negocia → usa un hotspot 2.4 GHz en WPA2 |
| WPA2-Enterprise (802.1X, certificate) | ❌ |
| Portal cautivo (hotel, airports, universidad) | ❌ requiere login web |
| Canal 12/13 | ⚠️ si falla: `sudo iw reg set ES` y `sudo raspi-config nonint do_wifi_country ES` |

**El aviso importante:** al pasar a LAN, **tu sesión de VNC/SSH se cae**, porque
el robot cambia de red. Vuelve a conectarte a la **IP nueva** (ver sección 5).

---

### Vía 2 · Cable Ethernet (RJ45) ⭐⭐ (la más rápida)

El TonyPi **tiene RJ45**. Con un cable al router:

```bash
ip -br addr show eth0     # la IP que te da el router
ping -c 3 1.1.1.1         # si responde, ya tienes internet
```

Cero configuración, funciona con WPA3, 5 GHz, redes de empresa… **y sirve
además para instalar drivers** si más adelante los necesitas.

El único inconveniente: el robot queda atado al cable. Si la movilidad importa,
esta vía es la fase 1 y luego se pasa a la Vía 1.

#### Modo 3 · AP + internet por cable (el mejor de los dos mundos)

El firmware de Hiwonder tiene un tercer modo que no sale en la documentación
habitual, pero está en el propio código (`hw_remote.py`):

```python
HW_WIFI_MODE = 1  # 1 = AP, 2 = cliente, 3 = AP + comparte internet por eth0
```

En **modo 3** el robot **mantiene su hotspot** (VNC/SSH no se caen nunca) y a la
vez **tiene internet por el cable**:

```bash
# enchufa el RJ45 del robot al router y:
bash tonypi_wifi.sh sta --mode 3 --ssid "TU_RED" --pass "TU_CLAVE"
```

Ventajas frente al modo 2:
- **No pierdes el acceso**: el hotspot sigue siendo `HW-…` en `192.168.149.1`.
- El robot tiene internet y además **repartelo** a los que estén en su hotspot.
- Si algo falla, el cable es el único requisito (el WiFi da igual).

Es la opción recomendada si te importa no perder la sesión de VNC mientras
configuras el resto del proyecto.

---

### Vía 3 · Hotspot del móvil (2.4 GHz)

Si tu router no cumple los requisitos de la Vía 1 (5 GHz, WPA3, empresa) o si
quieres aislar el robot en su propia red:

1. Activa **punto de acceso WiFi** en el móvil (2.4 GHz, WPA2).
2. `bash tonypi_wifi.sh sta --ssid "NombreDelHotspot" --pass "Clave"`
3. Listo: el robot entra al hotspot y sale a internet por los datos del móvil.

Es la vía más universal: funciona con **cualquier** red, incluso una red WPA3
de empresa, porque el hotspot es WPA2.

Variante avanzada: el **PC como hotspot** (Windows: *Configuración → Red →
Móvil y puntos de acceso*; Linux/macOS: "Crear punto de acceso"), con el PC
compartiendo su conexión.

---

### Vía 4 · `nmcli` / ajustes del escritorio (apaño, no recomendado)

```bash
sudo nmcli dev wifi list
sudo nmcli dev wifi connect "TU_RED" password "TU_CLAVE"
```

Funciona en algunos robots, pero:
- el servicio de Hiwonder puede **volver a imponer el modo AP** al reiniciar;
- no es el flujo soportado por el fabricante;
- no sobrevive a un ciclo de apagado/encendido de forma fiable.

Úsalo solo si `wifi.service` **no existe** en tu imagen (lo sabrás con el
`probe`).

---

### Vía 5 · Módulo WiFi USB (solo si el integrado está muerto)

Solo si el `probe` dice que `brcmfmac` **no** está cargado o que el
`config.txt` tiene `dtoverlay=disable-wifi`.

El repo ya trae el módulo completo:

```bash
./wifi_dongle_setup.sh diagnose        # ¿lo reconoce el kernel?
./wifi_dongle_setup.sh disable-onboard  # el USB toma el nombre wlan0
./wifi_dongle_setup.sh install-driver   # compila rtw88 (necesita internet → usa la Vía 2)
./wifi_dongle_setup.sh sta --ssid "TU_RED" --pass "TU_CLAVE"
```

Los chips Realtek **RTL88xx** (8812AU, 8821AU, 8822BU…) no vienen en el kernel
aarch64: hay que compilarlos, y para eso **necesitas internet antes** → cable
Ethernet primero.

> Ojo: `disable-onboard` apaga el WiFi integrado de la Pi **a propósito**. Si
> luego resultas que el integrado funcionaba, quita `dtoverlay=disable-wifi` de
> `/boot/firmware/config.txt` y el `blacklist brcmfmac`, y reinicia.

---

### Vía 6 · Internet desde tu PC (compartir conexión)

El PC hace de router para el robot, por Ethernet:

```bash
# en el PC (Linux)
nmcli con mod "Wired connection 1" ipv4.method shared
# en el robot: cable al PC, DHCP normal
```

En Windows: *Configuración de red → Compartir conexión* →Ethernet → Ethernet.
El robot recibirá una IP tipo `192.168.137.x`.

Útil cuando el robot está lejos del router pero cerca del PC.

---

## 4. Árbol de decisión

```
¿El robot tiene internet ya?
├─ SÍ  → nada que hacer. Sigue con el despliegue (sección 6).
└─ NO
   │
   ├─ ¿Hay un cable de red a mano?
   │   └─ SÍ → Vía 2 (Ethernet). 2 minutos. IMPRESCINDIBLE si luego
   │            hace falta compilar drivers.
   │
   ├─ ¿El integrado funciona? (probe: brcmfmac cargado, sin disable-wifi)
   │   ├─ SÍ → Vía 1 (STA). 2 minutos.
   │   └─ NO → ¿El USB está enchufado?
   │            ├─ SÍ → Vía 5 (driver; usa Vía 2 mientras tanto)
   │            └─ NO → quita disable-wifi / blacklist y reinicia → Vía 1
   │
   └─ ¿Tu router es 5 GHz / WPA3 / empresa?
       └─ SÍ → Vía 3 (hotspot del móvil en 2.4 GHz WPA2)
```

---

## 5. La transición sin perder el robot

Al pasar de AP a LAN, el robot se va de la red y **tu VNC se cae**. Esto es
normal, pero conviene estar preparado. `tonypi_wifi.sh sta` deja tres redes de
seguridad:

1. **Vigilante automático (3 min).** Si el robot no consigue IP de LAN,
   restaura la configuración anterior y vuelve al modo AP por su cuenta.
   Log: `~/tonypi_wifi_watchdog.log`.
   Si ves que todo fue bien, cancela el vigilante:
   ```bash
   bash tonypi_wifi.sh cancel-watchdog
   ```

2. **Copia de seguridad.** Todo lo tocado queda en `~/tonypi_wifi_backup/`.
   Para volver atrás a mano:
   ```bash
   bash tonypi_wifi.sh ap
   ```

3. **Escape físico (inmediato).** Mantén pulsado el **botón KEY1** de la placa
   de expansión hasta que parpadee el LED azul → el robot vuelve al modo AP y
   su hotspot reaparece. Es el método oficial de Hiwonder.

**Dónde mirar la IP nueva** cuando el robot ya está en tu red:

- en la salida del propio script (`ip : ...`);
- en la tabla de DHCP de tu router (192.168.1.1 → *DHCP clients*);
- con `hostname -I` en el robot;
- en la app WonderPi: mantener pulsado el icono del robot.

> Si tu VNC entra **por el hotspot del robot** (192.168.149.x), al pasar a LAN
> tendrás que reconectar a la IP de tu red. Si tu VNC entra **por Ethernet**, la
> sesión sobrevive porque el cable no se mueve.

---

## 6. Después de tener internet

```bash
# 1) verificar que la API responde
curl -s -o /dev/null -w '%{http_code}\n' https://integrate.api.nvidia.com/v1/models   # 200

# 2) desplegar PontiBot (desde tu PC)
export TONYPI_HOST=<IP_NUEVA_DEL_ROBOT>
cd tonypi-mcp
./deploy_to_robot.sh --host $TONYPI_HOST --with-service --patch
```

El resto del proyecto está en `GUIA_PASO_A_PASO.md` (pasos 4 a 8).

---

## 7. FAQ rápido

| Síntoma | Causa probable | Solución |
|---|---|---|
| VNC se cae al cambiar a LAN | Normal: el robot cambia de red | Reconecta a la IP nueva (§5) |
| `iw dev` no muestra nada | Radio apagado o dongle sin driver | `probe` → sección 4 y 5 |
| El robot entra al router pero no hay internet | DNS del router o WPA3 | `nmcli dev show wlan0 \| grep DNS` → `sudo nmcli con mod "<red>" ipv4.dns "1.1.1.1 8.8.8.8"` |
| `wifi.service: Unit not found` | Tu imagen usa solo `hw_wifi.service` | `sudo systemctl restart hw_wifi.service` (la Vía 4 con nmcli también sirve) |
| No encuentra `wifi_conf.py` | Otro usuario/path | `find / -name 'wifi_conf.py' 2>/dev/null` |
| El robot entra pero la IP es 192.168.149.x | Sigue en modo AP | `probe` → mira `HW_WIFI_MODE` |
| La contraseña WPA del router es especial (`#`, `@`, `€`) | Shell | Usa comillas: `--pass 'clave#con€'` |

---

## 8. Bonus: `apt` falla en el TonyPi (buster archivado)

Si al instalar paquetes ves esto:

```
Err:1 http://mirrors.ustc.edu.cn/... buster InRelease
  Temporary failure resolving 'mirrors.ustc.edu.cn'
E: Unable to locate package bluez-tools
```

eso son **dos problemas distintos**, y el segundo solo aparece si arreglas el primero:

### 8.1 · El DNS (bloqueante)

`Temporary failure resolving` significa que **no resuelve nombres**. Sin DNS no
hay `apt`, ni `pip`, ni llamada a la API. Es un problema de red (secciones 3 y
4), no de repositorios.

```bash
ip -br addr; ip route; cat /etc/resolv.conf
ping -c2 1.1.1.1          # ¿hay salida?
getent hosts deb.debian.org   # ¿resuelve DNS?
```

| Síntoma | Diagnóstico | Solución |
|---|---|---|
| `ip route` sin `default` | sin red | Vía 1/2/3 de esta guía |
| ping OK pero `getent` falla | solo DNS | `sudo nmcli con mod "TU_RED" ipv4.dns "1.1.1.1 8.8.8.8"` |
| `ip -br addr` con 192.168.149.x | estás en el hotspot del robot | Vía 1 |

### 8.2 · Los repos de buster están archivados (secundario)

`raspbian.raspberrypi.org` **ya no sirve** (su `dists/buster` está vacío) y los
`Release` archivados están caducados, así que `apt` se queja aunque el DNS
funcione. El instalador lo arregla solo:

```bash
cd ~/tonypi-mcp
bash setup_pi.sh --fix-repos
```

Lo que hace: comenta las líneas muertas, añade los espejos del archivo
(`legacy.raspbian.org`, `archive.raspberrypi.org`, `archive.debian.org`) y
desactiva `Check-Valid-Until`.

### 8.3 · `pipewire-audio-client-libraries` no existe en buster

En buster el stack de audio es **PulseAudio** (`pulseaudio`,
`pulseaudio-module-bluetooth`) y PipeWire va aparte en la versión 0.2.5, sin
el paquete `pipewire-audio-client-libraries` (ese nombre es de bullseye+).

Esto importaba porque un `apt install` con un paquete inexistente **aborta la
instalación entera**: no se instalaba ni `alsa-utils`, ni `ffmpeg`, ni nada
más. Por eso `setup_pi.sh` ahora instala **por grupos y con reintento paquete a
paquete**: si falta uno, se avisa y se sigue.

## 8. Aviso para el TonyPi v1.0: es un Raspbian Buster

La imagen del TonyPi v1.0 **no es Ubuntu 20.04, es Raspbian Buster** (Debian
10). Tres consecuencias que te van a morder si no las sabes:

**a) Buster está archivado (fin de soporte: junio de 2024).** Los repos que
trae la imagen ya no existen, así que `apt update` falla aunque tengas
internet. La solución es apuntar al archivo:

```bash
cd ~/tonypi-mcp
bash setup_pi.sh --fix-repos
```

Eso añade `legacy.raspbian.org`, `archive.debian.org` y
`archive.raspberrypi.org`, comenta la línea muerta de
`raspbian.raspberrypi.org` y desactiva el `Check-Valid-Until` (obligatorio en
repos archivados). **Verificado en 2026-11: los tres mirrors responden 200.**

**b) `pipewire-audio-client-libraries` no existe en Buster.** Es un paquete de
bullseye+. En Buster el stack de audio es **PulseAudio**, y `pipewire` está en
la versión 0.2.5. El instalador ya lo distingue solo según el *codename*.

**c) Python 3.7 → el SDK de MCP no cabe.** El paquete `mcp` oficial exige
**Python ≥ 3.10**, así que en el robot no se puede instalar. No es un problema:
el agente de voz del robot funciona con el **backend `rpc`** (habla
directamente con el JSON-RPC del firmware, sin SDK). El **servidor MCP se
ejecuta en tu PC**, que sí tiene Python moderno, y le habla al robot por el
puerto 9030.

Único ajuste: `webrtcvad-wheels` se fija a `2.0.14`, que sí trae wheel para
cp37 + aarch64 (la última, 2.0.14.post1, ya exige Python 3.10). Está en
`requirements-pi.txt`, que el instalador usa solo cuando detecta Python < 3.10.

> Errores típicos de `apt` en un Buster sin internet:
> `Temporary failure resolving 'mirrors.ustc.edu.cn'` → **es DNS, no son los
> mirrors**. Con internet pero sin `--fix-repos` → los repos están muertos, y
> entonces sí es el mirror.

---

## Fuentes

- [TonyPi v1.0 · Raspberry Pi Series Robot Network Configuration](https://docs.hiwonder.com/projects/TonyPi/en/latest/docs/13_network_configuration.html)
- [TonyPi Pro · Network Configuration Instruction](https://docs.hiwonder.com/projects/TonyPi_Pro/en/latest/docs/14_network_configuration.html)
- [TonyPi · Quick User Experience (modos AP y LAN)](https://docs.hiwonder.com/projects/TonyPi/en/latest/docs/2.quick_user_experience.html)

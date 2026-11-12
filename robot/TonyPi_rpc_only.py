#!/usr/bin/python3
# coding=utf8
"""
TonyPi_rpc_only.py — servicio "solo RPC" para el TonyPi v1.0 (Raspbian Buster).

=============================================================================
POR QUÉ EXISTE ESTE FICHERO
=============================================================================
El servicio de fábrica `tonypi.service` arranca `/home/pi/TonyPi/TonyPi.py`, que:

  1. al importar `RPCServer.py` ejecuta, en este orden:
       - `ctl.set_buzzer(1900, 0.1, 0.9, 1)`   → un pitido
       - `ColorTrack.initMove()`
       - `AGC.runActionGroup('stand_slow')`    → el robot se pone de pie
  2. levanta el servidor JSON-RPC en el puerto 9030 y el de vídeo MJPG en el 8080;
  3. y ADEMÁS ejecuta el "programa de juego" (Functions/Running.py) cuando
     `RunningFunc` está entre 1 y 12 (control remoto,踢球, gestos, seguimiento de
     línea, tracking de color, cara, AprilTag, transporte, ajuste LAB, hurdles,
     escaleras, clasificación de color).

El punto 3 es el "modo de prueba". Y es peligroso para nosotros porque las
llamadas RPC NO se ejecutan en el hilo del servidor: se encolan en una Queue y
las consume el HILO PRINCIPAL del robot (`runbymainth` -> `QUEUE.put(...)`,
con un tope de 200 x 0,01 s = 2 s). Si hay una función de juego cargada, el hilo
principal está ocupado y todas nuestras órdenes expiran con:

    E04 - Operation timeout!

Este script = `TonyPi.py` SIN el bucle de juego. Conserva todo lo que nos sirve:
el pitido, la acción de arranque `stand_slow`, el JSON-RPC en :9030, el MJPG en
:8080 y la cámara. `RunningFunc` queda forzado a 0 para siempre.

=============================================================================
ADAPTACIÓN OBLIGATORIA ANTES DE INSTALAR
=============================================================================
Este fichero está derivado del `TonyPi.py` de Hiwonder (rama `main`, para
Raspberry Pi 5). TU robot es un TonyPi v1.0 con Raspbian Buster y Python 3.7.

  1. Compara con tu fichero real:
         ssh pi@<ROBOT> 'cat /home/pi/TonyPi/TonyPi.py'
  2. Ajusta SOLO lo que difiera: rutas (`/home/pi/TonyPi/...`), nombres de
     módulos (`hiwonder.Camera`, `hiwonder.yaml_handle`) y la sintaxis.
  3. No copies esto sin esa comparación. Si tu TonyPi.py es muy distinto,
     PREFIERE la Opción A de la guía (mantener el servicio de fábrica y llamar
     a `UnloadFunc` tras cada arranque): es menos invasiva.

    diff /home/pi/TonyPi/TonyPi.py TonyPi_rpc_only.py

=============================================================================
INSTALACIÓN
=============================================================================
    scp TonyPi_rpc_only.py pi@<ROBOT>:/home/pi/TonyPi/
    scp tonypi-rpc.service  pi@<ROBOT>:/etc/systemd/system/   (con sudo)
    ssh pi@<ROBOT> 'sudo systemctl daemon-reload && \
                     sudo systemctl disable tonypi.service && \
                     sudo systemctl enable --now tonypi-rpc.service'

ROLLBACK:
    ssh pi@<ROBOT> 'sudo systemctl disable --now tonypi-rpc.service && \
                     sudo systemctl enable --now tonypi.service'
"""

import sys
import os
import time
import queue
import threading
import logging

import cv2
import numpy as np

import RPCServer
import MjpgServer
import hiwonder.Camera as Camera
import hiwonder.yaml_handle as yaml_handle
import Functions.Running as Running

if sys.version_info.major == 2:
    print('Please run this program with python3!')
    sys.exit(0)

# Cola de trabajo del hilo principal: aquí es donde el servidor RPC deposita
# las llamadas para que se ejecuten fuera del hilo HTTP.
QUEUE_RPC = queue.Queue(10)


def task():
    """Consume la cola y ejecuta las peticiones RPC en el hilo principal."""
    while True:
        try:
            req, ret = QUEUE_RPC.get(False)
            event, params, *_ = ret
            ret[2] = req(params)
            event.set()
        except queue.Empty:
            time.sleep(0.01)


def start_tony_pi_rpc_only():
    # 1) Servidor JSON-RPC en el puerto 9030 (y el de vídeo en el 8080)
    RPCServer.QUEUE = QUEUE_RPC
    threading.Thread(target=RPCServer.startRPCServer, daemon=True).start()
    threading.Thread(target=task, daemon=True).start()
    threading.Thread(target=MjpgServer.startMjpgServer, daemon=True).start()

    # 2) Cámara (imprescindible para el snapshot de visión que pide el LLM)
    loading_picture = None
    try:
        loading_picture = cv2.imread('/home/pi/TonyPi/Functions/loading.jpg')
    except Exception as e:
        print('loading.jpg no disponible:', e)

    cam = Camera.Camera()
    try:
        open_once = yaml_handle.get_yaml_data('/boot/camera_setting.yaml')['open_once']
    except Exception:
        open_once = False

    if open_once:
        cam.camera_open()

    Running.open_once = open_once
    Running.cam = cam

    # 3) ======================================================================
    #    AQUÍ ESTÁ EL CAMBIO RESPECTO AL TONYPI.PY DE FÁBRICA
    #    Forzamos el reposo: el robot NO ejecuta ningún programa de juego.
    #    Sin esto, cualquier función cargada (1..12) bloquea el hilo principal
    #    y nuestras llamadas RPC expiran con E04.
    # ======================================================================
    Running.RunningFunc = 0
    print('[tonypi-rpc] modo reposo forzado: RunningFunc = 0', flush=True)
    print('[tonypi-rpc] JSON-RPC en :9030 · MJPG en :8080 · cámara activa', flush=True)

    # 4) Bucle principal: sin juego, pero manteniendo `img_show` al día.
    #    OJO: `/?action=snapshot` sirve ESTA MISMA variable. Si no se refresca,
    #    el snapshot que pide el modelo de visión devuelve 0 bytes.
    while True:
        time.sleep(0.03)
        try:
            if cam.frame is not None:
                MjpgServer.img_show = cam.frame
            elif loading_picture is not None:
                MjpgServer.img_show = loading_picture
        except Exception as e:
            print('error', e)


if __name__ == '__main__':
    logging.basicConfig(level=logging.ERROR)
    start_tony_pi_rpc_only()

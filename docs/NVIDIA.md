# NVIDIA NIM para el TonyPi — resultados verificados

Todo lo de esta página está **medido contra la API con tu clave**, no copiado de
blogs. Fecha de la medición: **2026-11-04**.

---

## 1. La clave

- Creada en <https://build.nvidia.com/settings> (verificación de teléfono, sin tarjeta).
- Endpoint: `https://integrate.api.nvidia.com/v1` (compatible con OpenAI).
- Auth: `Authorization: Bearer nvapi-...`.
- **Guardada cifrada** como secreto `NVIDIA_API_KEY`. En los comandos se
  referencia con `${NVIDIA_API_KEY}`.

## 2. Límite real del free tier

**~40 peticiones por minuto por clave.** No hay créditos: la restricción es el
rate limit. Hay dos consecuencias prácticas:

1. Un turno de conversación del robot puede gastar **2-5 llamadas** (una por
   tool call). Con el modelo `bolt-e4b` son 1-2, así que entran ~15-20 turnos
   por minuto.
2. Si el agente encadena muchas herramientas, se come el límite. Por eso el
   código reintenta con backoff y respeta el `Retry-After`.

> **El catálogo miente a medias.** `GET /v1/models` devuelve **85 modelos**,
> pero algunos devuelven **404** para esta cuenta (`meta/llama-3.2-11b-vision-instruct`,
> `microsoft/phi-3-vision-128k-instruct`). El catálogo no es la verdad: la
> verdad es el sondeo.

## 3. Resultado del sondeo

| Modelo | chat | tool calling | vision | Veredicto |
|---|---|---|---|---|
| **`nvidia/nemotron-3.5-bolt-e4b`** | 0,43 s | 0,29 s | ✓ (0,57 s) | **Ganador** |
| `minimaxai/minimax-m3.1-flash` | 1,39 s | 3,76 s | ✓ | Reserva (más inteligente, más lento) |
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` | 0,96 s | ✓ | ✓ | Alternativa multimodal |
| `nvidia/nemotron-3.5-lightning-30b-a12b` | 0,24 s | ✗ | ✗ | No sirve: no llama herramientas |
| `nvidia/nemotron-3.5-super-vl-120b-a12b` | 0,37 s | ✗ | ✓ | No sirve: no llama herramientas |
| `meta/llama-3.2-11b-vision-instruct` | — | — | — | 404 en esta cuenta |
| `microsoft/phi-3-vision-128k-instruct` | — | — | — | 404 en esta cuenta |

### Por qué `bolt-e4b` y no el más rápido

`nemotron-3.5-lightning-30b-a3b` responde en 0,24 s pero **no devuelve
`tool_calls`**. Sin tool calling el modelo solo habla: diría "voy a saludar" y no
saludaría. Para un robot eso no vale.

`bolt-e4b` es el único que cumple las tres cosas a la vez.

## 4. Las manías de este modelo (y cómo las compensamos)

`nemotron-3.5-bolt-e4b` es rápido pero tiene un defecto: **a veces escribe la
llamada a herramienta como texto plano en vez de usar el campo `tool_calls`**.
Se han observado cuatro formas:

```
robot_walk(direction="forward",steps="3")            parentesis
robot_look{pan:<|"|>2000<|"|>,tilt:<|"|>1500<|"|>}    llaves + tokens internos
robot_stop                                             nombre solo
```

Sin compensación, el robot "responde" pero **nunca se mueve**: el modelo dice
"ya avanzo" y no pasa nada.

La solución está en `tool_parse.py`, que detecta las cuatro formas, las
convierte en llamadas reales y las quita del texto que se va a leer en voz
alta. El bucle del agente (`voice_agent.run_turn`) lo aplica automáticamente.

El mismo modelo, además, tiende a **contestar en indonesio** si no se le
insiste. El prompt del sistema lo arregla ("Responde SIEMPRE en español"),
verificado: "Hola. Todo en orden, aunque mi batería pida tregua."

Si prefieres un modelo más "estricto" y sin manías, la alternativa es
`minimaxai/minimax-m3.1-flash`: 6/6 también, tool_calls siempre correctos, pero
más lento (1,4-3,8 s) y más verboso (2-5 llamadas por petición).

## 5. Elección semántica de herramienta (6/6)

Evaluado con el bucle completo de herramientas, que es como lo ejecuta el agente:

| Petición | Herramienta elegida | Acierto |
|---|---|---|
| «Saluda a la persona que tienes delante» | `robot_camera_snapshot` → `robot_do_action` | ✓ |
| «Avanza tres pasos hacia delante» | `robot_walk` | ✓ |
| «Para de moverte ahora mismo» | `robot_stop` | ✓ |
| «Qué color ves delante de ti?» | `robot_read_camera_rgb` | ✓ |
| «Mira un poco hacia la derecha» | `robot_look` | ✓ |
| «Busca caras con la cámara» | `robot_start_vision` | ✓ |

**6/6 con `bolt-e4b`** y **6/6 con `minimax-m3.1-flash`**.

La diferencia está en el estilo: `bolt-e4b` hace **1-2 llamadas** por petición
(vence directo), mientras que `minimax` hace **2-5** (primero pregunta el
estado, luego lista las acciones, y solo entonces ejecuta). Para un robot
importa: cada llamada extra es latencia y rate limit.

## 6. Un detalle sobre los argumentos

El modelo devolvió `"steps": "3"` (string) para un parámetro declarado como
`integer`. El código lo absorbe porque `TonyPiClient.walk()` hace `int(steps)`,
y Pydantic (FastMCP) también coacciona `"3"` → `3`. Pero si escribes tus propias
herramientas, **coacciona los números a mano**.

## 7. Configuración final

```bash
export LLM_API_KEY=${NVIDIA_API_KEY}
export LLM_BASE_URL=https://integrate.api.nvidia.com/v1
export LLM_MODEL=nvidia/nemotron-3.5-bolt-e4b
export LLM_LANGUAGE=es
```

En el robot, en `/etc/systemd/system/pontibot.service`:

```ini
Environment="LLM_API_KEY=nvapi-..."
Environment="LLM_BASE_URL=https://integrate.api.nvidia.com/v1"
Environment="LLM_MODEL=nvidia/nemotron-3.5-bolt-e4b"
Environment="LLM_LANGUAGE=es"
```

## 8. Sobre `deepseek-ai/deepseek-v4.1-flash` (medido el 2026-11-04)

**Capaz, pero impracticable para un robot que habla.** Medido con tu clave:

| Prueba | Resultado | Latencia |
|---|---|---|
| Chat | responde, pero el `content` sale **vacío** (todo va a `reasoning_content`) | **157,8 s** |
| Tool calling | ✅ llama `wave` correctamente | **151,9 s** |
| Visión | ✅ identifica el color ("Rojo") | **115,7 s** |
| `reasoning_effort: "low"` | sigue razonando, `content` vacío | 80,2 s |
| `chat_template_kwargs: {"enable_thinking": false}` | ✅ sin razonamiento, responde en español con el prompt | **85,4 s** |

Y lo que decide la cuestión: **con el razonamiento apagado, tres llamadas seguidas
dieron 200 s de timeout, 156 s y 200 s de timeout**. No es lento de forma
predecible: es errático, con cola en el servidor de NVIDIA.

**Veredicto:** el modelo funciona, pero una persona no espera 2,5 minutos a un
robot que tarda en responder, y encima hay un porcentaje alto de que la llamada
simplemente expire. En el bucle de voz es inviable.

**Dónde sí le sirve:** como *planificador* para tareas puntuales y no urgentes
("¿por dónde paso?", "planifica una secuencia de acciones") — aunque con el
riesgo de timeout. Si lo quieres usar así, hay que subir el timeout del cliente
a 240 s y aceptar que el robot puede quedarse mudo un rato.

Alternativa si necesitas "deep thinking": `nvidia/nemotron-3.5-super-vl-120b-a12b`
es multimodal y responde en 0,37 s, pero **no devuelve `tool_calls`** — sirve
para describir imágenes, no para controlar el cuerpo.

## 9. Volver a verificar (el catálogo cambia cada mes)

```bash
python nvidia_models.py --list      # catálogo actual
python nvidia_models.py --probe     # sondea y recomienda
python nvidia_smoke_test.py         # prueba de humo con las 26 herramientas reales
```

`nvidia_catalog.json` guarda el último sondeo con fecha.

"""
Catalogo de modelos NVIDIA NIM: que hay, que es gratis y que sirve de verdad.

En vez de fiarte de una lista de blog, esto PREGUNTA a la API y lo comprueba:

  1. GET /v1/models              -> que modelos existen ahora mismo
  2. chat completion             -> que el modelo responde
  3. tool calling                -> que devuelve tool_calls (necesario para mover el robot)
  4. vision                      -> que acepta imagen (necesario para "dime que ves")

El resultado se cachea en nvidia_catalog.json para no repetir los sondeos.

Uso:
    export NVIDIA_API_KEY=nvapi-...
    python nvidia_models.py --probe          # sondea y recomienda
    python nvidia_models.py --list           # solo el catalogo
    python nvidia_models.py --check MODEL_ID # comprueba uno concreto
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any


def _load_env_file() -> None:
    """
    Carga el .env de la carpeta (si existe).

    Sin esto, el smoke test que lanza el despliegue en el robot no veria la
    clave: el .env no esta en el entorno de la shell, solo en el fichero.
    Las variables ya presentes en el entorno tienen prioridad.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, ".env"),
        os.path.join(os.path.dirname(here), ".env"),
    ]
    path = next((c for c in candidates if os.path.exists(c)), candidates[0])
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for raw in handle:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    except OSError:
        pass


_load_env_file()

# La clave de NVIDIA puede venir como NVIDIA_API_KEY o como LLM_API_KEY: es la
# misma. Si el .env solo tiene LLM_API_KEY (que es lo que escribe el
# despliegue), estas herramientas tienen que funcionar igual.
API_KEY = (
    os.environ.get("NVIDIA_API_KEY", "")
    or os.environ.get("LLM_API_KEY", "")
)

BASE_URL = (
    os.environ.get("NVIDIA_BASE_URL")
    or os.environ.get("LLM_BASE_URL")
    or "https://integrate.api.nvidia.com/v1"
).rstrip("/")
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nvidia_catalog.json")

# Respaldo minimo si Pillow no esta disponible (puede fallar en algunos modelos).
TINY_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRof"
    "Hh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAAB"
    "AAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q=="
)


def _test_image() -> tuple[bytes, str]:
    """
    Imagen de prueba realista: rectangulo rojo sobre fondo gris.

    Importa: con un JPEG de 1x1 algunos modelos devuelven 422 (no lo
    consideran una imagen valida) y dariamos vision+ por falso negativo.
    """
    try:
        import io

        from PIL import Image, ImageDraw

        image = Image.new("RGB", (128, 128), (120, 120, 120))
        draw = ImageDraw.Draw(image)
        draw.rectangle((40, 40, 88, 88), fill=(220, 30, 30))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue(), "image/png"
    except Exception:
        return TINY_JPEG, "image/jpeg"

# Candidatos por defecto: rapidos, con tool calling y/o vision.
# Se verifican igual en el sondeo, asi que la lista puede quedar obsoleta sin dano.
DEFAULT_CANDIDATES = [
    "minimaxai/minimax-m3.1-flash",
    "nvidia/nemotron-3.5-bolt-e4b",
    "nvidia/nemotron-3.5-lightning-30b-a3b",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
    "nvidia/nemotron-3.5-super-vl-120b-a12b",
    "nvidia/nemotron-3-ultra-550b-a55b",
    "z-ai/glm-5.3",
    "meta/llama-3.1-70b-instruct",
    "qwen/qwen3-coder-480b-a35b-instruct",
]


class NvidiaError(RuntimeError):
    pass


def _api_key(explicit: str | None = None) -> str:
    key = explicit or API_KEY
    if not key:
        raise NvidiaError(
            "falta la clave de NVIDIA. Exporta la clave o guardala como secreto:\n"
            "  export NVIDIA_API_KEY=nvapi-...\n"
            "  (o ponla en el .env como LLM_API_KEY)"
        )
    return key


def _request(path: str, payload: dict[str, Any] | None = None, timeout: int = 60,
             api_key: str | None = None, retries: int = 4) -> dict[str, Any]:
    """
    Peticion a la API de NVIDIA.

    El free tier esta limitado a ~40 peticiones/minuto por clave, asi que un
    429 es normal cuando el sondeo encadena varias llamadas. Reintentamos con
    backoff exponencial.
    """
    url = path if path.startswith("http") else f"{BASE_URL}{path}"
    key = api_key or _api_key()
    last_error = ""

    for attempt in range(retries):
        if payload is None:
            request = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
        else:
            request = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
                method="POST",
            )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            last_error = f"HTTP {exc.code} en {url}: {detail[:300]}"
            if exc.code == 429 and attempt < retries - 1:
                # El free tier son ~40 peticiones/minuto por clave. Si la API
                # manda Retry-After lo respetamos; si no, esperamos con backoff.
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                try:
                    wait = float(retry_after) if retry_after else 12 * (attempt + 1)
                except (TypeError, ValueError):
                    wait = 12 * (attempt + 1)
                time.sleep(min(wait, 75))
                continue
            raise NvidiaError(last_error) from exc
        except urllib.error.URLError as exc:
            last_error = f"no se pudo contactar a NVIDIA: {exc.reason}"
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise NvidiaError(last_error) from exc
        except TimeoutError as exc:
            # socket.timeout es TimeoutError en Python 3.10+: un modelo lento
            # no debe tumbar el agente.
            last_error = f"timeout esperando a NVIDIA tras {timeout}s"
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise NvidiaError(last_error) from exc
    raise NvidiaError(last_error)


# --------------------------------------------------------------------------- #
# Catalogo
# --------------------------------------------------------------------------- #
def fetch_catalog(api_key: str | None = None) -> list[dict[str, Any]]:
    """GET /v1/models -> lista de modelos disponibles."""
    body = _request("/models", api_key=api_key)
    return body.get("data", []) or []


def model_ids(catalog: list[dict[str, Any]]) -> list[str]:
    return [entry.get("id", "") for entry in catalog if entry.get("id")]


# --------------------------------------------------------------------------- #
# Sondas
# --------------------------------------------------------------------------- #
def probe_chat(model_id: str, api_key: str | None = None) -> tuple[bool, float, str]:
    """Devuelve (funciona, latencia_segundos, mensaje)."""
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": "Di OK"}],
        "max_tokens": 16,
    }
    start = time.time()
    try:
        body = _request("/chat/completions", payload, timeout=45, retries=2)
        elapsed = time.time() - start
        choices = body.get("choices") or []
        if not choices:
            return False, elapsed, "respuesta sin choices"
        content = (choices[0].get("message") or {}).get("content") or ""
        return True, elapsed, content[:60]
    except NvidiaError as exc:
        return False, time.time() - start, str(exc)[:160]
    except Exception as exc:  # noqa: BLE001 - una sonda no debe tumbar el script
        return False, time.time() - start, f"{type(exc).__name__}: {str(exc)[:120]}"


def probe_tool_calling(model_id: str, api_key: str | None = None) -> tuple[bool, float, str]:
    """El modelo devuelve una llamada a herramienta? (imprescindible para el robot)."""
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": "Saluda a la persona que tienes delante."}],
        "tools": [{
            "type": "function",
            "function": {
                "name": "wave",
                "description": "El robot saluda con la mano",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }],
        "tool_choice": "auto",
        "max_tokens": 128,
    }
    start = time.time()
    try:
        body = _request("/chat/completions", payload, timeout=45, retries=2)
        elapsed = time.time() - start
        message = (body.get("choices") or [{}])[0].get("message") or {}
        calls = message.get("tool_calls") or []
        if calls:
            name = (calls[0].get("function") or {}).get("name", "?")
            return True, elapsed, f"tool_calls ok ({name})"
        if message.get("content"):
            return False, elapsed, "respondio texto, no llamo a la herramienta"
        return False, elapsed, "respuesta vacia"
    except NvidiaError as exc:
        return False, time.time() - start, str(exc)[:160]
    except Exception as exc:  # noqa: BLE001 - una sonda no debe tumbar el script
        return False, time.time() - start, f"{type(exc).__name__}: {str(exc)[:120]}"


def probe_vision(model_id: str, api_key: str | None = None) -> tuple[bool, float, str]:
    """El modelo acepta una imagen? (necesario para 'dime que ves')."""
    image, mime = _test_image()
    payload = {
        "model": model_id,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": "De que color es el rectangulo? Una palabra."},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64," + base64.b64encode(image).decode()}},
            ],
        }],
        "max_tokens": 48,
    }
    start = time.time()
    try:
        body = _request("/chat/completions", payload, timeout=60, retries=2)
        elapsed = time.time() - start
        choices = body.get("choices") or []
        if not choices:
            return False, elapsed, "respuesta sin choices"
        message = choices[0].get("message") or {}
        content = (message.get("content") or "").strip()
        # los modelos de razonamiento pueden devolver el texto en otro sitio
        if not content:
            content = (message.get("reasoning_content") or "").strip()
        if content:
            return True, elapsed, content[:60]
        return False, elapsed, "respuesta sin texto"
    except NvidiaError as exc:
        return False, time.time() - start, str(exc)[:160]
    except Exception as exc:  # noqa: BLE001 - una sonda no debe tumbar el script
        return False, time.time() - start, f"{type(exc).__name__}: {str(exc)[:120]}"


def probe_all(model_id: str, api_key: str | None = None) -> dict[str, Any]:
    """Sondea un modelo en las tres dimensiones que necesita el robot."""
    chat_ok, chat_lat, chat_msg = probe_chat(model_id, api_key)
    result: dict[str, Any] = {
        "model": model_id,
        "chat_ok": chat_ok,
        "chat_latency": round(chat_lat, 2),
        "chat_msg": chat_msg,
    }
    if chat_ok:
        tools_ok, tools_lat, tools_msg = probe_tool_calling(model_id, api_key)
        result["tools_ok"] = tools_ok
        result["tools_latency"] = round(tools_lat, 2)
        result["tools_msg"] = tools_msg
        vision_ok, vision_lat, vision_msg = probe_vision(model_id, api_key)
        result["vision_ok"] = vision_ok
        result["vision_latency"] = round(vision_lat, 2)
        result["vision_msg"] = vision_msg
    return result


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #
def save_cache(results: list[dict[str, Any]]) -> None:
    with open(CACHE_FILE, "w", encoding="utf-8") as handle:
        json.dump({"base_url": BASE_URL, "probed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "results": results}, handle, indent=2, ensure_ascii=False)


def load_cache() -> dict[str, Any] | None:
    if not os.path.exists(CACHE_FILE):
        return None
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def recommend(results: list[dict[str, Any]]) -> str | None:
    """Elige el mejor modelo para el robot: responde, llama a herramientas y es rapido."""
    def score(entry: dict[str, Any]) -> float:
        value = 0.0
        if entry.get("chat_ok"):
            value += 10
        if entry.get("tools_ok"):
            value += 10
        if entry.get("vision_ok"):
            value += 6
        # menos de 3 segundos es aceptable para un robot
        latency = entry.get("chat_latency", 99)
        if latency < 1.5:
            value += 5
        elif latency < 3:
            value += 3
        elif latency < 6:
            value += 1
        return value

    best = max(results, key=score)
    return best["model"] if score(best) >= 16 else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Sondeo de modelos NVIDIA NIM gratuitos")
    parser.add_argument("--list", action="store_true", help="solo listar el catalogo")
    parser.add_argument("--probe", action="store_true", help="sondear los candidatos")
    parser.add_argument("--check", default="", help="sondear un modelo concreto")
    parser.add_argument("--candidates", default="", help="lista de ids separados por comas")
    args = parser.parse_args()

    try:
        catalog = fetch_catalog()
    except NvidiaError as exc:
        print(f"ERROR: {exc}")
        return 1

    ids = model_ids(catalog)
    print(f"catalogo NVIDIA: {len(ids)} modelos")

    if args.list:
        for model_id in ids:
            print(f"  {model_id}")
        return 0

    if args.check:
        result = probe_all(args.check)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    if not args.probe:
        print("usa --list, --probe o --check")
        return 0

    candidates = [c.strip() for c in args.candidates.split(",") if c.strip()] if args.candidates else DEFAULT_CANDIDATES
    # solo sondeamos modelos que existen en el catalogo
    candidates = [c for c in candidates if c in ids] or ids[:12]

    results: list[dict[str, Any]] = []
    print(f"\nsondeando {len(candidates)} modelos...\n")
    for model_id in candidates:
        result = probe_all(model_id)
        results.append(result)
        flags = []
        flags.append("chat+" if result["chat_ok"] else "chat-")
        flags.append("tools+" if result.get("tools_ok") else "tools-")
        flags.append("vision+" if result.get("vision_ok") else "vision-")
        print(f"  {result['model']:<50} {result['chat_latency']:>6.2f}s  {' '.join(flags)}")

    save_cache(results)
    best = recommend(results)
    print("\n=== resultado ===")
    if best:
        print(f"modelo recomendado: {best}")
        print(f"\nexport LLM_BASE_URL={BASE_URL}")
        print(f"export LLM_MODEL={best}")
    else:
        print("ningun candidato cumple chat + tool calling a la vez")
        print("mira el detalle en nvidia_catalog.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

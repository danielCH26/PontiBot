"""
Bloque de codigo que se inserta en el RPCServer.py del robot.

Añade cinco metodos que el firmware oficial NO expone por RPC:

    SetBuzzer(freq, on_time, off_time, repeat)   -> pitido en el buzzer
    PlayAudio(nombre_o_ruta)                     -> reproduce un sonido
    Speak(texto, backend)                        -> sintetiza y reproduce
    ListFiles(ruta, patron, max)                 -> lista ficheros de un disco
    ReadFile(ruta, max_bytes)                    -> lee un fichero de texto

Los dos ultimos son los que permiten que PontiBot lea un disco duro externo:
el disco esta en el robot, asi que el listado tiene que ocurrir alli.

Todo el acceso a ficheros esta RESTRINGIDO a unas carpetas concretas (las de
montaje: /media/pi, /mnt, /media/usb0...) y es de SOLO LECTURA.

No es obligatorio: sirve para que el LLM, via MCP, pueda hacer que el robot
suene o hable sin depender del agente de voz.

Uso: python apply_patch.py [ruta/al/RPCServer.py]
"""

MARKER_START = "# ================= INICIO PATCH tonypi-mcp ================="
MARKER_END = "# ================= FIN PATCH tonypi-mcp ================="

_PATCH_CODE = '''
import os as _os
import subprocess as _subprocess
import fnmatch as _fnmatch


# Carpetas donde el bot puede leer. Todo lo demas queda fuera.
_STORAGE_ROOTS = [
    '/media/pi',
    '/mnt',
    '/media/usb0',
    '/media/usb1',
    '/media/usb2',
    '/home/pi/TonyPi/audio',
]

_AUDIO_EXT = ('.wav', '.mp3', '.ogg', '.flac', '.m4a', '.aac', '.opus')


def _storage_safe(path):
    """Normaliza una ruta y devuelve None si no esta en una carpeta permitida."""
    if path is None:
        return None
    path = str(path).strip()
    if not path or '\\x00' in path:
        return None
    candidates = []
    if _os.path.isabs(path):
        candidates.append(path)
    else:
        for root in _STORAGE_ROOTS:
            candidates.append(_os.path.join(root, path))
    for candidate in candidates:
        normalized = _os.path.normpath(candidate)
        if '..' in normalized.split(_os.sep):
            continue
        for root in _STORAGE_ROOTS:
            root_norm = _os.path.normpath(root)
            if not (normalized == root_norm or normalized.startswith(root_norm.rstrip('/') + '/')):
                continue
            try:
                real = _os.path.realpath(normalized)
                real_root = _os.path.realpath(root_norm)
            except OSError:
                continue
            if real == real_root or real.startswith(real_root.rstrip('/') + '/'):
                return normalized
    return None


@dispatcher.add_method
def SetBuzzer(*args):
    """(freq, on_time, off_time, repeat) - pitido en el buzzer de la expansion."""
    ret = (True, (), 'SetBuzzer')
    if len(args) != 4:
        return (False, __RPC_E01, 'SetBuzzer')
    try:
        freq, on_time, off_time, repeat = (int(a) for a in args)
        ctl.set_buzzer(freq, on_time, off_time, repeat)
    except Exception as e:
        print(e)
        ret = (False, __RPC_E03, 'SetBuzzer')
    return ret


@dispatcher.add_method
def PlayAudio(*args):
    """(nombre_o_ruta) - reproduce un sonido.

    Acepta un nombre suelto (del directorio audio/ del robot) o una ruta dentro
    de las carpetas montadas (/media/pi, /mnt, ...), por ejemplo
    'canciones/robot.mp3'.
    """
    ret = (True, (), 'PlayAudio')
    if len(args) != 1:
        return (False, __RPC_E01, 'PlayAudio')
    name = str(args[0]).strip()
    if not name:
        return (False, __RPC_E02, 'PlayAudio')

    path = None
    if '/' in name or '\\\\' in name:
        path = _storage_safe(name)
        if path is None:
            return (False, 'E02 - ruta no permitida: {}'.format(name), 'PlayAudio')
    else:
        path = '/home/pi/TonyPi/audio/{}.wav'.format(name)
        if not _os.path.exists(path):
            # Puede estar en un disco externo: busca en las carpetas montadas.
            for root in _STORAGE_ROOTS:
                candidate = _os.path.join(root, name)
                if _os.path.isfile(candidate):
                    path = candidate
                    break
            else:
                return (False, 'E03 - audio not found: {}'.format(name), 'PlayAudio')

    if not _os.path.isfile(path):
        return (False, 'E03 - no existe: {}'.format(path), 'PlayAudio')

    extension = _os.path.splitext(path)[1].lower()
    if extension == '.wav':
        players = [['aplay', '-q', path]]
    elif extension == '.mp3':
        players = [['mpg123', '-q', path], ['ffplay', '-nodisp', '-autoexit', '-loglevel', 'quiet', path]]
    elif extension in ('.ogg', '.opus'):
        players = [['ogg123', '-q', path], ['ffplay', '-nodisp', '-autoexit', '-loglevel', 'quiet', path]]
    elif extension == '.flac':
        players = [['flac', path], ['ffplay', '-nodisp', '-autoexit', '-loglevel', 'quiet', path]]
    else:
        players = [['ffplay', '-nodisp', '-autoexit', '-loglevel', 'quiet', path]]

    last_error = ''
    for player in players:
        try:
            _subprocess.Popen(player)
            return ret
        except FileNotFoundError as e:
            last_error = str(e)
        except Exception as e:
            print(e)
            last_error = str(e)
            break
    return (False, 'E03 - no hay reproductor para {} ({})'.format(path, last_error), 'PlayAudio')


@dispatcher.add_method
def ListFiles(*args):
    """(ruta, patron, max) - lista los ficheros de una carpeta montada.

    ruta: '' para la raiz, o relativa a una de las carpetas permitidas.
    patron: opcional, tipo '*.mp3'.
    """
    ret = (True, (), 'ListFiles')
    if len(args) > 3:
        return (False, __RPC_E01, 'ListFiles')
    raw_path = args[0] if len(args) > 0 else ''
    pattern = str(args[1]) if len(args) > 1 and args[1] else ''
    try:
        max_entries = int(args[2]) if len(args) > 2 and args[2] else 200
    except (TypeError, ValueError):
        max_entries = 200
    max_entries = max(1, min(max_entries, 500))

    if not str(raw_path).strip():
        # Sin ruta: devuelve las carpetas montadas que existen.
        roots = []
        for root in _STORAGE_ROOTS:
            if _os.path.isdir(root):
                roots.append({'name': root, 'is_dir': True, 'size': 0})
        if not roots:
            return (False, 'E03 - no hay ninguna carpeta montada ({})'.format(', '.join(_STORAGE_ROOTS)), 'ListFiles')
        return (True, roots, 'ListFiles')

    path = _storage_safe(raw_path)
    if path is None:
        return (False, 'E02 - ruta no permitida: {}'.format(raw_path), 'ListFiles')
    if not _os.path.isdir(path):
        return (False, 'E03 - no es una carpeta: {}'.format(path), 'ListFiles')

    entries = []
    try:
        names = sorted(_os.listdir(path))
    except PermissionError:
        return (False, 'E03 - sin permiso de lectura en {}'.format(path), 'ListFiles')
    except OSError as e:
        return (False, 'E03 - {}'.format(e), 'ListFiles')

    for name in names:
        if pattern and not _fnmatch.fnmatch(name, pattern):
            continue
        full = _os.path.join(path, name)
        try:
            is_dir = _os.path.isdir(full)
            size = 0 if is_dir else _os.path.getsize(full)
        except OSError:
            is_dir, size = False, 0
        entries.append({'name': name, 'is_dir': is_dir, 'size': size})
        if len(entries) >= max_entries:
            break

    return (True, entries, 'ListFiles')


@dispatcher.add_method
def ReadFile(*args):
    """(ruta, max_bytes) - lee un fichero de texto de una carpeta permitida."""
    ret = (True, (), 'ReadFile')
    if len(args) < 1 or len(args) > 2:
        return (False, __RPC_E01, 'ReadFile')
    raw_path = args[0]
    try:
        max_bytes = int(args[1]) if len(args) > 1 and args[1] else 4000
    except (TypeError, ValueError):
        max_bytes = 4000
    max_bytes = max(1, min(max_bytes, 20000))

    path = _storage_safe(raw_path)
    if path is None:
        return (False, 'E02 - ruta no permitida: {}'.format(raw_path), 'ReadFile')
    if not _os.path.isfile(path):
        return (False, 'E03 - no existe: {}'.format(path), 'ReadFile')

    try:
        with open(path, 'rb') as handle:
            data = handle.read(max_bytes)
    except PermissionError:
        return (False, 'E03 - sin permiso de lectura en {}'.format(path), 'ReadFile')
    except OSError as e:
        return (False, 'E03 - {}'.format(e), 'ReadFile')

    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        try:
            text = data.decode('latin-1')
        except Exception:
            return (False, 'E03 - el fichero no es texto', 'ReadFile')

    truncated = len(data) >= max_bytes
    return (True, (text, truncated), 'ReadFile')


@dispatcher.add_method
def Speak(*args):
    """(texto, backend) - sintetiza el texto y lo reproduce. backend: piper | espeak"""
    ret = (True, (), 'Speak')
    if len(args) < 1:
        return (False, __RPC_E01, 'Speak')
    text = str(args[0])
    backend = str(args[1]) if len(args) > 1 else 'espeak'
    if not text.strip():
        return (False, __RPC_E02, 'Speak')
    wav_path = '/tmp/tonypi_speak.wav'
    try:
        if backend == 'piper':
            _subprocess.run(['piper', '--output_file', wav_path], input=text,
                            text=True, check=True, timeout=60)
        else:
            _subprocess.run(['espeak-ng', '-v', 'es', '-s', '165', '-w', wav_path, text],
                            check=True, timeout=60)
        _subprocess.Popen(['aplay', '-q', wav_path])
    except FileNotFoundError as e:
        return (False, 'E03 - {}: {}'.format(backend, e), 'Speak')
    except Exception as e:
        print(e)
        ret = (False, __RPC_E03, 'Speak')
    return ret
'''

# El bloque lleva los separadores de linea exactos para que apply/undo
# sean reversibles byte a byte.
PATCH_BLOCK = "\n\n" + MARKER_START + "\n" + _PATCH_CODE + MARKER_END + "\n"

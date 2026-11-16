# -*- coding: utf-8 -*-
"""Fuentes de datos y de eventos.

Nada aqui bloquea el hilo de GTK: bspwm y el FIFO entran por watchers de
GLib, y lo que hay que sondear (bateria, red) se lee de sysfs cada pocos
segundos. Si el dibujado se bloquease, la animacion daria tirones, que
es justo lo que se intenta evitar.
"""
import os
import json
import time
import subprocess
import glob
import hashlib
import socket
import fcntl
import struct
import threading
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GLib, Gtk, GdkPixbuf
import config as C


def _read(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


# ------------------------------------------------------------ sistema

class SystemInfo(object):
    def __init__(self):
        self.battery = 100
        self.charging = False
        self.wifi = False
        self.ip = ""
        self.vpn_ip = ""
        self.volume = 100
        self.muted = False
        self._bat = self._find_battery()
        self.refresh()

    def _find_battery(self):
        for p in sorted(glob.glob("/sys/class/power_supply/BAT*")):
            return p
        return None

    def refresh_power(self):
        """Solo bateria y enchufe: dos lecturas de sysfs, sin lanzar
        procesos. Es lo que permite sondearlo cada segundo."""
        if self._bat:
            c = _read(self._bat + "/capacity")
            if c.isdigit():
                self.battery = int(c)
            self.charging = _read(self._bat + "/status") in ("Charging", "Full")

    def refresh(self):
        if self._bat:
            c = _read(self._bat + "/capacity")
            if c.isdigit():
                self.battery = int(c)
            self.charging = _read(self._bat + "/status") in ("Charging", "Full")

        # operstate dice si el enlace esta arriba sin lanzar procesos
        self.wifi = _read("/sys/class/net/%s/operstate" % C.IFACE_WIFI) == "up"
        self.ip = self._addr(C.IFACE_WIFI)
        self.vpn_ip = self._addr(C.IFACE_VPN)

        # PipeWire, no ALSA: el control real del sistema es wpctl.
        try:
            out = subprocess.run(
                ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                capture_output=True, text=True, timeout=1).stdout
            # "Volume: 0.53" o "Volume: 0.53 [MUTED]"
            parts = out.split()
            if len(parts) >= 2:
                self.volume = int(round(float(parts[1]) * 100))
            self.muted = "MUTED" in out
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        return True

    def _addr(self, iface):
        """IPv4 de una interfaz por ioctl, sin lanzar 'ip'.

        SIOCGIFADDR devuelve el dato del kernel directamente: es
        instantaneo y ahorra un fork+exec en cada sondeo. Lanzar un
        proceso entero para leer cuatro bytes era el gasto mas tonto
        del ciclo.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            packed = fcntl.ioctl(
                sock.fileno(), 0x8915,                    # SIOCGIFADDR
                struct.pack("256s", iface[:15].encode()))
            return socket.inet_ntoa(packed[20:24])
        except OSError:
            return ""            # interfaz inexistente o sin IPv4
        finally:
            sock.close()


# -------------------------------------------------------------- bspwm

class Bspwm(object):
    """Escritorios en vivo via 'bspc subscribe report'.

    Se usa el flujo de eventos y no un sondeo porque el cambio de
    escritorio tiene que verse en el fotograma siguiente; con polling
    habria un retardo perceptible justo en lo que mas se mira.
    """
    def __init__(self, on_change):
        self.on_change = on_change
        self.desktops = []      # [(nombre, estado)] estado: free|occupied|urgent
        self.focused = 0
        self.proc = None
        self.start()

    def start(self):
        try:
            self.proc = subprocess.Popen(
                ["bspc", "subscribe", "report"],
                stdout=subprocess.PIPE, text=True, bufsize=1)
        except OSError:
            return
        GLib.io_add_watch(self.proc.stdout, GLib.PRIORITY_DEFAULT,
                          GLib.IO_IN | GLib.IO_HUP, self._on_line)

    def _on_line(self, src, cond):
        if cond & GLib.IO_HUP:
            return False
        line = src.readline()
        if not line:
            return False
        self._parse(line.strip())
        self.on_change()
        return True

    def _parse(self, line):
        # Formato: W  seguido de elementos separados por ':'. La inicial
        # de cada elemento es el tipo+estado; las mayusculas marcan el
        # elemento con el foco.
        #   O/o = ocupado,  F/f = libre,  U/u = urgente
        desks = []
        focused = 0
        for item in line.lstrip("W").split(":"):
            if not item:
                continue
            k, name = item[0], item[1:]
            if k in "OoFfUu":
                state = {"o": "occupied", "f": "free", "u": "urgent"}[k.lower()]
                if k.isupper():
                    focused = len(desks)
                desks.append((name, state))
        if desks:
            self.desktops = desks
            self.focused = focused


# --------------------------------------------------------------- foco

def _arbol_tiene(pid, nombre):
    """True si `pid` o alguno de sus descendientes se llama `nombre`.

    Un solo `ps` y se recorre el arbol en memoria: lanzar uno por nivel
    seria mas lento justo en el momento sensible, que es el cambio de
    foco.
    """
    try:
        salida = subprocess.run(["ps", "-eo", "pid=,ppid=,comm="],
                                capture_output=True, text=True,
                                timeout=2).stdout
    except Exception:
        return False
    hijos, nombres = {}, {}
    for linea in salida.split("\n"):
        campos = linea.split(None, 2)
        if len(campos) != 3:
            continue
        try:
            hijo, padre = int(campos[0]), int(campos[1])
        except ValueError:
            continue
        hijos.setdefault(padre, []).append(hijo)
        nombres[hijo] = campos[2]
    pila, visto = [pid], set()
    while pila:
        p = pila.pop()
        if p in visto:
            continue
        visto.add(p)
        if nombre in nombres.get(p, "").lower():
            return True
        pila.extend(hijos.get(p, []))
    return False


def ventana_enfocada():
    """Quien tiene el foco: id, clase, nombre legible y si es Claude.

    Para Claude Code no sirve el titulo: la terminal lo cambia a lo que
    este haciendo la conversacion, asi que dice de QUE va la ventana
    pero no de que programa es. Lo que si lo dice es el arbol de
    procesos: si de esa ventana cuelga un proceso que se llama claude,
    es Claude Code.
    """
    def _run(cmd):
        try:
            return subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=2).stdout.strip()
        except Exception:
            return ""

    wid = _run(["bspc", "query", "-N", "-n", "focused"])
    if not wid:
        return {"id": "", "clase": "", "app": "", "claude": False}
    clase, pid = "", 0
    for linea in _run(["xprop", "-id", wid, "WM_CLASS", "_NET_WM_PID"]).split("\n"):
        if linea.startswith("WM_CLASS"):
            partes = [x.strip().strip('"')
                      for x in linea.split("=", 1)[-1].split(",")]
            clase = (partes[-1] or partes[0]).strip().lower()
        elif linea.startswith("_NET_WM_PID"):
            try:
                pid = int(linea.split("=")[-1])
            except ValueError:
                pid = 0
    claude = bool(pid) and _arbol_tiene(pid, "claude")
    app = "Claude" if claude else {
        "kitty": "Terminal", "google-chrome": "Chrome",
        "chromium": "Chromium"}.get(clase, clase)
    return {"id": wid, "clase": clase, "app": app, "claude": claude}


class Foco(object):
    """Ventana enfocada, en vivo via 'bspc subscribe node_focus'.

    Existe para una sola cosa: que el notch pueda decir que el dictado
    esta disponible cuando miras una ventana de Claude. Por eso NO
    sondea: recorrer el arbol de procesos cada pocos segundos para un
    indicador que casi nunca cambia seria gastar bateria en nada. Se
    mira cuando el foco cambia, que es la unica vez que puede cambiar
    la respuesta.
    """
    def __init__(self, on_change):
        self.on_change = on_change
        self.info = {"id": "", "clase": "", "app": "", "claude": False}
        self.proc = None
        self.refrescar()
        self.start()

    def start(self):
        try:
            self.proc = subprocess.Popen(
                ["bspc", "subscribe", "node_focus"],
                stdout=subprocess.PIPE, text=True, bufsize=1)
        except OSError:
            return
        GLib.io_add_watch(self.proc.stdout, GLib.PRIORITY_DEFAULT,
                          GLib.IO_IN | GLib.IO_HUP, self._on_line)

    def _on_line(self, src, cond):
        if cond & GLib.IO_HUP:
            return False
        if not src.readline():
            return False
        antes = self.info.get("claude")
        self.refrescar()
        # Solo molesta a la isla si CAMBIA la respuesta: alt-tab entre
        # dos ventanas que no son Claude no tiene por que repintar nada.
        if self.info.get("claude") != antes:
            self.on_change()
        return True

    def refrescar(self):
        self.info = ventana_enfocada()

    @property
    def claude(self):
        return bool(self.info.get("claude"))


# --------------------------------------------------------------- fifo

class Fifo(object):
    """Entrada de eventos externos: una linea JSON por evento.

    Se reabre despues de cada EOF. Un FIFO devuelve EOF en cuanto el
    ultimo escritor cierra, asi que sin reabrir el demonio solo
    atenderia al primer cliente y despues quedaria sordo.
    """
    def __init__(self, path, on_event):
        self.path = path
        self.on_event = on_event
        if os.path.exists(path):
            os.unlink(path)
        os.mkfifo(path, 0o600)
        self._open()

    def _open(self):
        fd = os.open(self.path, os.O_RDONLY | os.O_NONBLOCK)
        self.ch = GLib.IOChannel.unix_new(fd)
        self.ch.set_encoding(None)
        self.ch.set_buffered(False)
        self._buf = b""
        GLib.io_add_watch(self.ch, GLib.PRIORITY_DEFAULT,
                          GLib.IO_IN | GLib.IO_HUP, self._on_io)

    def _on_io(self, ch, cond):
        if cond & GLib.IO_IN:
            try:
                data = os.read(ch.unix_get_fd(), 65536)
            except OSError:
                data = b""
            if data:
                self._buf += data
                while b"\n" in self._buf:
                    line, self._buf = self._buf.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        self.on_event(json.loads(line.decode("utf-8")))
                    except (ValueError, UnicodeDecodeError):
                        pass
        if cond & GLib.IO_HUP:
            # Ultimo escritor cerrado: reabrir para seguir escuchando.
            try:
                ch.shutdown(False)
            except Exception:
                pass
            GLib.idle_add(self._open)
            return False
        return True


# ------------------------------------------------------------- musica

class Player(object):
    """Reproduccion actual via MPRIS, usando 'playerctl --follow'.

    Se usa --follow en vez de sondear porque playerctl emite una linea
    en cuanto cambia la pista o el estado: asi la isla reacciona al
    instante y no hay un proceso despertandose cada segundo.

    Si playerctl no esta instalado, 'available' queda en False y el
    resto del programa sigue funcionando sin musica.
    """
    def __init__(self, on_change):
        import shutil
        self.on_change = on_change
        self.status = ""
        self.artist = ""
        self.title = ""
        self.art_url = ""
        self.available = shutil.which("playerctl") is not None
        if self.available:
            self.start()

    def start(self):
        try:
            self.proc = subprocess.Popen(
                ["playerctl", "--follow", "metadata", "--format",
                 "{{status}}\t{{artist}}\t{{title}}\t{{mpris:artUrl}}"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, bufsize=1)
        except OSError:
            self.available = False
            return
        GLib.io_add_watch(self.proc.stdout, GLib.PRIORITY_DEFAULT,
                          GLib.IO_IN | GLib.IO_HUP, self._on_line)

    def _on_line(self, src, cond):
        if cond & GLib.IO_HUP:
            return False
        line = src.readline()
        if not line:
            return False
        parts = (line.rstrip("\n").split("\t") + ["", "", "", ""])[:4]
        self.status, self.artist, self.title, self.art_url = parts
        self.on_change()
        return True

    @property
    def playing(self):
        return self.status == "Playing" and bool(self.title)


def vpn_label():
    """Etiqueta opcional que acompana a la IP de la VPN (ver config)."""
    raw = _read(C.VPN_LABEL_FILE)
    if not raw:
        return ""
    parts = raw.split()
    return parts[1] if len(parts) > 1 else (parts[0] if parts else "")


# ------------------------------------------------------- iconos e imagenes

ART_CACHE = os.path.expanduser("~/.cache/island/art")
_icon_cache = {}


def _from_path(path, size):
    try:
        return GdkPixbuf.Pixbuf.new_from_file_at_scale(path, size, size, True)
    except Exception:
        return None


def _from_theme(name, size):
    try:
        theme = Gtk.IconTheme.get_default()
        info = theme.lookup_icon(name, size, Gtk.IconLookupFlags.FORCE_SIZE)
        if info is not None:
            return info.load_icon()
    except Exception:
        pass
    return None


def load_icon(spec, size, appname=""):
    """Resuelve el icono de una notificacion a un pixbuf ya escalado.

    Se prueban varias fuentes porque las apps son inconsistentes: unas
    mandan una ruta absoluta, otras un nombre del tema de iconos y
    bastantes no mandan nada util y solo queda deducirlo del nombre de
    la aplicacion.
    """
    key = (spec or "", size, appname or "")
    if key in _icon_cache:
        return _icon_cache[key]

    cands = []
    if spec:
        cands.append(spec)
        # Los nombres de tema van en minuscula, pero WM_CLASS suele
        # venir capitalizado ("Google-chrome"): sin esta variante, las
        # ventanas se quedaban sin icono.
        if spec.lower() != spec:
            cands.append(spec.lower())
    if appname:
        low = appname.strip().lower()
        cands += [low, low.replace(" ", "-"), low.split()[0] if low.split() else low]

    pb = None
    for c in cands:
        if not c:
            continue
        if c.startswith("file://"):
            from urllib.parse import urlparse, unquote
            c = unquote(urlparse(c).path)
        if c.startswith("/") and os.path.exists(c):
            pb = _from_path(c, size)
        else:
            pb = _from_theme(c, size)
        if pb is not None:
            break

    _icon_cache[key] = pb
    return pb


def fetch_art(url, size, done):
    """Caratula del reproductor.

    Las rutas file:// se cargan en el acto; las http(s) se bajan EN UN
    HILO y se avisa por GLib.idle_add. Descargar en el hilo de GTK
    congelaria la animacion todo lo que tarde la red, que es justo lo
    que no puede pasar en un widget que esta animandose.
    """
    if not url:
        done(None)
        return

    if url.startswith("file://"):
        from urllib.parse import urlparse, unquote
        done(_from_path(unquote(urlparse(url).path), size))
        return

    if not url.startswith(("http://", "https://")):
        done(None)
        return

    os.makedirs(ART_CACHE, exist_ok=True)
    path = os.path.join(ART_CACHE, hashlib.sha1(url.encode()).hexdigest())
    if os.path.exists(path):
        done(_from_path(path, size))
        return

    def work():
        try:
            import urllib.request
            with urllib.request.urlopen(url, timeout=6) as r:
                data = r.read()
            tmp = path + ".part"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
            pb = _from_path(path, size)
        except Exception:
            pb = None
        GLib.idle_add(done, pb)

    threading.Thread(target=work, daemon=True).start()


# ------------------------------------------------- identificacion de apps web

RULES_PATH = os.path.expanduser("~/.config/island/apps.json")
FAVICON_CACHE = os.path.expanduser("~/.cache/island/favicons")
_rules = {"mtime": 0, "data": []}


def _load_rules():
    """Recarga apps.json si cambio en disco, sin reiniciar la isla."""
    try:
        m = os.path.getmtime(RULES_PATH)
    except OSError:
        return []
    if m != _rules["mtime"]:
        try:
            with open(RULES_PATH) as f:
                raw = json.load(f)
            out = []
            for r in raw:
                if not r.get("match"):
                    continue
                import re
                out.append((re.compile(r["match"], re.I), r))
            _rules["data"] = out
            _rules["mtime"] = m
        except (OSError, ValueError, Exception):
            pass
    return _rules["data"]


def match_app(*fields):
    """Devuelve la regla que casa, o None.

    Hace falta porque Chrome manda TODAS las notificaciones web con
    appname 'Google Chrome': sin mirar el contenido no hay manera de
    distinguir un mensaje de WhatsApp de uno de cualquier otra pestana.
    """
    hay = " ".join(f for f in fields if f)
    for rx, rule in _load_rules():
        if rx.search(hay):
            return rule
    return None


def fetch_favicon(domain, size, done):
    """Favicon del propio sitio, cacheado para siempre.

    Se pide a <dominio>/favicon.ico y NO a un servicio de terceros:
    pasar por uno significaria contarle a ese tercero que sitios te
    mandan notificaciones.
    """
    if not domain:
        done(None)
        return
    os.makedirs(FAVICON_CACHE, exist_ok=True)
    path = os.path.join(FAVICON_CACHE, domain.replace("/", "_") + ".img")
    if os.path.exists(path):
        done(_from_path(path, size))
        return

    def work():
        pb = None
        try:
            import urllib.request
            req = urllib.request.Request(
                "https://%s/favicon.ico" % domain,
                headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as r:
                data = r.read()
            if data:
                tmp = path + ".part"
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, path)
                pb = _from_path(path, size)
        except Exception:
            pb = None
        GLib.idle_add(done, pb)

    threading.Thread(target=work, daemon=True).start()


# ------------------------------------------------------- limpieza de marcado

_TAG_RE = None


def sanitize(s):
    """Quita el marcado que admite el spec de notificaciones.

    El cuerpo puede traer <b>, <i>, <u>, <a href>, <br> y entidades
    (&amp;, &#39;...). dunst las interpreta al pintar su burbuja, pero
    al hook le llega el texto CRUDO, asi que sin esto la isla enseña
    las etiquetas en vez del mensaje.

    El orden importa: primero se quitan las etiquetas REALES y despues
    se descodifican las entidades. Al reves, un mensaje que escribiera
    literalmente "&lt;b&gt;" se convertiria en "<b>" y el borrado de
    etiquetas se comeria texto que el remitente si habia escrito.
    """
    global _TAG_RE
    if not s:
        return ""
    import re
    import html as _html
    if _TAG_RE is None:
        _TAG_RE = re.compile(r"<[^<>]{0,200}?>")
    # <br> separa, no desaparece: sin esto dos frases quedarian pegadas.
    s = re.sub(r"(?i)<br\s*/?>", " ", s)
    s = _TAG_RE.sub("", s)
    s = _html.unescape(s)
    return " ".join(s.split())


# ------------------------------------------------------------- lanzador

APP_DIRS = [
    os.path.expanduser("~/.local/share/applications"),
    "/usr/local/share/applications",
    "/usr/share/applications",
]
# Codigos de campo del spec .desktop: se sustituyen por los ficheros o
# URLs que se pasen al programa. Como aqui se lanza sin argumentos, hay
# que quitarlos o el programa recibiria "%U" como nombre de fichero.
_FIELD_CODES = ("%f", "%F", "%u", "%U", "%d", "%D", "%n", "%N",
                "%i", "%c", "%k", "%v", "%m")


def _parse_desktop(path, lang):
    """Lee un .desktop y devuelve (nombre, exec, icono) o None."""
    data = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            en_entry = False
            for line in f:
                line = line.strip()
                if line.startswith("["):
                    # Solo interesa [Desktop Entry]; las acciones
                    # adicionales traen su propio Name/Exec y pisarian
                    # los de la aplicacion.
                    en_entry = (line == "[Desktop Entry]")
                    continue
                if not en_entry or "=" not in line or line.startswith("#"):
                    continue
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip()
    except OSError:
        return None

    if data.get("Type") != "Application":
        return None
    if data.get("NoDisplay", "").lower() == "true":
        return None
    if data.get("Hidden", "").lower() == "true":
        return None

    nombre = data.get("Name[%s]" % lang) or data.get("Name")
    ejec = data.get("Exec")
    if not nombre or not ejec:
        return None

    for code in _FIELD_CODES:
        ejec = ejec.replace(code, "")
    ejec = " ".join(ejec.split())

    if data.get("Terminal", "").lower() == "true":
        ejec = "%s %s" % (C.CMD_TERMINAL, ejec)

    return (nombre, ejec, data.get("Icon", ""),
            (data.get("Keywords[%s]" % lang) or data.get("Keywords", "")))


def scan_apps():
    """Indice de aplicaciones instaladas.

    Si el mismo nombre de fichero aparece en varios directorios gana el
    primero: el spec dice que ~/.local tiene prioridad sobre /usr, que
    es como se sobreescribe un lanzador del sistema.
    """
    import locale as _loc
    lang = (_loc.getlocale(_loc.LC_MESSAGES)[0] or "en").split("_")[0]
    vistos = set()
    apps = []
    for d in APP_DIRS:
        try:
            nombres = sorted(os.listdir(d))
        except OSError:
            continue
        for n in nombres:
            if not n.endswith(".desktop") or n in vistos:
                continue
            vistos.add(n)
            r = _parse_desktop(os.path.join(d, n), lang)
            if r:
                apps.append(r)
    apps.sort(key=lambda a: a[0].lower())
    return apps


def match_apps(apps, query, limit=6):
    """Filtra y ordena por relevancia.

    Tres niveles, de mejor a peor: el nombre EMPIEZA por lo escrito,
    alguna palabra del nombre empieza por ello, o aparece suelto por el
    medio (incluidas las palabras clave del .desktop). Sin esto,
    escribir "fire" sacaria antes cualquier cosa que contuviese esas
    letras que el propio Firefox.
    """
    q = query.strip().lower()
    if not q:
        return apps[:limit]
    out = []
    for app in apps:
        nombre = app[0].lower()
        if nombre.startswith(q):
            score = 0
        elif any(w.startswith(q) for w in nombre.split()):
            score = 1
        elif q in nombre:
            score = 2
        elif q in app[3].lower():
            score = 3
        else:
            continue
        out.append((score, len(nombre), app))
    out.sort(key=lambda t: (t[0], t[1]))
    return [t[2] for t in out[:limit]]


# ------------------------------------------------- frecuencia de uso

FREC_PATH = os.path.expanduser("~/.cache/island/frecency.json")
_frec = None


def frec_load():
    global _frec
    if _frec is None:
        try:
            with open(FREC_PATH) as f:
                _frec = json.load(f)
        except (OSError, ValueError):
            _frec = {}
    return _frec


def frec_bump(key):
    d = frec_load()
    e = d.setdefault(key, {"n": 0, "t": 0})
    e["n"] += 1
    e["t"] = int(time.time())
    try:
        os.makedirs(os.path.dirname(FREC_PATH), exist_ok=True)
        tmp = FREC_PATH + ".part"
        with open(tmp, "w") as f:
            json.dump(d, f)
        os.replace(tmp, FREC_PATH)
    except OSError:
        pass


def frec_score(key):
    """Cuantas veces se ha abierto, pesado por lo reciente que sea.

    Solo el contador dejaria arriba para siempre algo que usaste mucho
    hace medio ano; solo la fecha haria que lo ultimo abierto ganase
    siempre. El producto equilibra las dos cosas.
    """
    e = frec_load().get(key)
    if not e:
        return 0.0
    dias = max(0.0, (time.time() - e.get("t", 0)) / 86400.0)
    return e.get("n", 0) * (1.0 + 3.0 / (1.0 + dias))


# ---------------------------------------------------------- calculadora

_CALC_OK = None


def calc_eval(expr):
    """Evalua una expresion aritmetica, o None si no lo es.

    Se recorre el arbol de sintaxis y se rechaza cualquier nodo que no
    sea aritmetica pura. Usar eval() a secas sobre lo que se teclea en
    un lanzador seria ejecutar codigo arbitrario.
    """
    global _CALC_OK
    import ast as _ast
    if _CALC_OK is None:
        _CALC_OK = (_ast.Expression, _ast.BinOp, _ast.UnaryOp, _ast.Constant,
                    _ast.Add, _ast.Sub, _ast.Mult, _ast.Div, _ast.FloorDiv,
                    _ast.Mod, _ast.Pow, _ast.USub, _ast.UAdd, _ast.Paren
                    if hasattr(_ast, "Paren") else _ast.Expression)
    e = expr.strip().replace(",", ".").replace("x", "*").replace("^", "**")
    if not e or not any(c.isdigit() for c in e):
        return None
    if not all(c in "0123456789+-*/%.()** " for c in e):
        return None
    try:
        arbol = _ast.parse(e, mode="eval")
        for n in _ast.walk(arbol):
            if not isinstance(n, _CALC_OK):
                return None
        v = eval(compile(arbol, "<calc>", "eval"), {"__builtins__": {}}, {})
    except Exception:
        return None
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            return None
        # Sin decimales inutiles: 4.0 se muestra como 4.
        return ("%.10g" % v)
    return str(v)


def copy_clipboard(texto):
    try:
        p = subprocess.Popen(["xclip", "-selection", "clipboard"],
                             stdin=subprocess.PIPE)
        p.communicate(texto.encode(), timeout=2)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


# ------------------------------------------------------------ ventanas

def list_windows():
    """Ventanas abiertas: [(id, titulo, clase)].

    Se consulta solo al abrir el lanzador, no periodicamente: son ~10 ms
    con tres ventanas y no tiene sentido pagarlos en reposo.
    """
    out = []
    r = _run_q(["bspc", "query", "-N", "-n", ".window"])
    for wid in (r or "").split():
        titulo = _xprop(wid, "_NET_WM_NAME") or _xprop(wid, "WM_NAME")
        clase = (_xprop(wid, "WM_CLASS") or "").split('", "')[-1].strip('" ')
        if titulo:
            out.append((wid, titulo, clase))
    return out


def _run_q(args):
    try:
        return subprocess.run(args, capture_output=True, text=True,
                              timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _xprop(wid, prop):
    s = _run_q(["xprop", "-id", wid, prop])
    if "=" not in s:
        return ""
    return s.split("=", 1)[1].strip().strip('"')

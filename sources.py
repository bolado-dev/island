# -*- coding: utf-8 -*-
"""Fuentes de datos y de eventos.

Nada aqui bloquea el hilo de GTK: bspwm y el FIFO entran por watchers de
GLib, y lo que hay que sondear (bateria, red) se lee de sysfs cada pocos
segundos. Si el dibujado se bloquease, la animacion daria tirones, que
es justo lo que se intenta evitar.
"""
import ctypes
import os
import json
import re
import time
import subprocess
import glob
import hashlib
import shutil
import socket
import stat
from collections import deque
import fcntl
import struct
import threading
import unicodedata
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
        self._vuelta = 0
        self.refresh(volumen=True)

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

    def refresh(self, volumen=None):
        """El estado del sistema. 'volumen' fuerza preguntarselo a
        PipeWire; por defecto solo se hace de vez en cuando.

        `wpctl get-volume` son 19,6 ms de fork+exec, y el volumen casi
        nunca cambia a nuestras espaldas: cuando lo tocas tu llega el
        evento de la tecla, y al abrir el panel se pregunta a proposito.
        Lo de aqui es la red de seguridad para cuando lo cambia otro
        programa, y para eso basta con mirar de tarde en tarde.
        """
        self._vuelta += 1
        if volumen is None:
            volumen = (self._vuelta % 4 == 1)
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
        if not volumen:
            return True
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


class Carga(object):
    """Carga de la maquina: CPU, memoria, temperaturas y consumo.

    Todo sale de /proc y /sys. NO se llama a `sensors`: lm-sensors lee
    exactamente esos mismos ficheros, asi que invocarlo seria un
    fork+exec cada dos segundos para que otro programa haga el mismo
    open() y encima devuelva texto traducido que habria que volver a
    parsear. Lo unico que aporta lm-sensors es `sensors-detect`, que
    carga modulos del kernel para chips raros; si ese paso hace falta
    en tu maquina, lo que aparece despues son mas ficheros aqui.

    Guarda historial para la grafica. Con 90 muestras a uno cada dos
    segundos son los ultimos tres minutos.
    """

    # Etiquetas de hwmon que interesan, por nombre del chip. El resto
    # se ignora: acpitz en esta maquina devuelve 0 grados siempre, y
    # una lectura falsa es peor que ninguna.
    CHIPS = (("coretemp", "CPU"), ("k10temp", "CPU"), ("zenpower", "CPU"),
             ("nvme", "Disco"), ("amdgpu", "GPU"), ("nouveau", "GPU"),
             ("iwlwifi", "Wifi"))

    def __init__(self, al_muestrear=None, muestras=90, cada=2):
        self.al_muestrear = al_muestrear
        self.cada = cada
        # Vacio, no relleno de ceros: con ceros, recien arrancada la
        # isla, la grafica diria que la maquina llevaba tres minutos
        # sin hacer nada. Lo que hay se reparte a lo ancho y la
        # resolucion va creciendo sola.
        self.hist = deque(maxlen=muestras)
        self.nucleos = []          # % por nucleo, en orden
        self.cpu = 0.0             # % total
        self.mem_usada = 0         # bytes
        self.mem_total = 0
        self.temps = {}            # "CPU" -> grados
        self.vatios = None
        self.ghz = 0.0
        self.carga1 = 0.0          # load average de un minuto
        self.swap = (0, 0)         # usado, total
        self.red = (0.0, 0.0)      # bytes/s bajando, subiendo
        self.disco = (0.0, 0.0)    # bytes/s leyendo, escribiendo
        self.disco_uso = (0, 0)    # usado, total del sistema de ficheros
        self.arriba = 0.0          # segundos encendida
        self.red_hist = deque(maxlen=muestras)
        self.disco_hist = deque(maxlen=muestras)
        self._red_prev = None
        self._disco_prev = None
        self._t_prev = None
        self._iface = self._busca_iface()
        self._disco_dev = self._busca_disco()
        self._prev = {}
        self._sondas, self._lentas = self._busca_sondas()
        self._freqs = glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/"
                                "scaling_cur_freq")
        self._bat = "/sys/class/power_supply/BAT0/power_now"
        self._vuelta = 0
        self._ligero = None
        self._rapido = False
        self.refresh(todo=True)
        self._id = GLib.timeout_add_seconds(cada, self._tick)

    # ------------------------------------------------------ que mirar

    @staticmethod
    def _busca_iface():
        """La interfaz por la que sale el trafico.

        Se prefiere la de config, y si no esta levantada se coge la
        primera fisica que lo este. 'lo' nunca: contarse a si mismo no
        dice nada, y las de tunel tampoco, que su trafico ya va contado
        por debajo en la fisica.
        """
        candidatas = [C.IFACE_WIFI] + sorted(
            os.path.basename(x) for x in glob.glob("/sys/class/net/*"))
        for n in candidatas:
            if not n or n == "lo" or n.startswith(("tun", "tailscale",
                                                   "docker", "veth", "br-")):
                continue
            if _read("/sys/class/net/%s/operstate" % n) == "up":
                return n
        return C.IFACE_WIFI

    @staticmethod
    def _busca_disco():
        """El disco del sistema, el que tiene la raiz.

        Se mira de que dispositivo cuelga "/" y se sube hasta el disco
        entero: lo que interesa es cuanto se mueve el cacharro, no una
        particion suelta.
        """
        try:
            dev = os.stat("/").st_dev
            mayor, menor = os.major(dev), os.minor(dev)
            ruta = "/sys/dev/block/%d:%d" % (mayor, menor)
            real = os.path.realpath(ruta)
            nombre = os.path.basename(real)
            # De "nvme0n1p2" al disco "nvme0n1"; de "sda1" a "sda".
            padre = os.path.basename(os.path.dirname(real))
            if padre and padre != "block" and nombre.startswith(padre):
                return padre
            return nombre
        except OSError:
            return ""

    # ------------------------------------------------------- sondas

    def _busca_sondas(self):
        """Donde esta cada temperatura, buscado UNA vez.

        Los numeros de hwmon bailan entre arranques --hwmon6 hoy puede
        ser hwmon2 manana-, asi que se localizan por el nombre del chip
        y no por la ruta.
        """
        sondas = {}
        for d in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
            nombre = _read(os.path.join(d, "name"))
            for clave, titulo in self.CHIPS:
                if not nombre.startswith(clave):
                    continue
                if titulo in sondas:
                    break
                sondas[titulo] = self._mejor_temp(d)
                break
        sondas = dict((k, v) for k, v in sondas.items() if v)

        # Cuales son CARAS, medido y no supuesto. No todas las sondas
        # cuestan lo mismo: leer la del procesador son 0,07 ms porque
        # el kernel ya la tiene, y la del NVMe 6,2 ms porque cada
        # lectura manda un comando al disco. A una muestra cada dos
        # segundos eso es despertar al disco 43.000 veces al dia para
        # un numero que cambia despacio.
        lentas = set()
        for titulo, ruta in sondas.items():
            t0 = time.monotonic()
            _read(ruta)
            if (time.monotonic() - t0) > 0.002:
                lentas.add(titulo)
        return sondas, lentas

    @staticmethod
    def _mejor_temp(d):
        """De un chip con varias sondas, la que resume.

        En un Intel moderno hay una por nucleo y una de paquete: la de
        paquete es la que vale, porque es la mas alta y la que dice si
        la maquina esta pasandolo mal. En un NVMe, "Composite".
        """
        mejor = None
        for f in sorted(glob.glob(os.path.join(d, "temp*_input"))):
            etiqueta = _read(f[:-6] + "_label").lower()
            if "package" in etiqueta or "composite" in etiqueta or \
                    "tctl" in etiqueta or "edge" in etiqueta:
                return f
            if mejor is None:
                mejor = f
        return mejor

    # ------------------------------------------------------ muestreo

    def _tick(self):
        self.refresh()
        if self.al_muestrear:
            self.al_muestrear(False)
        return True

    def _tick_ligero(self):
        """Solo el reparto de /proc/stat: 0,02 ms.

        Mientras se mira el panel hace falta un valor nuevo a menudo o
        las barras van a saltos de un segundo, pero no hace falta
        volver a preguntar por las temperaturas ni por la frecuencia,
        que es lo que cuesta. Esto es barato de verdad: a seis veces
        por segundo son 0,12 ms por segundo de reloj.
        """
        self._cpu(largo=False)
        if self.al_muestrear:
            self.al_muestrear(True)
        return True

    def refresh(self, todo=False):
        self._vuelta += 1
        # Las sondas caras, una de cada diez vueltas: la temperatura de
        # un disco no cambia en dos segundos, y asi la muestra normal
        # baja de 8 ms a menos de uno.
        lentas = todo or (self._vuelta % 10 == 1)
        self._cpu()
        self._memoria()
        for titulo, ruta in self._sondas.items():
            if titulo in self._lentas and not lentas:
                continue
            v = _read(ruta)
            if v.lstrip("-").isdigit():
                self.temps[titulo] = int(v) / 1000.0
        v = _read(self._bat)
        self.vatios = int(v) / 1e6 if v.isdigit() else None
        self._trafico()
        self._espacio()
        try:
            self.carga1 = float(_read("/proc/loadavg").split()[0])
        except (ValueError, IndexError):
            pass

    def _cpu(self, largo=True):
        """Uso por nucleo a partir de /proc/stat.

        Un porcentaje de CPU solo existe entre DOS lecturas: lo que hay
        en /proc/stat son contadores desde el arranque, asi que se
        guarda la anterior y se mira el reparto del tiempo transcurrido.
        """
        nucleos = []
        try:
            with open("/proc/stat") as f:
                for linea in f:
                    if not linea.startswith("cpu"):
                        break
                    partes = linea.split()
                    cual = partes[0]
                    nums = [int(x) for x in partes[1:11]]
                    total, ocio = sum(nums), nums[3] + nums[4]
                    antes = self._prev.get(cual)
                    self._prev[cual] = (total, ocio)
                    if antes is None or total <= antes[0]:
                        pct = 0.0
                    else:
                        dt, docio = total - antes[0], ocio - antes[1]
                        pct = max(0.0, min(100.0, 100.0 * (dt - docio) / dt))
                    if cual == "cpu":
                        self.cpu = pct
                        if largo:
                            # El historial va al ritmo lento: si
                            # tambien se alimentase del muestreo
                            # ligero, los tres minutos de grafica se
                            # quedarian en quince segundos.
                            self.hist.append(pct / 100.0)
                    else:
                        nucleos.append(pct)
        except OSError:
            return
        if nucleos:
            self.nucleos = nucleos

        if not largo:
            return

        # La frecuencia media, para saber si esta acelerada o dormida.
        # La lista de ficheros se busco una vez: el glob cuesta tanto
        # como leerlos todos.
        freqs = []
        for f in self._freqs:
            v = _read(f)
            if v.isdigit():
                freqs.append(int(v))
        self.ghz = (sum(freqs) / len(freqs) / 1e6) if freqs else 0.0

    def _trafico(self):
        """Red y disco en bytes por segundo.

        Son contadores desde el arranque, como /proc/stat: lo que se
        enseña es la diferencia entre dos lecturas partida por el tiempo
        que ha pasado de verdad, no por el periodo nominal del
        temporizador --que no se cumple si la maquina esta ocupada, y
        entonces las tasas saldrian infladas-.
        """
        ahora = time.monotonic()
        dt = (ahora - self._t_prev) if self._t_prev else 0.0
        self._t_prev = ahora

        base = "/sys/class/net/%s/statistics/" % self._iface
        rx, tx = _read(base + "rx_bytes"), _read(base + "tx_bytes")
        if rx.isdigit() and tx.isdigit():
            par = (int(rx), int(tx))
            if self._red_prev and dt > 0.05:
                self.red = (max(0.0, (par[0] - self._red_prev[0]) / dt),
                            max(0.0, (par[1] - self._red_prev[1]) / dt))
                self.red_hist.append(self.red[0] + self.red[1])
            self._red_prev = par

        if self._disco_dev:
            try:
                with open("/proc/diskstats") as f:
                    for linea in f:
                        campos = linea.split()
                        if len(campos) > 9 and campos[2] == self._disco_dev:
                            # Sectores de 512 bytes: leidos (campo 5) y
                            # escritos (campo 9).
                            par = (int(campos[5]) * 512,
                                   int(campos[9]) * 512)
                            if self._disco_prev and dt > 0.05:
                                self.disco = (
                                    max(0.0, (par[0] - self._disco_prev[0]) / dt),
                                    max(0.0, (par[1] - self._disco_prev[1]) / dt))
                                self.disco_hist.append(
                                    self.disco[0] + self.disco[1])
                            self._disco_prev = par
                            break
            except (OSError, ValueError):
                pass

    def _espacio(self):
        try:
            st = os.statvfs("/")
            total = st.f_blocks * st.f_frsize
            libre = st.f_bavail * st.f_frsize
            self.disco_uso = (max(0, total - libre), total)
        except OSError:
            pass
        try:
            self.arriba = float(_read("/proc/uptime").split()[0])
        except (ValueError, IndexError):
            pass

    def _memoria(self):
        total = disponible = 0
        try:
            with open("/proc/meminfo") as f:
                for linea in f:
                    if linea.startswith("MemTotal:"):
                        total = int(linea.split()[1]) * 1024
                    elif linea.startswith("MemAvailable:"):
                        disponible = int(linea.split()[1]) * 1024
                        break
        except OSError:
            return
        self.mem_total = total
        self.mem_usada = max(0, total - disponible)
        st = sf = 0
        try:
            with open("/proc/meminfo") as f:
                for linea in f:
                    if linea.startswith("SwapTotal:"):
                        st = int(linea.split()[1]) * 1024
                    elif linea.startswith("SwapFree:"):
                        sf = int(linea.split()[1]) * 1024
                        break
        except OSError:
            pass
        self.swap = (max(0, st - sf), st)

    # -------------------------------------------------------- ayudas

    @property
    def mem_frac(self):
        return (self.mem_usada / self.mem_total) if self.mem_total else 0.0

    @property
    def temp_cpu(self):
        return self.temps.get("CPU")

    def acelera(self, rapido, ms=150):
        """Mientras se mira el panel, dos ritmos a la vez.

        El lento sigue siendo el de siempre --temperaturas, frecuencia,
        memoria e historial-, y encima se añade uno ligero que solo
        reparte /proc/stat. Asi el numero y las barras se mueven como
        algo vivo sin volver a pagar lo caro seis veces por segundo.
        """
        if bool(getattr(self, "_rapido", False)) == bool(rapido):
            return
        self._rapido = bool(rapido)
        if self._ligero is not None:
            GLib.source_remove(self._ligero)
            self._ligero = None
        if rapido:
            self._ligero = GLib.timeout_add(ms, self._tick_ligero)


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


# ----------------------------------------------------------------- x

_X = {"dpy": None, "lib": None}


def _x11():
    """Conexion minima con el servidor X, por ctypes.

    Sin python-xlib y sin lanzar `xprop` o `xinput` cada segundo: es la
    misma idea que leer la IP por ioctl en vez de llamar a `ip`. Si no
    hay sesion grafica, todo lo de aqui devuelve vacio y nadie se
    entera.
    """
    if _X["dpy"] is None:
        try:
            lib = ctypes.CDLL("libX11.so.6")
            lib.XOpenDisplay.restype = ctypes.c_void_p
            lib.XInternAtom.restype = ctypes.c_ulong
            lib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                        ctypes.c_int]
            lib.XGetWindowProperty.argtypes = [
                ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
                ctypes.c_long, ctypes.c_long, ctypes.c_int, ctypes.c_ulong,
                ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
                ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte))]
            dpy = lib.XOpenDisplay(None)
            _X["lib"], _X["dpy"] = lib, (dpy or False)
        except OSError:
            _X["dpy"] = False
    return _X["lib"], _X["dpy"]


def tecla_pulsada(nombre):
    """True si esa tecla esta fisicamente pulsada ahora mismo (ver
    dictado.py, que la usa para saber cuando sueltas el push-to-talk)."""
    lib, dpy = _x11()
    if not dpy:
        return False
    sym = lib.XStringToKeysym(nombre.encode())
    if not sym:
        return False
    kc = lib.XKeysymToKeycode(ctypes.c_void_p(dpy), sym)
    if not kc:
        return False
    mapa = (ctypes.c_char * 32)()
    lib.XQueryKeymap(ctypes.c_void_p(dpy), mapa)
    return bool(mapa[kc >> 3][0] & (1 << (kc & 7)))


def _cardinales(win, nombre):
    """Lee una propiedad numerica de una ventana (o de la raiz).

    Vale para `_NET_CLIENT_LIST` (todas las ventanas) y para
    `_NET_WM_PID` (de quien es una). Las dos son lo mismo por dentro:
    una lista de enteros de 32 bits.
    """
    lib, dpy = _x11()
    if not dpy:
        return []
    prop = lib.XInternAtom(ctypes.c_void_p(dpy), nombre, 0)
    tipo = ctypes.c_ulong()
    fmt = ctypes.c_int()
    n = ctypes.c_ulong()
    resto = ctypes.c_ulong()
    datos = ctypes.POINTER(ctypes.c_ubyte)()
    r = lib.XGetWindowProperty(
        ctypes.c_void_p(dpy), win, prop, 0, 1024, 0, 0,
        ctypes.byref(tipo), ctypes.byref(fmt), ctypes.byref(n),
        ctypes.byref(resto), ctypes.byref(datos))
    if r != 0 or not datos:
        return []
    # format 32 son `long` en C, o sea 8 bytes en 64 bits: es la rareza
    # clasica de Xlib y la causa de la mitad de los lectores rotos.
    paso = 8 if fmt.value == 32 else max(1, fmt.value // 8)
    crudo = bytes(bytearray(datos[i] for i in range(n.value * paso)))
    lib.XFree(datos)
    return [int.from_bytes(crudo[i:i + paso], "little")
            for i in range(0, len(crudo), paso)]


def _raiz():
    lib, dpy = _x11()
    return lib.XDefaultRootWindow(ctypes.c_void_p(dpy)) if dpy else 0


def ventanas():
    """Todas las ventanas del escritorio, segun el propio servidor X."""
    lib, dpy = _x11()
    if not dpy:
        return []
    return _cardinales(_raiz(), b"_NET_CLIENT_LIST")


def titulo(wid):
    """Titulo de una ventana, leido directo del servidor X.

    Se prueba `_NET_WM_NAME` (UTF-8, lo que usa todo el mundo desde
    hace veinte años) y se cae a `WM_NAME` por si acaso. Devuelve "" si
    la ventana ya no existe, que es como se sabe que se cerro.
    """
    lib, dpy = _x11()
    if not dpy:
        return ""
    try:
        win = int(wid, 16) if isinstance(wid, str) else int(wid)
    except (TypeError, ValueError):
        return ""
    for nombre in (b"_NET_WM_NAME", b"WM_NAME"):
        prop = lib.XInternAtom(ctypes.c_void_p(dpy), nombre, 0)
        tipo = ctypes.c_ulong()
        fmt = ctypes.c_int()
        n = ctypes.c_ulong()
        resto = ctypes.c_ulong()
        datos = ctypes.POINTER(ctypes.c_ubyte)()
        r = lib.XGetWindowProperty(
            ctypes.c_void_p(dpy), win, prop, 0, 1024, 0, 0,
            ctypes.byref(tipo), ctypes.byref(fmt), ctypes.byref(n),
            ctypes.byref(resto), ctypes.byref(datos))
        if r == 0 and datos:
            crudo = bytes(bytearray(datos[i] for i in range(n.value)))
            lib.XFree(datos)
            if crudo:
                return crudo.decode("utf-8", "replace")
    return ""


# --------------------------------------------------------------- foco

# Las IA que se saben reconocer, por el nombre de su proceso. El valor
# es (slug del logo en icons/, nombre legible). Añadir otra es una linea
# aqui y un SVG al lado; si el SVG falta, se enseña el nombre y ya.
IAS = (
    ("claude", ("claude", "Claude")),
    ("codex",  ("codex",  "Codex")),
    ("gemini", ("gemini", "Gemini")),
)


def _ps_arbol():
    """Una foto de los procesos: (hijos por padre, nombre por pid).

    Se saca una vez y se consulta muchas: lanzar un `ps` por ventana
    para saber de quien es cada una seria cuatro procesos cada barrido.
    """
    try:
        salida = subprocess.run(["ps", "-eo", "pid=,ppid=,comm="],
                                capture_output=True, text=True,
                                timeout=2).stdout
    except Exception:
        return {}, {}
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
    return hijos, nombres


def _ia_en(pid, arbol=None):
    """Que IA cuelga de `pid`, el mismo o cualquier descendiente."""
    hijos, nombres = arbol if arbol is not None else _ps_arbol()
    pila, visto = [pid], set()
    while pila:
        p = pila.pop()
        if p in visto:
            continue
        visto.add(p)
        comm = nombres.get(p, "").lower()
        for clave, datos in IAS:
            if clave in comm:
                return datos
        pila.extend(hijos.get(p, []))
    return None


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
        return {"id": "", "clase": "", "app": "", "ia": ""}
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
    ia = _ia_en(pid) if pid else None
    app = ia[1] if ia else {
        "kitty": "Terminal", "google-chrome": "Chrome",
        "chromium": "Chromium"}.get(clase, clase)
    return {"id": wid, "clase": clase, "app": app,
            "ia": ia[0] if ia else ""}


class Foco(object):
    """Ventana enfocada, en vivo via 'bspc subscribe node_focus'.

    Existe para una sola cosa: que el notch pueda decir que el dictado
    esta disponible cuando miras una ventana de una IA. Por eso NO
    sondea: recorrer el arbol de procesos cada pocos segundos para un
    indicador que casi nunca cambia seria gastar bateria en nada. Se
    mira cuando el foco cambia, que es la unica vez que puede cambiar
    la respuesta.
    """
    def __init__(self, on_change):
        self.on_change = on_change
        self.info = {"id": "", "clase": "", "app": "", "ia": ""}
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
        antes = self.info.get("ia")
        self.refrescar()
        # Solo molesta a la isla si CAMBIA la respuesta: alt-tab entre
        # dos ventanas que no son de una IA no repinta nada.
        if self.info.get("ia") != antes:
            self.on_change()
        return True

    def refrescar(self):
        self.info = ventana_enfocada()

    @property
    def ia(self):
        """Slug de la IA enfocada ("claude", "gemini"...) o cadena vacia."""
        return self.info.get("ia") or ""

    @property
    def app(self):
        return self.info.get("app") or ""


# ------------------------------------------------------ portapapeles

class Portapapeles(object):
    """Lo ultimo que has copiado, para poder recuperarlo desde el
    lanzador.

    Esto SONDEA, y es la unica cosa de la isla que lo hace. X no avisa
    de un cambio de seleccion a quien no se registra con XFixes, y
    montar eso aqui significaba meter un segundo bucle de eventos de X
    dentro de una aplicacion GTK. Se midio lo que cuesta la alternativa
    tonta: `xclip -o` son unos 3 ms, asi que a uno cada tres segundos
    sale al 0,1% de un nucleo. Cuando moleste, ahi esta el camino bueno.

    No guarda nada en disco a proposito: por ahi pasan contraseñas.
    Lo que se copio se olvida al reiniciar la isla.
    """
    def __init__(self, maximo=20, cada=3, limite=4096):
        self.maximo, self.limite = maximo, limite
        self.items = []            # el mas reciente primero
        # Cuando se vio cada cosa. En un diccionario aparte y no en la
        # lista para no cambiarle la forma a quien ya la usa: el
        # lanzador espera cadenas y las sigue recibiendo.
        self.visto = {}
        # Lo fijado. En memoria como todo lo demas: fijar es decir "esto
        # lo voy a pegar varias veces", no "guardame esto para siempre",
        # y por el portapapeles pasan contrasenas. Lo que no se escribe
        # no se filtra.
        self.fijados = set()
        self._ultimo = None

        # Por AVISO, no sondeando. GTK ya tiene el portapapeles de X
        # abierto y emite "owner-change" cuando alguien copia: por
        # debajo es XFixes, o sea justo el camino bueno que decia el
        # comentario de arriba. Lo que se gana: el sondeo eran 6,7 ms de
        # `xclip` cada tres segundos --un proceso entero para leer un
        # texto que casi nunca ha cambiado- y ahora son cero hasta que
        # copias algo.
        #
        # Si GTK no estuviera disponible queda el sondeo de antes, que
        # es lo que hace funcionar esto en una sesion sin pantalla.
        self._clip = None
        try:
            from gi.repository import Gtk, Gdk
            self._clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            self._clip.connect("owner-change", self._cambio)
        except Exception:
            self._clip = None
        if self._clip is None and cada > 0:
            GLib.timeout_add_seconds(cada, self._tick)

    def _cambio(self, clip, _ev):
        """Alguien ha copiado algo. Se pide el texto SIN bloquear.

        wait_for_text() pararia la isla hasta que conteste quien copio
        --y quien copio puede ser un navegador ocupado-, asi que se
        pide con callback: mientras tanto se sigue dibujando.
        """
        try:
            clip.request_text(lambda _c, txt, _d: self._guarda(txt or ""), None)
        except Exception:
            pass

    def _tick(self):
        try:
            r = subprocess.run(["xclip", "-selection", "clipboard", "-o"],
                               capture_output=True, text=True, timeout=1)
        except Exception:
            return True
        self._guarda(r.stdout)
        return True

    def _guarda(self, txt):
        if not txt or not txt.strip() or len(txt) > self.limite:
            return
        if txt == self._ultimo:
            return
        self._ultimo = txt
        # Repetido: sube al principio en vez de duplicarse.
        self.items = [x for x in self.items if x != txt]
        self.items.insert(0, txt)
        self.visto[txt] = time.time()
        # Al recortar, lo fijado NO cuenta ni se cae: para eso se fija.
        # Si no, bastaban veinte copias para perder lo que habias
        # apartado a proposito.
        sueltos = [x for x in self.items if x not in self.fijados]
        for sobra in sueltos[self.maximo:]:
            self.items.remove(sobra)
            self.visto.pop(sobra, None)
        return

    def fijar(self, txt):
        """Fija o suelta. Devuelve si quedo fijado."""
        if txt in self.fijados:
            self.fijados.discard(txt)
            return False
        self.fijados.add(txt)
        return True

    def lista(self):
        """Lo fijado primero y lo demas por orden de copiado.

        El orden lo decide esto y no quien dibuja: asi el panel y el
        lanzador no pueden acabar ensenando ordenes distintos.
        """
        fij = [x for x in self.items if x in self.fijados]
        return fij + [x for x in self.items if x not in self.fijados]

    def borrar(self, txt):
        """Saca algo del historial. No toca el portapapeles del sistema:
        si lo que borras es justo lo ultimo copiado, sigue estando a un
        Ctrl+V; lo que se tira es el recuerdo, no la copia."""
        self.items = [x for x in self.items if x != txt]
        self.visto.pop(txt, None)
        self.fijados.discard(txt)
        if self._ultimo == txt:
            # Si no, al siguiente barrido lo ve igual que estaba y lo
            # vuelve a meter: habrias borrado algo que reaparece solo.
            self._ultimo = None

    def edad(self, txt):
        """Segundos desde que se copio, o None si no se sabe."""
        t = self.visto.get(txt)
        return None if t is None else max(0.0, time.time() - t)

    def busca(self, q, tope=3):
        ql = q.lower()
        return [x for x in self.lista() if ql in x.lower()][:tope]


# Tipos de cosa copiada. Un historial de portapapeles es una lista de
# cadenas sueltas y todas se parecen; saber de un vistazo que una es una
# URL, otra un comando y otra un color es la diferencia entre leerlas
# una a una y encontrar la que buscas.
#
# El orden importa: se devuelve el PRIMERO que casa, asi que lo mas
# especifico va arriba. Un color es tambien texto, y una ruta tambien.
_RE_COLOR  = re.compile(r"^#[0-9a-fA-F]{3,8}$|^rgba?\([\d\s.,%]+\)$")
_RE_URL    = re.compile(r"^(https?://|www\.)\S+$|^[\w.-]+\.[a-z]{2,}(/\S*)?$",
                        re.I)
_RE_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)
_RE_RUTA   = re.compile(r"^[~./][^\n]*$|^/[^\n]*$")
_RE_NUM    = re.compile(r"^-?[\d.,]+([eE][-+]?\d+)?$")
# Lo que delata a un comando. No se intenta adivinar por el nombre del
# programa (son miles): se mira la forma, que es lo que no cambia.
_RE_CMD    = re.compile(r"(^|\s)(sudo|git|npm|pip|apt|docker|systemctl|"
                        r"export|cd|ssh|curl|chmod|bspc|python3?)\s|"
                        r"[|$]|^\$\s|--?\w")


# Codigo, sin intentar adivinar el lenguaje: los signos que la prosa no
# usa y las palabras con las que empieza media linea de cualquier
# lenguaje. Falla con prosa llena de parentesis, y el precio de fallar
# es ensenar un parrafo en monoespaciada, que no rompe nada.
_RE_CODIGO = re.compile(
    r"[{};=()\[\]]|^\s*(def|class|import|from|const|let|var|function|"
    r"public|private|return|if|for|while|#!|<\w)", re.M)


def clip_tipo(txt):
    """Que clase de cosa es lo copiado: una clave corta."""
    una = txt.strip()
    if not una:
        return "texto"
    if "\n" in una.strip("\n"):
        # Varias lineas. Importa distinguir un parrafo de un trozo de
        # codigo: el parrafo se lee en proporcional y el codigo NO, que
        # es justo donde la l y el 1 se confunden.
        if _RE_CMD.search(una):
            return "cmd"
        return "codigo" if _RE_CODIGO.search(una) else "lineas"
    if _RE_COLOR.match(una):
        return "color"
    if _RE_CORREO.match(una):
        return "correo"
    if _RE_URL.match(una):
        return "url"
    if _RE_NUM.match(una):
        return "numero"
    if _RE_RUTA.match(una) and " " not in una:
        return "ruta"
    if _RE_CMD.search(una):
        return "cmd"
    return "texto"


def clip_color(txt):
    """El color de un #rrggbb, en 0..1, o None si no lo es."""
    h = txt.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) not in (6, 8):
        return None
    try:
        return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        return None


def clip_edad(seg):
    """'hace 2 min'. En cristiano y sin decimales: lo que se quiere
    saber es si es de ahora mismo o de hace rato."""
    if seg is None:
        return ""
    if seg < 45:
        return "ahora"
    if seg < 3600:
        return "hace %d min" % max(1, int(seg // 60))
    if seg < 86400:
        return "hace %d h" % int(seg // 3600)
    return "hace %d d" % int(seg // 86400)


# ----------------------------------------------------------- trabajo

# Caracteres con los que una CLI de IA marca "estoy trabajando" en el
# titulo del terminal: el girador. Claude Code usa los cuartos de
# circulo; se añaden los de puntos por si otra usa esos.
GIRADORES = "\u25d0\u25d3\u25d1\u25d2\u25f4\u25f7\u25f6\u25f5" \
            "\u280b\u2819\u2839\u2838\u283c\u2834\u2826\u2827\u2807\u280f"


class Trabajo(object):
    """Avisa cuando una IA termina en una ventana que NO estas mirando.

    La señal es el titulo del terminal: mientras trabaja lleva delante
    un girador, y al acabar desaparece. Vale para cualquier CLI que
    haga eso, sin configurarla.

    Por que no avisa con la ventana enfocada: porque entonces lo estas
    viendo. El aviso es para cuando te has ido a otra cosa.

    Por que no avisa de los trabajos cortos: una respuesta de tres
    segundos no necesita aviso, y avisar de todas convierte el notch en
    ruido.

    Y por que BARRE en vez de enterarse al cambiar el foco, que fue la
    primera version: la IA tarda un instante en arrancar dentro de la
    ventana nueva, asi que al llegarle el foco todavia no cuelga de
    ella ningun proceso que se llame claude. Esa version no registraba
    la ventana jamas. Comprobado con una ventana de mentira.
    """
    def __init__(self, on_fin, minimo=0.0, cada=2):
        self.on_fin = on_fin
        self.minimo = minimo
        self.cada = cada
        self.vistas = {}       # id de ventana -> {"ia", "app", "ocupado", "desde"}
        self._sin_ia = set()   # ventanas ya descartadas, para no repreguntar
        self._cuenta = 0
        GLib.timeout_add_seconds(1, self._tick)

    def _barrido(self):
        """Busca ventanas de IA entre las que NO se habian visto.

        El arbol de procesos solo se saca si hay alguna por mirar, y
        ahi esta todo el ahorro: `ps -eo pid,ppid,comm` cuesta 31 ms
        --lo mas caro de la isla con diferencia- y se estaba lanzando
        cada dos segundos aunque no hubiera cambiado ni una ventana,
        que es el 99% de las veces. Un escritorio con las mismas
        ventanas de hace un rato no tiene nada que resolver.

        Medido: 15,6 ms por segundo de reloj antes, 0,1 despues.
        """
        vents = ventanas()
        # Las descartadas que ya no estan se olvidan: si no, el conjunto
        # crece con cada ventana que se abre y se cierra, y un id que X
        # reutilice se quedaria marcado para siempre.
        self._sin_ia &= set(vents)
        nuevas = [w for w in vents
                  if w not in self.vistas and w not in self._sin_ia]
        if not nuevas:
            return
        arbol = _ps_arbol()
        for win in nuevas:
            pids = _cardinales(win, b"_NET_WM_PID")
            ia = _ia_en(pids[0], arbol) if pids else None
            if not ia:
                # Se apunta que esta no es de ninguna IA, o cada barrido
                # volveria a sacar el arbol de procesos por ella.
                self._sin_ia.add(win)
            if ia:
                # "ocupado" arranca sin saberse (None) y no en False: si
                # la ventana ya estaba trabajando cuando la descubrimos,
                # dar por hecho que no lo estaba hace que el siguiente
                # vistazo parezca el comienzo del trabajo y la duracion
                # salga mal. Y si no sabemos cuando empezo, no se dice.
                self.vistas[win] = {"ia": ia[0], "app": ia[1],
                                    "ocupado": None, "desde": None}

    def _tick(self):
        if self._cuenta % self.cada == 0:
            self._barrido()
        self._cuenta += 1
        if not self.vistas:
            return True

        activa = _cardinales(_raiz(), b"_NET_ACTIVE_WINDOW")
        enfocada = activa[0] if activa else 0
        ahora = time.monotonic()
        for win, est in list(self.vistas.items()):
            tit = titulo(win)
            if not tit:
                del self.vistas[win]        # la ventana ya no esta
                continue
            ocupado = tit[0] in GIRADORES
            if est["ocupado"] is None:
                # Primera vez que la vemos: si ya estaba trabajando, su
                # comienzo se lo perdimos y la duracion queda en None.
                est["desde"] = None if ocupado else 0.0
            elif ocupado and not est["ocupado"]:
                est["desde"] = ahora
            elif est["ocupado"] and not ocupado:
                tardo = (ahora - est["desde"]) if est["desde"] else None
                if (tardo is None or tardo >= self.minimo) and win != enfocada:
                    self.on_fin(est["ia"], est["app"], tardo)
            est["ocupado"] = ocupado
        return True


def _run_quieto(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=2).stdout.strip()
    except Exception:
        return ""


# -------------------------------------------------------------- micro

class Micro(object):
    """Quien esta capturando audio AHORA, via 'pw-mon'.

    Por eventos y no sondeando: pw-mon suelta el inventario entero al
    arrancar y despues solo lo que cambia, igual que 'bspc subscribe'.
    Preguntarle a wpctl cada dos segundos habria sido un proceso nuevo
    cada dos segundos para una respuesta que casi siempre es "nadie".

    Lo que se busca en su salida es `media.class = "Stream/Input/Audio"`,
    que es como PipeWire llama a un flujo que LEE del microfono. Los
    `Audio/Source` son el dispositivo en si y estan siempre ahi; no
    significan que nadie escuche.
    """
    def __init__(self, on_change):
        self.on_change = on_change
        self.capturando = {}       # id de nodo -> nombre del programa
        self.proc = None
        self._accion, self._id, self._nombre = "", None, ""
        self.start()

    def start(self):
        try:
            self.proc = subprocess.Popen(
                ["pw-mon"], stdout=subprocess.PIPE, text=True, bufsize=1)
        except OSError:
            return
        GLib.io_add_watch(self.proc.stdout, GLib.PRIORITY_DEFAULT,
                          GLib.IO_IN | GLib.IO_HUP, self._on_line)

    @property
    def abierto(self):
        return bool(self.capturando)

    @property
    def quien(self):
        return ", ".join(sorted(set(self.capturando.values())))

    def _on_line(self, src, cond):
        if cond & GLib.IO_HUP:
            return False
        linea = src.readline()
        if not linea:
            return False
        antes = self.abierto
        self._parse(linea.rstrip("\n"))
        if self.abierto != antes:
            self.on_change()
        return True

    def _parse(self, linea):
        # pw-mon dibuja un arbol: las lineas vienen con caracteres de
        # caja delante ("  |- |-- media.class = ..."), no con
        # tabulaciones, asi que hay que pelarlas antes de mirar nada.
        # Esto costo la primera version entera: el parser no casaba una
        # sola linea y el indicador no se encendia nunca.
        cruda = linea.rstrip()
        s = cruda.strip().lstrip("\u2502\u251c\u2514\u2500- \t")

        if cruda in ("added:", "changed:", "removed:"):
            self._accion = cruda[:-1]
            self._id = None
            self._nombre = ""
            return
        if s.startswith("id:"):
            try:
                self._id = int(s.split(":", 1)[1])
            except ValueError:
                self._id = None
            # Un "removed" trae el id y nada mas, asi que se atiende aqui.
            if self._accion == "removed" and self._id is not None:
                self.capturando.pop(self._id, None)
        elif "application.name" in s:
            self._nombre = s.split("=", 1)[-1].strip().strip('"')
        elif "node.name" in s and not self._nombre:
            self._nombre = s.split("=", 1)[-1].strip().strip('"')
        elif "media.class" in s and self._id is not None:
            # Se decide en cuanto se sabe, sin esperar a que el bloque
            # termine: los bloques no tienen marca de fin.
            if '"Stream/Input/Audio"' in s:
                # El dictado de la propia isla no cuenta: ya tiene su
                # tarjeta con la onda, y avisar ahi de que el microfono
                # esta abierto seria decir dos veces lo mismo.
                if self._nombre != "island-dictado":
                    self.capturando[self._id] = self._nombre or "algo"
            else:
                self.capturando.pop(self._id, None)


# --------------------------------------------------------------- fifo

# El canal por el que entra todo lo que no se puede sondear: dunst, el
# dictado, las capturas. Un FIFO y no un socket porque los que escriben
# son scripts de una linea, y "echo > fifo" es algo que sabe hacer
# cualquiera.
FIFO = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "island.fifo")


def enviar_evento(**campos):
    """Mete un evento en el FIFO de la isla.

    Lo usan los ayudantes que corren como proceso suelto (el dictado y
    las capturas) sin pasar por `island-send`: durante una grabacion
    esto se llama doce veces por segundo, y lanzar un interprete de
    Python por cada nivel costaria mas que grabar.

    Si la isla no esta escuchando, se descarta en silencio. Que el
    escritorio no tenga barra no es motivo para que falle una captura.
    """
    if not os.path.exists(FIFO):
        return False
    try:
        fd = os.open(FIFO, os.O_WRONLY | os.O_NONBLOCK)
        os.write(fd, (json.dumps(campos) + "\n").encode())
        os.close(fd)
        return True
    except OSError:
        return False


class Fifo(object):
    """Entrada de eventos externos: una linea JSON por evento.

    Se reabre despues de cada EOF. Un FIFO devuelve EOF en cuanto el
    ultimo escritor cierra, asi que sin reabrir el demonio solo
    atenderia al primer cliente y despues quedaria sordo.

    Y se vigila que el fichero abierto SIGA SIENDO el de la ruta. Esto
    paso de verdad: arrancando una segunda isla, la nueva borraba el
    FIFO y creaba otro, y la primera se quedaba leyendo un inodo
    huerfano --abierto y borrado-. Como en ese ya no escribia nadie,
    tampoco llegaba nunca el EOF que dispara la reapertura, asi que se
    quedaba sorda para siempre: super+d dejaba de hacer nada y no habia
    ni un error en el log.
    """
    def __init__(self, path, on_event):
        self.path = path
        self.on_event = on_event
        self.ch = None
        self._watch = None
        self._ino = None
        self._crea()
        self._open()
        GLib.timeout_add_seconds(5, self._vigila)

    def _crea(self):
        """El FIFO, sin borrarlo si ya existe.

        Antes se borraba y se creaba otro en cada arranque. Reusarlo
        evita dejar huerfano al que estuviera leyendo otro proceso, que
        es justo el caso de arriba.
        """
        try:
            if stat.S_ISFIFO(os.stat(self.path).st_mode):
                return
            os.unlink(self.path)
        except OSError:
            pass
        try:
            os.mkfifo(self.path, 0o600)
        except OSError:
            pass

    def _open(self):
        self._cierra()
        self._crea()
        fd = os.open(self.path, os.O_RDONLY | os.O_NONBLOCK)
        self._ino = os.fstat(fd).st_ino
        self.ch = GLib.IOChannel.unix_new(fd)
        self.ch.set_encoding(None)
        self.ch.set_buffered(False)
        self._buf = b""
        self._watch = GLib.io_add_watch(self.ch, GLib.PRIORITY_DEFAULT,
                                        GLib.IO_IN | GLib.IO_HUP, self._on_io)

    def _cierra(self):
        if self._watch is not None:
            GLib.source_remove(self._watch)
            self._watch = None
        if self.ch is not None:
            try:
                self.ch.shutdown(False)
            except Exception:
                pass
            self.ch = None

    def _vigila(self):
        """Comprueba que la ruta sigue apuntando a lo que tenemos abierto."""
        try:
            ino = os.stat(self.path).st_ino
        except OSError:
            ino = None
        if ino != self._ino:
            self._open()
        return True

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
            self._watch = None          # esta fuente se muere al devolver False
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
# Iconos ya resueltos. Con tope: la clave lleva la ruta, y Chrome
# escribe el icono de CADA notificacion web en un temporal distinto, asi
# que sin limite la cache crece una entrada por notificacion recibida y
# no vuelve a acertar ninguna.
_icon_cache = {}
_ICON_MAX = 64


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

    if len(_icon_cache) >= _ICON_MAX:
        _icon_cache.clear()
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


def sin_origen(cuerpo, dominio):
    """Quita del cuerpo la linea del sitio de origen.

    Chrome mete el origen DENTRO del cuerpo de toda notificacion web:
    lo que llega es "web.whatsapp.com", una linea en blanco y, al
    final, el mensaje. Al pintarlo todo seguido, la mitad de la linea
    util se la comia un dato que ya dicen el nombre y el icono de la
    tarjeta.

    Si al quitarlo no queda nada --notificaciones que SOLO traen el
    origen- se devuelve lo que habia: mas vale repetir el sitio que
    dejar la tarjeta muda.
    """
    if not cuerpo or not dominio:
        return cuerpo
    d = dominio.rstrip("/")
    formas = []
    for esquema in ("", "http://", "https://"):
        formas += [esquema + d, esquema + d + "/"]
    bajas = {f.lower() for f in formas}

    # Por lineas, que es como lo manda Chrome...
    quedan = [l.strip() for l in cuerpo.split("\n")]
    quedan = [l for l in quedan if l and l.lower() not in bajas]
    limpio = "\n".join(quedan)

    # ...y por delante, que es como queda cuando alguien ya ha juntado
    # las lineas en una sola. sanitize() colapsa los saltos antes de
    # que esto llegue a mirarlos, asi que hacen falta las dos formas.
    for f in sorted(formas, key=len, reverse=True):
        if limpio.lower().startswith(f.lower()):
            sig = limpio[len(f):len(f) + 1]
            if sig and (sig.isalnum() or sig in "._-"):
                continue      # "web.whatsapp.com.mx": es otro dominio
            resto = limpio[len(f):].lstrip(" \u00b7-\u2013\u2014:")
            if resto:
                limpio = resto
            break
    return limpio or cuerpo


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


# ------------------------------------------------------------ miniaturas

_thumb_cache = {}


# El color de un icono, para el resplandor del notch. Se cachea POR
# PIXBUF y guardando el propio pixbuf: la clave es su id(), y sin
# conservar una referencia Python podria reutilizar ese id para otro
# objeto y devolver el color de un icono distinto.
_color_cache = {}
_COLOR_MAX = 48


def color_dominante(pb, respaldo=None):
    """El color con el que brilla un icono.

    No es la media de sus pixeles: la media de un logo de Discord sobre
    fondo blanco es gris claro, y un resplandor gris no es un
    resplandor. Se pesa cada pixel por lo SATURADO que esta, que es lo
    que de verdad identifica a una marca, y se descartan los grises y lo
    casi negro.

    Y al final se sube el color a un tono vivo (saturacion y brillo
    minimos). Lo que se pinta no es el icono, es la luz que echaria: una
    luz apagada no se lee como luz, se lee como suciedad en la pantalla.
    """
    if pb is None:
        return respaldo
    clave = id(pb)
    hit = _color_cache.get(clave)
    if hit is not None:
        return hit[1]

    try:
        # 16x16 basta y de sobra: lo que se busca es el tono, no el
        # dibujo. Escalar primero convierte el bucle en 256 vueltas
        # pase lo que pase, venga un favicon de 16 o una caratula de
        # 600.
        chico = pb.scale_simple(16, 16, GdkPixbuf.InterpType.BILINEAR)
        if chico is None:
            return respaldo
        datos = chico.get_pixels()
        canales = chico.get_n_channels()
        fila = chico.get_rowstride()
        alto, ancho = chico.get_height(), chico.get_width()
    except Exception:
        return respaldo

    import colorsys
    sr = sg = sb = peso = 0.0
    mr = mg = mb = mpeso = 0.0
    for y in range(alto):
        base = y * fila
        for x in range(ancho):
            o = base + x * canales
            r, g, b = datos[o] / 255.0, datos[o + 1] / 255.0, datos[o + 2] / 255.0
            a = datos[o + 3] / 255.0 if canales == 4 else 1.0
            if a < 0.5:
                continue
            h, l, sat = colorsys.rgb_to_hls(r, g, b)
            mr += r * a; mg += g * a; mb += b * a; mpeso += a
            if l < 0.12 or l > 0.95 or sat < 0.18:
                continue        # negro, blanco o gris: no dicen el color
            w = a * sat
            sr += r * w; sg += g * w; sb += b * w; peso += w

    if peso > 0.0:
        r, g, b = sr / peso, sg / peso, sb / peso
    elif mpeso > 0.0:
        # Un logo en blanco y negro (bastantes lo son). Su media sirve
        # para no dejarlo sin brillo, pero ya se sabe que saldra gris y
        # el ajuste de abajo lo levanta.
        r, g, b = mr / mpeso, mg / mpeso, mb / mpeso
    else:
        return respaldo

    h, l, sat = colorsys.rgb_to_hls(r, g, b)
    col = colorsys.hls_to_rgb(h, min(0.72, max(0.58, l)), max(0.62, sat))
    if len(_color_cache) >= _COLOR_MAX:
        _color_cache.clear()
    _color_cache[clave] = (pb, col)
    return col


def load_thumb(ruta, alto):
    """Miniatura escalada a ese alto, cacheada por fichero y fecha.

    La escala la hace GdkPixbuf una vez y no cairo en cada fotograma: a
    sesenta por segundo, volver a muestrear la misma imagen es trabajo
    tirado y encima con peor filtro.
    """
    if not ruta:
        return None
    try:
        mt = os.path.getmtime(ruta)
    except OSError:
        return None
    clave = (ruta, mt, alto)
    if clave in _thumb_cache:
        return _thumb_cache[clave]
    try:
        pb = GdkPixbuf.Pixbuf.new_from_file(ruta)
        if pb.get_height() != alto:
            escala = alto / float(pb.get_height())
            pb = pb.scale_simple(max(1, int(pb.get_width() * escala)), alto,
                                 GdkPixbuf.InterpType.BILINEAR)
    except Exception:
        return None
    # Una sola: la isla ensena la ultima captura, no un album.
    _thumb_cache.clear()
    _thumb_cache[clave] = pb
    return pb


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


# -------------------------------------------------------------- emoji

# Los nombres de grupo del fichero de Unicode, en castellano. El orden
# lo decide el fichero (es el de CLDR, pensado justo para paletas de
# teclado), asi que aqui solo se traduce.
GRUPOS_ES = {
    "Smileys & Emotion":  "Caras y emociones",
    "People & Body":      "Gente y cuerpo",
    "Animals & Nature":   "Animales y naturaleza",
    "Food & Drink":       "Comida y bebida",
    "Travel & Places":    "Viajes y lugares",
    "Activities":         "Actividades",
    "Objects":            "Objetos",
    "Symbols":            "Simbolos",
    "Flags":              "Banderas",
}

# Modificadores de tono de piel (U+1F3FB..U+1F3FF).
_TONOS = frozenset(range(0x1F3FB, 0x1F400))

_emoji_idx = None
_emoji_lock = threading.Lock()


def sin_tildes(s):
    return "".join(c for c in unicodedata.normalize("NFD", s.lower())
                   if not unicodedata.combining(c))


def _emoji_es():
    """Nombres y claves en castellano, si fetch-icons.sh los bajo."""
    try:
        with open(C.EMOJI_ES, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _emoji_parse():
    """Lee emoji-test.txt y devuelve [(char, nombre, grupo, buscable)].

    Se descartan tres cosas, y las tres por el mismo motivo: en una
    cuadricula estorban mas de lo que aportan.

      - Las variantes que no son "fully-qualified", que son la misma
        cosa escrita sin el selector de presentacion.
      - El grupo "Component": tonos de piel y tipos de pelo sueltos, que
        no son emoji que nadie quiera insertar.
      - Las variantes de tono de piel. Multiplican por seis cada emoji
        de persona y dejarian la rejilla llena de la misma mano repetida;
        pasan de 3947 a 1914.
    """
    try:
        texto = open(C.EMOJI_DATA, encoding="utf-8").read()
    except OSError:
        return []

    es = _emoji_es()
    fuera = []
    grupo = ""
    for ln in texto.splitlines():
        if ln.startswith("# group:"):
            grupo = ln.split(":", 1)[1].strip()
            continue
        if ln.startswith("#") or ";" not in ln:
            continue
        cps, resto = ln.split(";", 1)
        if "fully-qualified" not in resto or grupo == "Component":
            continue
        try:
            puntos = [int(c, 16) for c in cps.split()]
        except ValueError:
            continue
        if any(p in _TONOS for p in puntos):
            continue
        ch = "".join(chr(p) for p in puntos)

        # El nombre en ingles va detras del propio emoji y de su version
        # ("# 😀 E1.0 grinning face").
        tras = resto.split("#", 1)[-1].strip()
        en = tras.split(" ", 2)[-1].strip() if " " in tras else tras

        # CLDR guarda las claves SIN los selectores de presentacion.
        clave = ch.replace("️", "")
        nom_es, claves_es = es.get(clave, ("", ""))
        nombre = nom_es or en
        # Se busca por todo: nombre en castellano, sus sinonimos y el
        # nombre en ingles. Lo ultimo no es relleno; media jerga de
        # emoji se dice en ingles, y asi "fire" encuentra el fuego
        # aunque el nombre que se vea sea "fuego".
        buscable = sin_tildes(" ".join((nombre, claves_es, en)))
        fuera.append((ch, nombre, GRUPOS_ES.get(grupo, grupo), buscable))
    return fuera


def emoji_index():
    """La lista entera, construida una vez y cacheada.

    Son ~160 ms: 7 de leer el fichero y el resto de preguntarle a la
    fuente cual sabe dibujar. Se paga en un hilo al arrancar
    (emoji_precarga) para que abrir el selector no espere nunca.
    """
    global _emoji_idx
    with _emoji_lock:
        if _emoji_idx is None:
            import render
            crudo = _emoji_parse()
            _emoji_idx = render.emoji_soportados(crudo)
        return _emoji_idx


def emoji_precarga():
    """Construye el indice en segundo plano, sin estorbar al dibujado."""
    threading.Thread(target=emoji_index, daemon=True).start()


def emoji_buscar(q, limite=200):
    """Los emoji que casan con lo escrito, mejor primero.

    Sin busqueda no se devuelve la lista en orden de uso, solo los mas
    usados DELANTE: el orden de Unicode agrupa por tema (caras, gente,
    animales...) y perderlo por una ordenacion global dejaria la
    cuadricula sin ninguna estructura que seguir con la vista.
    """
    idx = emoji_index()
    q = sin_tildes(q.strip())
    if not q:
        # Los usados van delante, con su propia etiqueta: asi el salto
        # entre grupos del teclado (tabulador) los trata como un grupo
        # mas y la primera pulsacion cae justo al empezar la lista de
        # verdad. Diez son una fila de la rejilla.
        usados = sorted((e for e in idx if frec_score("emoji:" + e[0]) > 0),
                        key=lambda e: -frec_score("emoji:" + e[0]))[:10]
        recientes = [(e[0], e[1], "Recientes", e[3]) for e in usados]
        vistos = {e[0] for e in recientes}
        return recientes + [e for e in idx if e[0] not in vistos]

    out = []
    for e in idx:
        texto = e[3]
        pos = texto.find(q)
        if pos < 0:
            continue
        # Un nombre que EMPIEZA por lo escrito va antes que uno que lo
        # lleva en medio, y un sinonimo despues de los dos: buscando
        # "cara" lo que se quiere es la cara, no "mascara".
        if texto.startswith(q):
            rango = 0
        elif pos == 0 or texto[pos - 1] == " ":
            rango = 1
        else:
            rango = 2
        out.append((rango, -frec_score("emoji:" + e[0]), e))
    out.sort(key=lambda t: (t[0], t[1]))
    return [t[2] for t in out[:limite]]


# ------------------------------------------------------------- pegado

# Terminales que usan Ctrl+Shift+V en vez de Ctrl+V.
TERMINALES = frozenset((
    "kitty", "alacritty", "xterm", "urxvt", "st", "foot",
    "gnome-terminal", "konsole", "xfce4-terminal", "terminator",
    "wezterm", "tilix",
))


def _traza_pegar(msg):
    """Con ISLAND_DEBUG, apunta como fue el pegado.

    El que pega es un hilo sin terminal a la que quejarse, y sin esto no
    hay forma de saber si un emoji que no aparecio se quedo en el
    portapapeles, se fue a otra ventana o se intento teclear.
    """
    if not os.environ.get("ISLAND_DEBUG"):
        return
    try:
        # El mismo fichero que usa el dictado: el pegado es la ultima
        # fase de lo que el dictado ya traza, y partirlo en dos ficheros
        # obligaria a cruzarlos a mano para leer un ciclo entero.
        carpeta = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"),
                               "island-dictado")
        os.makedirs(carpeta, exist_ok=True)
        with open(os.path.join(carpeta, "traza.log"), "a") as f:
            f.write("%.3f pegar: %s\n" % (time.time(), msg))
    except OSError:
        pass


def pegar(texto, destino=None):
    """Deja el texto en la ventana que estabas usando.

    **Se pega, no se teclea.** Medido: `xdotool type` pierde las vocales
    acentuadas ("grabe video" por "grabé vídeo") porque remapea un
    codigo de tecla por cada caracter que el teclado no tiene, y con el
    retardo por defecto el servidor X no ha procesado el mapa nuevo
    cuando llega la pulsacion. Con `--delay 12` sale bien, pero entonces
    una frase de 300 caracteres tarda casi cuatro segundos.

    Pegar no tiene ninguno de los dos problemas: es instantaneo y el
    portapapeles no pasa por el mapa de teclado, asi que una ñ, un emoji
    o una interrogacion de apertura llegan intactos.

    Al portapapeles SIEMPRE, ademas, aunque el pegado falle: lo que
    acabas de dictar o elegir sigue estando a un Ctrl+V de distancia en
    vez de haberse perdido.

    Devuelve "escrito", "portapapeles" o "nada".
    """
    destino = destino or {}
    t0 = time.monotonic()
    if not copy_clipboard(texto):
        return "nada"
    if not shutil.which("xdotool"):
        return "portapapeles"
    try:
        if destino.get("id"):
            # Devolver el foco a donde estaba al empezar: si algo lo
            # robo mientras hablabas o elegias, el texto va igual a su
            # sitio.
            subprocess.run(["xdotool", "windowactivate", "--sync",
                            destino["id"]], timeout=3)
        t1 = time.monotonic()
        atajo = ("ctrl+shift+v" if destino.get("clase") in TERMINALES
                 else "ctrl+v")
        subprocess.run(["xdotool", "key", "--clearmodifiers", atajo],
                       timeout=5, check=True)
        _traza_pegar("foco %.0f ms, %s %.0f ms, ventana %s (%s)"
                     % ((t1 - t0) * 1000, atajo,
                        (time.monotonic() - t1) * 1000,
                        destino.get("id"), destino.get("clase")))
        return "escrito"
    except (OSError, subprocess.SubprocessError) as e:
        _traza_pegar("fallo en %.0f ms: %r -> se teclea"
                     % ((time.monotonic() - t0) * 1000, e))
        # Respaldo: teclearlo. El retardo de 12 ms no es decorativo, es
        # lo que da tiempo al remapeo; por debajo se comen los acentos.
        try:
            subprocess.run(["xdotool", "type", "--clearmodifiers",
                            "--delay", "12", texto], timeout=30)
            return "escrito"
        except (OSError, subprocess.SubprocessError):
            return "portapapeles"

# -*- coding: utf-8 -*-
"""Acciones de los paneles: audio, red y perfil de energia.

Todo lo que pueda tardar (nmcli tarda segundos en escanear) se hace en
un hilo y se devuelve por GLib.idle_add. Un bloqueo aqui congelaria la
animacion de la isla.
"""
import os
import subprocess
import threading
from gi.repository import GLib
import config as C

SINK = "@DEFAULT_AUDIO_SINK@"
EPP_CONF = C.EPP_CONF
EPP_SET = C.EPP_SET

# Etiqueta visible -> valor que entiende power-epp-set.sh. Son los
# mismos cuatro primeros que admite la regla de /etc/sudoers.d/power-epp;
# cualquier otro valor lo rechazaria sudo.
EPP_MODES = [
    ("Auto",        "auto"),
    ("Rendimiento", "performance"),
    ("Equilibrado", "balance_performance"),
    ("Ahorro",      "balance_power"),
]


def _run(args, timeout=8):
    try:
        return subprocess.run(args, capture_output=True, text=True,
                              timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


# ---------------------------------------------------------------- audio

def set_volume(frac):
    frac = max(0.0, min(1.0, frac))
    _run(["wpctl", "set-mute", SINK, "0"], 2)
    _run(["wpctl", "set-volume", "-l", "1.0", SINK, "%.2f" % frac], 2)


def toggle_mute():
    _run(["wpctl", "set-mute", SINK, "toggle"], 2)


# -------------------------------------------------------------- energia

def epp_disponible():
    """Hay un selector de perfiles instalado?

    Sin el, el panel de energia se queda solo con el estado de la
    bateria en vez de ensenar botones que no harian nada.
    """
    return os.path.exists(EPP_SET)


def epp_current():
    try:
        with open(EPP_CONF) as f:
            v = f.read().strip()
        return v or "auto"
    except OSError:
        return "auto"


def epp_set(mode, done=None):
    def work():
        r = _run(["sudo", "-n", EPP_SET, mode], 10)
        ok = bool(r and r.returncode == 0)
        if done:
            GLib.idle_add(done, ok, mode)
    threading.Thread(target=work, daemon=True).start()


# ------------------------------------------------------------------ red

def wifi_scan(done, limit=5):
    """Lista de redes: [(ssid, senal 0-100, en_uso, segura)].

    'nmcli device wifi list' puede tardar varios segundos cuando toca
    reescanear, de ahi el hilo.
    """
    def work():
        nets = []
        r = _run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY",
                  "device", "wifi", "list"], 15)
        if r and r.returncode == 0:
            # Un mismo SSID sale VARIAS veces: un punto de acceso dual
            # publica 2.4 y 5 GHz por separado, y solo una de las dos
            # filas lleva la marca de "en uso". Quedarse con la primera
            # que aparece perdia el indicador de red conectada, asi que
            # se agrupa por SSID y gana la fila en uso; si ninguna lo
            # esta, la de mas senal.
            best = {}
            for line in r.stdout.splitlines():
                # nmcli escapa los ':' internos como '\:'
                parts = line.replace("\\:", "\x00").split(":")
                if len(parts) < 4:
                    continue
                use, ssid, sig, sec = [p.replace("\x00", ":") for p in parts[:4]]
                if not ssid:
                    continue
                try:
                    sig = int(sig)
                except ValueError:
                    sig = 0
                cand = (ssid, sig, use.strip() == "*", bool(sec.strip()))
                cur = best.get(ssid)
                if (cur is None
                        or (cand[2] and not cur[2])
                        or (cand[2] == cur[2] and cand[1] > cur[1])):
                    best[ssid] = cand
            nets = list(best.values())
            # La conectada primero; el resto por potencia de senal.
            nets.sort(key=lambda n: (not n[2], -n[1]))
        GLib.idle_add(done, nets[:limit])
    threading.Thread(target=work, daemon=True).start()


def wifi_connect(ssid, done=None):
    def work():
        # 'con up' reutiliza el perfil guardado (con su contrasena). Si
        # la red no se conocia aun, se intenta una conexion nueva, que
        # solo prospera si es abierta: pedir contrasena necesita una
        # interfaz de texto que la isla no tiene.
        r = _run(["nmcli", "con", "up", "id", ssid], 25)
        if not (r and r.returncode == 0):
            r = _run(["nmcli", "device", "wifi", "connect", ssid], 25)
        ok = bool(r and r.returncode == 0)
        if done:
            GLib.idle_add(done, ok, ssid, "")
    threading.Thread(target=work, daemon=True).start()


def known_networks():
    """Nombres de perfiles ya guardados en NetworkManager.

    Sirve para decidir si hay que pedir contrasena: si la red ya tiene
    perfil, 'nmcli con up' reconecta con la que haya guardada y pedirla
    otra vez seria un paso de mas.
    """
    r = _run(["nmcli", "-t", "-f", "NAME", "connection", "show"], 6)
    if not r or r.returncode != 0:
        return set()
    return {l.strip() for l in r.stdout.splitlines() if l.strip()}


def wifi_connect_pw(ssid, password, done=None):
    def work():
        r = _run(["nmcli", "device", "wifi", "connect", ssid,
                  "password", password], 40)
        ok = bool(r and r.returncode == 0)
        msg = ""
        if not ok and r is not None:
            err = (r.stderr or "").lower()
            # El mensaje exacto varia entre versiones; lo que interesa es
            # distinguir "contrasena mal" de un fallo cualquiera, para
            # poder volver al campo en vez de cerrar el panel.
            if "secrets" in err or "password" in err or "key" in err:
                msg = "bad-password"
        if done:
            GLib.idle_add(done, ok, ssid, msg)
    threading.Thread(target=work, daemon=True).start()


# ------------------------------------------------------- no molestar

def dnd_paused():
    r = _run(["dunstctl", "is-paused"], 2)
    return bool(r and r.stdout.strip() == "true")


def dnd_toggle():
    _run(["dunstctl", "set-paused", "toggle"], 2)


# ------------------------------------------------------- reproduccion

def media(accion):
    """play-pause / previous / next sobre el reproductor MPRIS activo."""
    _run(["playerctl", accion], 3)


# ------------------------------------------------------------- bspwm

def bspwm_layout():
    r = _run(["bspc", "query", "-D", "-d", "focused", "--names"], 2)
    r2 = _run(["bspc", "query", "-T", "-d", "focused"], 2)
    import json as _j
    try:
        return _j.loads(r2.stdout).get("layout", "tiled")
    except Exception:
        return "tiled"


def bspwm_gap():
    r = _run(["bspc", "config", "window_gap"], 2)
    try:
        return int((r.stdout or "0").strip())
    except ValueError:
        return 0


def bspwm(*args):
    """Orden suelta de bspc. Se usa para las acciones del panel de
    escritorio, que son todas de una sola linea."""
    _run(["bspc"] + list(args), 3)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dynamic Island para bspwm.

Una sola ventana transparente a todo el ancho, pegada arriba. Dentro se
dibuja la capsula con cairo a 60fps. No se redimensiona la ventana X11
al expandirse: la ventana es siempre igual de grande y lo que cambia es
el dibujo. Redimensionar una ventana X11 no lo anima el compositor y se
veria a saltos; dibujando por dentro el control es total.
"""
import os
import sys
import time
import math
import locale
import calendar
import textwrap
import threading
import shlex
from collections import deque
import datetime
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib
import cairo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import theme as T
import render as R
from spring import Spring
import sources
import controls
import config as C


# Sin esto, strftime usa la locale C y la fecha saldria "Sun 15 Nov".
# Con LANG=es_ES.UTF-8 queda "dom 15 nov".
try:
    locale.setlocale(locale.LC_TIME, "")
except locale.Error:
    pass


class _Fase(object):
    """Lee self.anim en el momento de dibujar.

    La fase del latido cambia en cada fotograma pero el contenido solo
    se reconstruye cuando cambia de verdad; pasando este objeto en vez
    del numero, el dibujado mira el valor de ESTE fotograma.
    """
    def __init__(self, isla):
        self._isla = isla

    @property
    def value(self):
        return self._isla.anim


class Contador(object):
    """Lo que una cifra necesita recordar para rodar: de que valor
    venia, a cual va y por donde va el camino.

    Vive en la isla y no en el objeto de dibujo porque el contenido se
    reconstruye cada vez que cambia algo: un dibujo no puede acordarse
    de nada entre fotogramas.
    """
    def __init__(self, texto=""):
        self.actual = self.previo = texto
        self.sp = Spring(1.0, response=T.SP_ROLL_RESP,
                         damping=T.SP_ROLL_DAMP, escala=0.01)

    @property
    def p(self):
        return self.sp.value

    def set(self, texto):
        """Devuelve True si hay rodillo nuevo que animar."""
        if texto == self.actual:
            return False
        # Si llega otro cambio a mitad de camino, lo de antes se da por
        # visto: el usuario sube el volumen de tres en tres y lo que
        # importa es la cifra nueva, no encadenar animaciones.
        self.previo = self.actual
        self.actual = texto
        self.sp.snap(0.0)
        self.sp.set(1.0)
        return True


class Activity(object):
    """Algo que la isla muestra. 'pill' crece a lo ancho; 'card' crece
    tambien a lo alto y admite dos lineas."""
    def __init__(self, kind, prio, ttl, data, mode="pill"):
        self.kind = kind
        self.prio = prio
        self.data = data
        self.mode = mode
        self.born = time.monotonic()
        self.expires = None if ttl is None else self.born + ttl

    def alive(self, now):
        return self.expires is None or now < self.expires


class Island(Gtk.Window):

    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)

        geo = Gdk.Display.get_default().get_monitor(0).get_geometry()
        self.W, self.H = geo.width, T.WIN_H

        self.set_app_paintable(True)
        self.set_decorated(False)
        self.set_resizable(False)
        # DOCK: bspwm no lo gestiona como ventana normal y se queda
        # encima sin entrar en el mosaico.
        self.set_type_hint(Gdk.WindowTypeHint.DOCK)
        self.set_keep_above(True)
        self.set_accept_focus(False)
        self.stick()
        vis = self.get_screen().get_rgba_visual()
        if vis:
            self.set_visual(vis)
        self.set_default_size(self.W, self.H)
        self.move(geo.x, geo.y)

        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK
                        | Gdk.EventMask.BUTTON_RELEASE_MASK
                        | Gdk.EventMask.POINTER_MOTION_MASK
                        | Gdk.EventMask.LEAVE_NOTIFY_MASK
                        | Gdk.EventMask.KEY_PRESS_MASK)
        self.connect("draw", self.on_draw)
        self.connect("button-press-event", self.on_click)
        self.connect("button-release-event", self.on_release)
        self.connect("motion-notify-event", self.on_motion)
        self.connect("leave-notify-event", self.on_leave)
        self.connect("enter-notify-event", self.on_enter)
        self.connect("key-press-event", self.on_key)
        self.connect("realize", lambda *a: self.update_input_region())

        # --- animacion -------------------------------------------------
        # El ancho responde algo mas rapido que el alto: si ambos usan el
        # mismo periodo la expansion a tarjeta parece que "infla" en vez
        # de desplegarse.
        self.sp_w = Spring(600, response=0.42, damping=0.80)
        self.sp_h = Spring(T.H_COMPACT, response=0.50, damping=0.90)
        self.sp_fade = Spring(1.0, response=0.26, damping=1.0, escala=0.01)
        self._tick_id = None
        self._exp_id = None
        self._last = time.monotonic()

        # --- contenido -------------------------------------------------
        self.content = None       # (mode, item)
        self.prev_content = None
        self.state_key = None

        # --- datos -----------------------------------------------------
        self.sys = sources.SystemInfo()
        self.bspwm = sources.Bspwm(self._on_bspwm)
        self.player = sources.Player(self._on_player)
        # Que ventana tiene el foco, para avisar de que el dictado esta
        # disponible. Solo se consulta cuando el foco cambia (ver
        # sources.Foco), no en bucle.
        self.foco = sources.Foco(self._on_foco)
        # Quien captura audio, sea quien sea. Ahora que la isla sabe
        # escuchar, lo honesto es que sea tambien la que avisa de que
        # alguien escucha.
        self.micro = sources.Micro(self._on_micro)
        # Avisa cuando una IA termina en una ventana que no estas
        # mirando, que es la unica vez que el aviso sirve de algo.
        self.trabajo = sources.Trabajo(self._on_fin_ia, C.TRABAJO_MINIMO)
        self.portapapeles = sources.Portapapeles(C.CLIP_MAX, C.CLIP_CADA)
        self.activities = {}
        # Ultimos niveles del microfono, para la onda del dictado. Tope
        # fijo: es una ventana deslizante, no un historial.
        self.dict_levels = deque(maxlen=T.DICT_BARS)
        # Lo que se DIBUJA, que persigue a dict_levels. Los niveles
        # llegan doce veces por segundo y la pantalla va a sesenta: sin
        # esta segunda lista la onda avanzaria a saltos de cinco
        # fotogramas, que es justo el tiron que se ve en una barra de
        # sonido mal hecha.
        self.dict_shown = deque(maxlen=T.DICT_BARS)
        self.wifi_nets = None
        self.cal_off = 0          # meses de desplazamiento respecto a hoy
        self.dnd = False          # dunst en pausa
        self.oculto = False
        self._hide_id = None
        # None hasta el primer informe de bspwm: asi el notch no se
        # asoma en el arranque, que no es un cambio de escritorio.
        self._ws_prev = None
        # Muelle del desplazamiento vertical: 0 = visible, negativo =
        # replegado hacia arriba.
        self.sp_y = Spring(0, response=0.34, damping=0.92)
        # Un muelle de anchura por escritorio. El que deja de estar
        # activo se encoge mientras el nuevo crece, los dos con los
        # mismos parametros: como lo que uno pierde lo gana el otro en
        # el mismo instante, el ancho total no varia y el azul parece
        # DESLIZARSE hasta su sitio en vez de saltar.
        # Posicion de la pildora del indicador de escritorios.
        self.sp_wsx = Spring(0, response=T.SP_WS_RESP, damping=T.SP_WS_DAMP)
        # Crecimiento de la pildora al aterrizar en un escritorio.
        self.sp_pop = Spring(T.SEG_SLOT, response=T.SP_POP_RESP,
                             damping=T.SP_POP_DAMP)
        self.launch = None        # estado del lanzador de aplicaciones
        self.emo = None           # estado del selector de emoji
        self.port = None          # estado del historial del portapapeles
        self.emo_destino = {}     # ventana donde ira el emoji
        self.apps = []            # indice de .desktop (se llena en diferido)
        self.wins = []            # ventanas abiertas (se lee al abrir)
        self._drag = None
        self._prev_dmg = (0, 0)
        self.anim = 0.0           # fase 0..1 de las animaciones ciclicas
        self._was_charging = None # para detectar el flanco de enchufado

        # Realce de hover: en vez de que cada elemento se dibuje distinto
        # al pasar por encima, hay UN solo rectangulo que se desliza
        # entre zonas. Asi el cambio de un elemento a otro es continuo
        # (como el menu de macOS) y no un parpadeo de dos estados.
        self.hover = None
        self.pw = None            # estado del campo de contrasena
        self.known = set()        # perfiles de red ya guardados
        self.caret_on = True
        self._blink_id = None
        self._seat = None          # captura activa (puntero/teclado)
        self._dentro = False       # el raton, encima de la isla
        self._hover_r = R.HOVER_R  # forma del realce, la dice cada zona
        # La fase del ciclo de 1,4 s, envuelta para que los dibujos la
        # lean EN VIVO: el contenido no se reconstruye en cada fotograma.
        self.sp_anim = _Fase(self)
        self._cont = {}            # cifras que ruedan, por nombre
        # Medidor. Sin numeros, "optimizar" es mover cosas de sitio: lo
        # que se mide es a cuantos fotogramas se va de verdad, cuanto
        # cuesta cada uno y cuantas veces se reconstruye el contenido,
        # que es lo caro. Solo con ISLAND_DEBUG.
        self._prof = {"tick": 0, "draw": 0, "ms": 0.0, "max": 0.0,
                      "refresh": 0}
        self._per_ms = None        # periodo de fotograma, se calcula al usar
        self._grab_guard = None
        # Mas rapidos que los de la isla (0.38-0.50): el hover tiene que
        # sentirse inmediato, no "animado". Amortiguacion alta para que
        # no rebote al llegar a la zona.
        self.sp_hx = Spring(0, response=0.20, damping=0.95)
        self.sp_hy = Spring(0, response=0.20, damping=0.95)
        self.sp_hw = Spring(0, response=0.20, damping=0.95)
        self.sp_hh = Spring(0, response=0.20, damping=0.95)
        self.sp_ha = Spring(0, response=0.16, damping=1.0, escala=0.01)
        # Entrada del indicador de dictado disponible. Con rebote (0.7):
        # es un aviso de que algo se ha encendido, y un pequeño remate
        # al llegar lo hace notar sin tener que parpadear para siempre.
        # Nivel de volumen y brillo. Sin muelle, la barra SALTA al valor
        # nuevo: el evento trae un numero y se pinta tal cual, asi que
        # subir el volumen de 30 a 70 era un corte, no un movimiento.
        # Rapido y sin rebote: esto no es una entrada en escena, es un
        # mando respondiendo, y un rebote ahi se lee como imprecision.
        self.sp_nivel = Spring(0.0, response=T.SP_NIVEL_RESP,
                               damping=T.SP_NIVEL_DAMP, escala=0.01)
        self._nivel_de = None      # de que es el nivel que lleva dentro
        self.sp_mic = Spring(0.0, response=0.34, damping=0.70, escala=0.01)
        self.sp_rec = Spring(0.0, response=0.34, damping=0.70, escala=0.01)
        self._cursor_ptr = None
        self.fifo = sources.Fifo(sources.FIFO, self.on_event)

        if os.environ.get("ISLAND_DEBUG"):
            GLib.timeout_add_seconds(1, self._prof_dump)

        # Un unico temporizador de 1 s para reloj y enchufe: dos
        # separados despertaban el proceso el doble de veces para hacer
        # el mismo trabajo.
        GLib.timeout_add_seconds(1, self._tick_1s)
        # 15 s y no 5: este ciclo lanza wpctl e ip como subprocesos, y
        # ni la IP ni el volumen cambian solos. La bateria, que si
        # interesa al instante, va por _poll_power, que solo lee sysfs.
        GLib.timeout_add_seconds(15, self._tick_sys)

        self.show_all()
        self.refresh(initial=True)
        # Indexar 275 .desktop son ~20 ms: poco, pero no hay razon para
        # gastarlos antes de que la barra este en pantalla.
        GLib.idle_add(self._index_apps)
        # Lo fija la isla y no launch.sh: asi AUTOHIDE es la unica
        # fuente de verdad y no pueden quedar descuadrados.
        controls.bspwm("config", "top_padding",
                       "0" if T.AUTOHIDE else str(T.ALTO_RESERVADO))
        if T.AUTOHIDE:
            GLib.timeout_add(1200, self._quiza_ocultar)

    # ------------------------------------------------------------ datos

    def _al_frente(self):
        """Vuelve a poner la ventana encima de todo.

        GTK marca _NET_WM_STATE_ABOVE, pero bspwm no gestiona las
        ventanas de tipo DOCK: no hay nadie que haga cumplir esa marca,
        asi que cualquier ventana que se mapee o reciba el foco queda
        por encima y el notch desaparece detras. Es lo mismo que
        resolvia 'wm-restack = bspwm' en polybar.

        Se llama en los eventos de bspwm porque son exactamente los
        momentos en que el apilado cambia: abrir, cerrar, enfocar o
        cambiar de escritorio.
        """
        gw = self.get_window()
        if gw is not None:
            gw.raise_()

    def _on_bspwm(self):
        """Evento de bspwm. Si ha cambiado el escritorio, el notch asoma.

        Con el auto-ocultado, cambiar de escritorio por teclado no mueve
        el raton, asi que el notch seguia replegado: ni se veia donde
        habias ido ni la pildora deslizandose. Aqui se distingue el
        cambio de ESCRITORIO de los demas informes de bspwm (que llegan
        tambien al cambiar de ventana) para no asomarlo sin motivo.
        """
        self._al_frente()
        foco = self.bspwm.focused
        if foco != getattr(self, "_ws_prev", None):
            if self._ws_prev is not None:
                self._mostrar()
                self._programar_ocultado(T.REVEAL_MS)
            self._ws_prev = foco
        self.refresh()

    def _index_apps(self):
        self.apps = sources.scan_apps()
        return False

    def _tick_1s(self):
        self._poll_power()
        self._tick_clock()
        return True

    def _prof_dump(self):
        p = self._prof
        if p["tick"] or p["draw"]:
            try:
                carpeta = os.path.join(
                    os.environ.get("XDG_RUNTIME_DIR", "/tmp"),
                    "island-dictado")
                os.makedirs(carpeta, exist_ok=True)
                with open(os.path.join(carpeta, "traza.log"), "a") as f:
                    f.write("perf: %3d tick/s  %3d draw/s  %5.2f ms medio"
                            "  %5.2f ms peor  %3d refresh/s\n"
                            % (p["tick"], p["draw"],
                               p["ms"] / max(1, p["draw"]), p["max"],
                               p["refresh"]))
            except OSError:
                pass
        for k in p:
            p[k] = 0 if k != "ms" else 0.0
        p["max"] = 0.0
        return True

    def _tick_clock(self):
        # El reloj muestra HH:MM, asi que 59 de cada 60 refrescos no
        # cambiaban un solo pixel y aun asi reconstruian todo el
        # contenido. Solo se refresca cuando el minuto cambia de verdad.
        now = time.strftime("%H:%M")
        if now != getattr(self, "_last_clock", None):
            self._last_clock = now
            self.refresh()
        return True

    def _tick_sys(self):
        self.sys.refresh()
        self.dnd = controls.dnd_paused()
        self._sync_persistent()
        self.refresh()
        return True

    def _poll_power(self):
        """Vigila el enchufe aparte del refresco general.

        Leer dos ficheros de sysfs es barato, asi que se hace cada
        segundo: con el ciclo de 5 s la isla tardaba hasta cinco
        segundos en enterarse de que habias enchufado, y la reaccion
        dejaba de leerse como respuesta a lo que acababas de hacer.
        """
        before = self.sys.charging
        self.sys.refresh_power()
        now = self.sys.charging

        if self._was_charging is None:
            self._was_charging = now
            return True

        if now != self._was_charging:
            self._was_charging = now
            self.activities["power"] = Activity(
                "power", 40, 4.0,
                {"charging": now, "pct": self.sys.battery}, "pillx")
            self.refresh()
        elif before != now:
            self.refresh()
        return True

    def _sync_persistent(self):
        """Actividades que no las dispara un evento sino un estado: la
        VPN levantada y la bateria critica."""
        if self.sys.vpn_ip:
            self.activities["vpn"] = Activity(
                "vpn", 5, None,
                {"ip": self.sys.vpn_ip, "target": sources.vpn_label()}, "pill")
        else:
            self.activities.pop("vpn", None)

        if self.sys.battery <= 12 and not self.sys.charging:
            self.activities["battery"] = Activity(
                "battery", 8, None, {"pct": self.sys.battery}, "pill")
        else:
            self.activities.pop("battery", None)

    def _on_player(self):
        p = self.player
        if not p.playing:
            self.activities.pop("music", None)
            self.refresh()
            return
        data = {"title": p.title, "artist": p.artist, "art": None}
        self.activities["music"] = Activity("music", 10, None, data, "card")
        url = p.art_url

        def got(pb):
            # Puede haber cambiado de cancion mientras bajaba: solo se
            # acepta la imagen si sigue siendo la pista que la pidio.
            act = self.activities.get("music")
            if pb is not None and act is not None and act.data is data:
                data["art"] = pb
                self.refresh()
            return False

        sources.fetch_art(url, 56, got)
        self.refresh()

    def _on_micro(self):
        """Alguien ha abierto o cerrado el microfono.

        Al abrirse se despliega el notch unos segundos, porque el punto
        rojo en reposo solo se ve si estas mirando y esto es justo lo
        que hay que enterarse SIN mirar. Al cerrarse basta con que el
        indicador desaparezca.
        """
        if self.micro.abierto:
            self.activities["micro"] = Activity(
                "micro", 35, 3.5, {"quien": self.micro.quien}, "pillx")
        else:
            self.activities.pop("micro", None)
        self.refresh()

    def _on_foco(self):
        # Solo llega cuando la respuesta CAMBIA (ver sources.Foco), asi
        # que no hace falta comparar nada aqui.
        self.refresh()

    def _on_fin_ia(self, ia, app, segundos):
        if os.environ.get("ISLAND_DEBUG"):
            # 'segundos' puede ser None a proposito: si no se vio
            # empezar el trabajo, no se inventa un numero. La traza
            # tenia que saberlo y no lo sabia, asi que reventaba justo
            # en el caso que el aviso contempla.
            print("fin-ia: %s tras %s" % (
                app, "?" if segundos is None else "%.0fs" % segundos),
                flush=True)
        self.activities["fin-ia"] = Activity(
            "fin-ia", 55, 8.0,
            {"ia": ia, "app": app, "segundos": segundos}, "card")
        self.refresh()

    def on_event(self, ev):
        kind = ev.get("kind", "notify")
        if kind == "panel":
            # Permite abrir un panel sin raton: util para atarlo a una
            # tecla en sxhkd, y es lo que hace comprobable el panel de
            # forma automatica.
            self.open_panel(ev.get("target", "volume"))
            return
        if kind == "dismiss":
            self.activities.pop(ev.get("target", ""), None)
            if not self.activities:
                # Quien manda un dismiss quiere el notch fuera YA, no
                # dentro de 700 ms: es lo que hace captura.py antes de
                # disparar para no fotografiarse a si misma.
                self._programar_ocultado(0)
            self.refresh()
            return
        if kind == "dictado":
            # El dictado manda sobre todo lo demas mientras dura: lo
            # acabas de pulsar tu y estas hablando a la maquina. Y es la
            # unica actividad que NO caduca sola mientras esta en
            # marcha, porque no se sabe cuanto vas a hablar.
            estado = ev.get("state") or "oyendo"
            if estado == "oyendo":
                self.dict_levels.append(float(ev.get("value") or 0.0))
                # La barra nueva nace a la altura de la anterior y sube
                # desde ahi: apareciendo a cero, cada muestra empezaria
                # con un parpadeo hacia abajo.
                self.dict_shown.append(
                    self.dict_shown[-1] if self.dict_shown else 0.0)
            elif estado == "transcribiendo":
                # La onda no se borra ni se congela: se le pone objetivo
                # cero y CAE sola hasta la linea base, porque el
                # suavizado de _on_tick ya la lleva a donde apunte. Al
                # soltar la tecla se ve lo que de verdad ha pasado, que
                # el microfono se ha cerrado, en vez de un corte seco
                # entre dos tarjetas distintas.
                for i in range(len(self.dict_levels)):
                    self.dict_levels[i] = 0.0
            else:
                self.dict_levels.clear()
                self.dict_shown.clear()
            ttl = None if estado in ("oyendo", "transcribiendo") else \
                (6.0 if estado == "listo" else 3.0)

            # Un nivel nuevo con el dictado ya en marcha no cambia ni un
            # texto ni el ancho: lo unico que se mueve es la onda, y la
            # onda lee la lista EN VIVO al dibujar. Reconstruir aqui el
            # contenido seria medir con Pango doce veces por segundo
            # unas cadenas que no han cambiado.
            act = self.activities.get("dictado")
            if (estado == "oyendo" and act is not None
                    and (act.data.get("state") or "oyendo") == "oyendo"):
                act.data = ev
                self.ensure_tick()
                return

            # "panel" no es un panel de verdad: es el unico modo cuyo
            # alto se ajusta al contenido, y el resultado puede ocupar
            # una linea o tres. Los demas estados son de alto fijo.
            modo = "panel" if estado == "listo" else "card"
            self.activities["dictado"] = Activity("dictado", 60, ttl, ev, modo)
            self.refresh()
            return

        if kind in ("volume", "brightness"):
            objetivo = max(0.0, min(1.0, float(ev.get("value") or 0) / 100.0))
            if self._nivel_de != kind:
                # Al cambiar de mando no se desliza desde el valor del
                # otro: el brillo al 20% no tiene que venir volando
                # desde el volumen al 80%.
                self.sp_nivel.snap(objetivo)
                self._nivel_de = kind
            else:
                self.sp_nivel.set(objetivo)
            self.ensure_tick()

        spec = {
            "volume":     (30, 1.8, "pillx"),
            "brightness": (30, 1.8, "pillx"),
            "notify":     (20, 5.0, "card"),
            "music":      (10, None, "card"),
            "power":      (40, 4.0, "pillx"),
            # Mas que una notificacion y mas duradera: la acabas de
            # pedir tu, y tiene botones que hay que llegar a pulsar.
            "captura":    (35, 6.0, "card"),
        }.get(kind, (20, 5.0, "card"))
        prio, ttl, mode = spec
        if ev.get("ttl") is not None:
            ttl = ev["ttl"] or None
        if kind == "power":
            # Normaliza el evento externo a la misma forma que produce
            # _poll_power, para que el renderizador sea uno solo.
            ev = {"kind": "power", "charging": bool(ev.get("charging")),
                  "pct": int(ev.get("value") or self.sys.battery)}
        if kind == "notify":
            # Limpiar ANTES de aplicar reglas: si no, una etiqueta
            # partiria una palabra que una regla espera encontrar.
            ev["title"] = sources.sanitize(ev.get("title"))
            ev["body"] = sources.sanitize(ev.get("body"))
            ev["app"] = sources.sanitize(ev.get("app"))
            self._enrich(ev)
        if kind == "music" and not ev.get("title"):
            self.activities.pop("music", None)
        else:
            self.activities[kind] = Activity(kind, prio, ttl, ev, mode)
        self.refresh()

    def _enrich(self, ev):
        """Identifica de que servicio web viene una notificacion.

        Chrome manda todas sus notificaciones como 'Google Chrome', asi
        que se cruza todo lo disponible (nombre, titulo, cuerpo, URL y
        etiqueta de agrupacion) contra las reglas de apps.json. Si casa,
        se sustituye el nombre por el del servicio y se baja su favicon.
        """
        rule = sources.match_app(ev.get("app"), ev.get("title"),
                                 ev.get("body"), ev.get("hint"))
        if rule is None:
            return
        ev["app"] = rule.get("name") or ev.get("app")
        dom = rule.get("domain")
        if not dom:
            return

        def got(pb):
            act = self.activities.get("notify")
            if pb is not None and act is not None and act.data is ev:
                ev["pix"] = pb
                self.refresh()
            return False

        sources.fetch_favicon(dom, 52, got)

    def current(self):
        now = time.monotonic()
        dead = [k for k, a in self.activities.items() if not a.alive(now)]
        for k in dead:
            del self.activities[k]
        if not self.activities:
            return None
        # Mayor prioridad; a igualdad, la mas reciente.
        return max(self.activities.values(), key=lambda a: (a.prio, a.born))

    # --------------------------------------------------------- contenido

    def _measure_ctx(self):
        if not hasattr(self, "_mcr"):
            s = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)
            self._mcr = cairo.Context(s)
        return self._mcr

    def build(self, cr):
        act = self.current()
        if act is None:
            return "idle", "pill", self.build_idle(cr)
        key = act.kind
        if act.kind == "dictado":
            # Cada nivel de la onda llega como un evento; si la clave
            # cambiara con el, la isla haria un fundido cruzado doce
            # veces por segundo. Lo que si cruza es el cambio de fase.
            key = "dictado:" + str(act.data.get("state") or "oyendo")
        if act.kind == "panel":
            # La clave distingue CADA panel, no solo "es un panel": si no,
            # pasar de la lista de wifi al campo de contrasena no cuenta
            # como cambio de estado y el realce de hover se queda pegado
            # sobre una zona que ya no existe.
            key = "panel:" + str(act.data.get("which"))
        return key, act.mode, self.build_activity(cr, act)

    @staticmethod
    def _ico(nombre, px, color, respaldo="", tag=None):
        """Icono por nombre interno, en el juego que diga theme.USAR_SOLAR.

        Centralizarlo aqui es lo que permite cambiar de juego de iconos
        con una constante: las decenas de llamadas repartidas por los
        paneles no saben si detras hay un SVG o un glifo.
        """
        font = (T.F_SMALL if px <= 23
                else T.F_ICON if px <= 30 else T.F_ICON_L)
        # 'nombre' puede ser un nombre interno ("wifi") o ya un glifo
        # suelto: algunos mapas de theme guardan el caracter directamente.
        # Aceptar ambos evita tener que mantenerlos sincronizados.
        glifo = T.ICON_GLYPH.get(nombre)
        if glifo is None:
            glifo = respaldo or (nombre if len(nombre) <= 2 else "")
        if T.USAR_SOLAR:
            return R.Icon(nombre, px, color, glifo, font, tag)
        return R.Text(glifo, font, color, tag=tag)

    def build_idle(self, cr):
        si = self.sys
        row = R.Row()
        # Reloj y fecha forman un grupo pulsable que abre el calendario.
        row.add(R.Row([
            R.Rodillo(self._rodillo("reloj", time.strftime("%H:%M")),
                      T.F_CLOCK, T.FG),
            # La fecha acompana al reloj: mismo grupo, por eso GAP_ITEM y
            # no GAP_GROUP. Mas pequena y apagada para que el reloj siga
            # siendo el ancla visual del notch.
            R.Gap(T.GAP_ITEM),
            R.Text(time.strftime("%a %d %b"), T.F_SMALL, T.DIM),
        ], tag="clock"))
        row.add(R.Gap(T.GAP_GROUP))

        # Indicador de escritorios: pista de huecos iguales con una
        # pildora azul que se desliza al cambiar. El muelle solo mueve
        # su posicion; la pista es fija, asi que la animacion es un
        # unico elemento viajando y no dos cambiando de tamano.
        estados = [st for _n, st in self.bspwm.desktops]
        destino = self.bspwm.focused * R.WsBar.paso()
        if self.sp_wsx.target != destino:
            self._ws_salida = self.sp_wsx.target
            if T.WS_ANIM:
                self.sp_wsx.set(destino)
            else:
                self.sp_wsx.snap(destino)
            if T.WS_POP:
                # Arranca del tamano de un punto y crece hasta el suyo.
                self.sp_pop.snap(T.SEG_BAR)
                self.sp_pop.set(T.SEG_SLOT)
            self.ensure_tick()
        ws = R.Row([R.WsBar(estados, self.sp_wsx.value, self.sp_pop.value,
                            getattr(self, "_ws_salida", None))], tag="ws")
        row.add(ws)

        row.add(R.Gap(T.GAP_GROUP))
        # Dictado disponible. Mismo criterio que el "no molestar" de
        # abajo: aparece solo cuando significa algo. Un icono permanente
        # para un estado que casi siempre esta apagado es ruido fijo.
        quiere = 1.0 if self.foco.ia else 0.0
        if self.sp_mic.target != quiere:
            self.sp_mic.set(quiere)
            self.ensure_tick()
        if self.sp_mic.value > 0.01 or self.foco.ia:
            # El logo de la IA, en blanco como el resto de iconos de
            # estado, y "Dictado" al lado para que la primera vez se
            # entienda que el logo no es decoracion sino que indica
            # donde va a caer lo que digas.
            logo = self.foco.ia or "claude"
            row.add(R.Row([R.Alfa(R.Row([
                R.Icon("ia-" + logo, 22, T.FG, T.G_MIC, T.F_SMALL),
                R.Gap(8),
                R.Text("Dictado", T.F_SMALL, T.DIM),
            ]), self.sp_mic)], tag="dictado"))
            row.add(R.Gap(T.GAP_GROUP))
            self._mic_en_fila = True
        # Micro abierto por OTRO programa. Se queda mientras dure, no
        # unos segundos: lo que importa de esto no es el aviso, es poder
        # mirar el notch y saber si te estan escuchando.
        quiere_rec = 1.0 if self.micro.abierto else 0.0
        if self.sp_rec.target != quiere_rec:
            self.sp_rec.set(quiere_rec)
            self.ensure_tick()
        if self.sp_rec.value > 0.01 or self.micro.abierto:
            row.add(R.Row([R.Alfa(R.Row([
                R.Dot(7, T.RED),
                R.Gap(7),
                self._ico("mic", 22, T.RED, T.G_MIC),
            ]), self.sp_rec)], tag="micro"))
            row.add(R.Gap(T.GAP_GROUP))
            self._rec_en_fila = True

        # Solo aparece cuando esta activo: un icono permanente para un
        # estado que casi siempre esta apagado seria ruido fijo.
        if self.dnd:
            row.add(R.Row([self._ico("bell-off", 28, T.ORANGE)], tag="dnd"))
            row.add(R.Gap(T.GAP_ITEM))
        # Cada icono de estado va envuelto en una fila con etiqueta: es
        # lo que convierte el dibujo en una zona pulsable, porque las
        # etiquetas se registran al dibujar con su posicion real.
        row.add(R.Row([
            self._ico("vol-mute" if si.muted
                      else ["vol-mute", "vol-low", "vol-mid", "vol-high"][1 + min(2, si.volume // 40)],
                      28, T.DIM2 if si.muted else T.FG,
                      T.G_MUTE)], tag="vol"))
        row.add(R.Gap(T.GAP_ITEM))
        row.add(R.Row([
            self._ico("wifi" if si.wifi else "wifi-off", 28,
                      T.FG if si.wifi else T.DIM2, T.G_WIFI)], tag="net"))
        row.add(R.Gap(T.GAP_ITEM))
        if si.charging:
            bat = [self._ico("bolt", 28, T.GREEN, T.G_BOLT), R.Gap(6),
                   R.Rodillo(self._rodillo("bat", "%d%%" % si.battery),
                             T.F_TITLE, T.GREEN)]
        else:
            lvl = min(4, max(0, si.battery * 5 // 100))
            col = T.RED if si.battery <= 15 else T.FG
            bat = [self._ico("bat-%d" % lvl, 28, col, T.G_BAT[lvl]), R.Gap(6),
                   R.Rodillo(self._rodillo("bat", "%d%%" % si.battery),
                             T.F_TITLE, col)]
        row.add(R.Row(bat, tag="bat"))
        row.add(R.Gap(T.GAP_GROUP))
        row.add(self._ico("power", 28, T.DIM, T.G_POWER, tag="power"))
        return row

    def build_activity(self, cr, act):
        d = act.data
        k = act.kind

        if k in ("volume", "brightness"):
            pct = int(d.get("value", 0))
            if k == "volume":
                nom = ("vol-mute" if d.get("muted")
                       else ["vol-mute", "vol-low", "vol-mid", "vol-high"][1 + min(2, pct // 40)])
                col = T.DIM2 if d.get("muted") else T.FG
            else:
                nom, col = "sun", T.ORANGE
            # La barra va por el muelle y el numero por el valor real:
            # el numero es un dato y tiene que ser exacto desde el
            # primer fotograma; la barra es un gesto y puede tardar.
            # El icono, en hueco fijo: el altavoz cambia de dibujo con
            # el nivel (17 px el silenciado, 32 el de tres ondas) y con
            # eso la isla se reajustaba al cruzar cada umbral.
            return R.Row().add(
                R.Cell(self._ico(nom, 34, col, T.G_SUN), 34, 34),
                R.Gap(18),
                R.Bar(260, 10, self.sp_nivel, col),
                R.Gap(16),
                self._pct(cr, self._rodillo("nivel", "%d%%" % pct),
                          T.F_TITLE, T.FG))

        if k == "power":
            on = d.get("charging")
            pct = d.get("pct", 0)
            col = T.GREEN if on else T.FG
            return R.Row().add(
                R.BatteryAnim(54, 26, pct / 100.0, self.anim, col, on),
                R.Gap(18),
                self._ico("bolt", 28, T.GREEN, T.G_BOLT) if on else R.Gap(0),
                R.Gap(8) if on else R.Gap(0),
                R.Text("Cargando" if on else "En bater\u00eda",
                       T.F_TITLE, col),
                R.Gap(T.GAP_ITEM),
                R.Text("\u00b7", T.F_SUB, T.DIM2),
                R.Gap(T.GAP_ITEM),
                R.Text("%d%%" % pct, T.F_TITLE, T.FG))

        if k == "vpn":
            r = R.Row().add(
                R.Dot(7, T.GREEN), R.Gap(14),
                R.Text(d.get("ip", ""), T.F_BODY, T.FG))
            if d.get("target"):
                r.add(R.Gap(12), R.Text("·", T.F_BODY, T.DIM2),
                      R.Gap(12), R.Text(d["target"], T.F_BODY, T.DIM))
            return r

        if k == "battery":
            return R.Row().add(
                self._ico("bat-0", 34, T.RED, T.G_BAT[0]), R.Gap(16),
                R.Text("Bateria %d%%" % d.get("pct", 0), T.F_TITLE, T.RED))

        if k == "fin-ia":
            fila = R.Row()
            ia = d.get("ia") or ""
            if ia:
                fila.add(R.Icon("ia-" + ia, 30, T.FG,
                                d.get("app") or "", T.F_TITLE), R.Gap(16))
            fila.add(R.Text("Ha terminado", T.F_TITLE, T.FG))
            # La duracion solo si se vio empezar. Inventarse un "0 s"
            # porque la ventana se descubrio a mitad es peor que no
            # decir nada: el numero se lee como un dato.
            segs = d.get("segundos")
            if segs is not None:
                segs = int(segs)
                cuanto = ("%d:%02d" % (segs // 60, segs % 60) if segs >= 60
                          else "%d s" % segs)
                fila.add(R.Gap(T.GAP_ITEM),
                         R.Text("\u00b7", T.F_SUB, T.DIM2), R.Gap(T.GAP_ITEM),
                         R.Text(cuanto, T.F_SUB, T.DIM))
            return fila

        if k == "micro":
            return R.Row().add(
                R.Dot(8, T.RED), R.Gap(14),
                self._ico("mic", 28, T.RED, T.G_MIC), R.Gap(14),
                R.Text("Micr\u00f3fono abierto", T.F_TITLE, T.FG),
                R.Gap(T.GAP_ITEM),
                R.Text("\u00b7", T.F_SUB, T.DIM2), R.Gap(T.GAP_ITEM),
                R.Text(self._clip(d.get("quien") or "", 28), T.F_SUB, T.DIM))

        if k == "dictado":
            estado = d.get("state") or "oyendo"
            destino = d.get("app") or ""
            ia = d.get("ia") or ""

            if estado == "oyendo":
                fila = R.Row().add(
                    self._ico("mic", 30, T.DICT_COLOR, T.G_MIC),
                    R.Gap(16),
                    R.Wave(self.dict_shown, T.DICT_COLOR, T.DICT_BARS,
                           T.DICT_BAR_W, T.DICT_BAR_GAP,
                           T.DICT_BAR_H, T.DICT_BAR_MIN),
                    R.Gap(18),
                    R.Text("Escuchando", T.F_TITLE, T.FG))
            elif estado == "transcribiendo":
                # Sin microfono y sin onda: aqui ya no hay señal que
                # enseñar, el micro esta cerrado. Lo unico que esta
                # pasando es una espera, y para eso basta el latido de
                # los puntos. La onda todavia se ve un momento, pero
                # cayendo en la tarjeta que se desvanece por debajo.
                fila = R.Row().add(
                    R.Text("Transcribiendo", T.F_TITLE, T.FG),
                    R.Gap(16),
                    R.Pulse(self.anim, T.DICT_WORK))
            elif estado == "listo":
                lineas = textwrap.wrap(d.get("text") or "", T.DICT_COLS) or [""]
                if len(lineas) > T.DICT_LINEAS:
                    lineas = lineas[:T.DICT_LINEAS]
                    lineas[-1] = lineas[-1].rstrip() + "\u2026"
                fila = R.Row().add(
                    self._ico("check", 26, T.DICT_OK, T.G_CHECK),
                    R.Gap(14),
                    R.Stack([R.Text(l, T.F_BODY, T.FG) for l in lineas], gap=7))
            else:
                # Un fallo tiene que distinguirse de "no dijiste nada":
                # el mensaje lo manda quien lo sabe, que es el ayudante.
                fila = R.Row().add(
                    self._ico("mic-off", 28, T.DIM, T.G_MIC_OFF),
                    R.Gap(14),
                    R.Text(d.get("text") or "Sin audio", T.F_TITLE, T.DIM))

            # A donde va el texto. Si es una IA conocida, su logo en
            # blanco: un logo se reconoce de un vistazo y no hay que
            # leerlo, que es justo lo que se necesita de algo que esta
            # en pantalla dos segundos. Si no la conocemos, su nombre.
            if destino and estado != "transcribiendo":
                fila.add(R.Gap(T.GAP_ITEM),
                         R.Text("\u00b7", T.F_SUB, T.DIM2),
                         R.Gap(T.GAP_ITEM))
                if ia:
                    # El respaldo del icono es el propio nombre: si
                    # algun dia falta el SVG, se lee en vez de dejar un
                    # hueco.
                    fila.add(R.Icon("ia-" + ia, 26, T.FG, destino, T.F_SUB))
                else:
                    fila.add(R.Text(destino, T.F_SUB, T.DIM))
            return fila

        if k == "captura":
            pb = sources.load_thumb(d.get("thumb"), T.CAP_THUMB_H)
            # Sin miniatura (un PNG que GdkPixbuf no supo abrir) se
            # ensena el glifo de camara: la tarjeta sigue sirviendo,
            # porque lo que de verdad hace falta son los botones.
            cabeza = (R.Thumb(pb, T.CAP_THUMB_H, tag="cap:abrir")
                      if pb is not None
                      else self._ico("camera", 34, T.ACCENT, T.G_CAMERA))

            # El subtitulo dice el tamano y si quedo copiada, pero al
            # senalar un boton dice lo que hace ese boton. Es el mismo
            # criterio que el menu de apagado: la etiqueta vive en un
            # solo sitio y no en tres chips que ensancharian la tarjeta.
            cur = self.hover or ""
            base = " \u00b7 ".join(x for x in (d.get("text"),
                                               d.get("hint")) if x)
            sub = next((etq for etq, _g, acc in T.CAP_ACTS
                        if cur == "cap:" + acc), base)

            # El hueco del subtitulo es FIJO, el del texto mas ancho de
            # los que pueden salir ahi. Si no, al senalar un boton la
            # tarjeta se encoge, y lo que se mueve es justo el boton que
            # estas a punto de pulsar.
            txt = R.Text(sub, T.F_SMALL, T.DIM)
            ancho_sub = max([R.Text(t, T.F_SMALL, T.DIM).size(cr)[0]
                             for t in [base] + [a[0] for a in T.CAP_ACTS]])
            linea_sub = R.Row([txt,
                               R.Gap(max(0, ancho_sub - txt.size(cr)[0]))])

            botones = R.Row()
            for i, (_etq, glifo, acc) in enumerate(T.CAP_ACTS):
                if i:
                    botones.add(R.Gap(8))
                tag = "cap:" + acc
                botones.add(R.Chip(
                    "", T.F_SMALL, T.FG,
                    T.ACCENT if cur == tag else T.SURF_1, tag=tag,
                    icon=self._ico(glifo, 26,
                                   T.FG if cur == tag else T.DIM),
                    padx=14, pady=10))

            return R.Row().add(
                cabeza, R.Gap(18),
                R.Stack([
                    # "Captura" y no el nombre del fichero: son 23
                    # digitos que se comen la tarjeta y no dicen nada
                    # que no diga ya la miniatura. Donde esta se
                    # averigua con el boton de la carpeta.
                    R.Row().add(R.Text("Captura", T.F_TITLE, T.FG)),
                    linea_sub,
                ], gap=5),
                R.Gap(24), botones)

        if k == "music":
            art = d.get("art")
            tocando = self.player.status == "Playing"
            # La caratula puede llegar tarde (descarga en hilo); hasta
            # entonces se dibuja el glifo de nota y se sustituye sola.
            head = (R.Image(art, 56) if art is not None
                    else self._ico("music", 34, T.ACCENT, T.G_MUSIC))
            mandos = R.Row()
            for nom, etq in (("media-prev", "media:previous"),
                             ("media-pause" if tocando else "media-play",
                              "media:play-pause"),
                             ("media-next", "media:next")):
                mandos.add(R.Row([self._ico(nom, 26, T.FG)], tag=etq),
                           R.Gap(T.GAP_ITEM))
            return R.Row().add(
                head, R.Gap(20),
                R.Stack([
                    R.Row().add(R.Text(self._clip(d.get("title", ""), 30),
                                       T.F_TITLE, T.FG)),
                    R.Row().add(R.Text(self._clip(d.get("artist", ""), 34),
                                       T.F_SUB, T.DIM)),
                ]),
                R.Gap(T.GAP_GROUP), mandos)

        if k == "panel":
            return self.build_panel(cr, d.get("which"))

        # notificacion
        urg = d.get("urgency", "normal")
        acc = T.RED if urg == "critical" else T.ACCENT
        # Prioridad del icono: favicon del servicio > icono de la app >
        # campana. El favicon ya dice de que servicio es, asi que el
        # texto queda libre para el CONTENIDO (quien escribe y que dice)
        # en vez de gastar la primera linea repitiendo el nombre.
        pb = d.get("pix") or sources.load_icon(d.get("icon"), 52,
                                               d.get("app", ""))
        head = (R.Image(pb, 52) if pb is not None
                else self._ico("bell", 34, acc, T.G_BELL))
        title = d.get("title") or d.get("app", "")
        body = d.get("body") or ""
        if body.strip() == title.strip():
            body = ""
        rows = [R.Row().add(R.Text(self._clip(title, 32), T.F_TITLE, T.FG))]
        if body:
            rows.append(R.Row().add(R.Text(self._clip(body, 46), T.F_SUB, T.DIM)))
        return R.Row().add(head, R.Gap(20), R.Stack(rows))

    # ------------------------------------------------------------ paneles

    def build_panel(self, cr, which):
        si = self.sys

        if which == "volume":
            pct = 0 if si.muted else si.volume
            col = T.DIM2 if si.muted else T.FG
            nom = "vol-mute" if si.muted else ["vol-mute", "vol-low", "vol-mid", "vol-high"][1 + min(2, pct // 40)]
            # Una fila, no tres. El altavoz silencia al pulsarlo (como el
            # HUD de iOS), asi que los botones "Silenciar"/"Mezclador"
            # sobraban: eran una tercera fila entera para una accion que
            # ya cabe en el propio icono.
            return R.Row().add(
                R.Row([R.Cell(self._ico(nom, 34, col, T.G_MUTE), 34, 34)],
                      tag="vol-mute"),
                R.Gap(22),
                R.Slider(420, 12, self.sp_nivel, col, tag="vol-slider"),
                R.Gap(20),
                self._pct(cr, self._rodillo("nivel", "%d%%" % pct),
                          T.F_TITLE, T.FG))

        if which == "battery":
            if not controls.epp_disponible():
                # Sin selector de perfiles no se ensenan botones que no
                # harian nada: solo el estado.
                lvl = min(4, max(0, si.battery * 5 // 100))
                return R.Row().add(
                    self._ico("bolt" if si.charging else "bat-%d" % lvl, 34,
                              T.GREEN if si.charging else T.FG),
                    R.Gap(16),
                    R.Text("%d%% \u00b7 %s" % (
                        si.battery,
                        "cargando" if si.charging else "en bater\u00eda"),
                        T.F_TITLE, T.FG))
            cur = controls.epp_current()

            # El nombre del perfil va en un hueco de ancho RESERVADO (el
            # del nombre mas largo), no dentro del chip.
            #
            # Antes el chip senalado se ensanchaba para mostrar su
            # nombre, y eso desplazaba toda la fila: el chip que estabas
            # apuntando se iba de debajo del cursor y el clic caia en
            # otro sitio. Reservando el hueco, el ancho total no cambia
            # y los chips no se mueven jamas.
            lbl_w = max(R.Text(l, T.F_SUB, T.FG).size(cr)[0]
                        for l, _ in controls.EPP_MODES)
            shown = next((l for l, m in controls.EPP_MODES
                          if self.hover == "prof:" + m), None)
            if shown is None:
                shown = next((l for l, m in controls.EPP_MODES if m == cur),
                             "Auto")
            txt = R.Text(shown, T.F_SUB, T.FG)
            txt_w = txt.size(cr)[0]

            chips = R.Row()
            for i, (label, mode) in enumerate(controls.EPP_MODES):
                if i:
                    chips.add(R.Gap(8))
                on = (mode == cur)
                # Siempre solo icono: tamano constante, zona de clic
                # constante.
                # Blanco sobre el azul activo, como en rofi: una sola
                # regla para todo el escritorio.
                chips.add(R.Chip("", T.F_SUB, T.FG,
                                 T.ACCENT if on else T.SURF_1,
                                 tag="prof:" + mode,
                                 icon=self._ico(T.G_PROF[mode], 26,
                                                T.FG if on else T.DIM),
                                 padx=15, pady=10))

            lvl = min(4, max(0, si.battery * 5 // 100))
            return R.Row().add(
                self._ico("bolt" if si.charging else "bat-%d" % lvl, 34,
                          T.GREEN if si.charging else T.FG, T.G_BOLT),
                R.Gap(12),
                R.Text("%d%%" % si.battery, T.F_TITLE, T.FG),
                R.Gap(T.GAP_ITEM),
                R.Text("\u00b7", T.F_SUB, T.DIM2),
                R.Gap(T.GAP_ITEM),
                txt,
                R.Gap(lbl_w - txt_w + T.GAP_GROUP),
                chips)

        if which == "calendar":
            return self.build_calendar(cr)

        if which == "desktop":
            mono = controls.bspwm_layout() == "monocle"
            gap = controls.bspwm_gap()
            acciones = [
                ("monocle",   "Monocle",  "ds:monocle", mono),
                ("balance",   "Equilibrar", "ds:balance", False),
                ("rotate",    "Rotar",    "ds:rotate",  False),
                ("gap-minus", "Menos aire", "ds:gap-",  False),
                ("gap-plus",  "Mas aire", "ds:gap+",    False),
                ("bell-off",  "No molestar", "ds:dnd",  self.dnd),
            ]
            lbl_w = max(R.Text(a[1], T.F_SUB, T.FG).size(cr)[0]
                        for a in acciones)
            shown = next((a[1] for a in acciones if self.hover == a[2]), None)
            if shown is None:
                shown = "Escritorio %d \u00b7 %dpx" % (
                    self.bspwm.focused + 1, gap)
            txt = R.Text(shown, T.F_SUB, T.DIM)
            chips = R.Row()
            for i, (ico, _lab, tag, activo) in enumerate(acciones):
                if i:
                    chips.add(R.Gap(8))
                chips.add(R.Chip("", T.F_SUB, T.FG,
                                 T.ACCENT if activo else T.SURF_1,
                                 tag=tag,
                                 icon=self._ico(ico, 26,
                                                T.FG if activo else T.DIM),
                                 padx=15, pady=10))
            return R.Stack([R.Row().add(txt), chips], gap=16, center=True)

        if which == "launcher":
            return self.build_launcher(cr)

        if which == "emoji":
            return self.build_emoji(cr)

        if which == "portapapeles":
            return self.build_port(cr)

        if which == "powermenu":
            cur = self.hover or ""
            lbl_w = max(R.Text(a[0], T.F_SUB, T.FG).size(cr)[0]
                        for a in T.G_POWER_ACTS)
            shown = next((a[0] for i, a in enumerate(T.G_POWER_ACTS)
                          if cur == "act:%d" % i), "Apagar o salir")
            txt = R.Text(shown, T.F_SUB, T.DIM)
            chips = R.Row()
            for i, (label, glifo, _cmd) in enumerate(T.G_POWER_ACTS):
                if i:
                    chips.add(R.Gap(8))
                sel = (cur == "act:%d" % i)
                chips.add(R.Chip("", T.F_SUB, T.FG,
                                 T.ACCENT if sel else T.SURF_1,
                                 tag="act:%d" % i,
                                 icon=self._ico(glifo, 26,
                                                T.FG if sel else T.DIM),
                                 padx=15, pady=10))
            # Mismo truco que en el panel de energia: el nombre vive en
            # un hueco de ancho reservado, no dentro del chip, para que
            # los botones no se muevan al pasar por encima.
            return R.Stack([
                R.Row().add(txt),
                chips,
            ], gap=16, center=True)

        if which == "wifi-pw":
            pw = self.pw or {}
            err = pw.get("error")
            cab = R.Row().add(
                self._ico("lock", 28, T.RED if err else T.ACCENT, T.G_LOCK),
                R.Gap(T.GAP_ITEM),
                R.Text(pw.get("ssid", ""), T.F_TITLE, T.FG))

            if pw.get("estado") == "conectando":
                # Mientras nmcli trabaja. La barra NO tiene progreso
                # porque nmcli no lo da: fingir un 60% seria inventarse
                # un dato. Lo que dice es "sigo", que es lo que se sabe.
                return R.Stack([
                    cab,
                    R.Row().add(R.BarIndef(420, 8, self.sp_anim, T.ACCENT)),
                    R.Row().add(R.Text("Conectando\u2026", T.F_SMALL, T.DIM)),
                ], gap=T.GAP_ROW, center=True)

            ver = bool(pw.get("ver"))
            campo = R.Row().add(
                R.Field(380, pw.get("text", ""), T.F_SUB, T.FG,
                        caret=self.caret_on, secret=not ver, tag="pw-field"),
                R.Gap(T.GAP_ITEM),
                # El ojo no es decoracion: una contrasena de wifi se
                # teclea de un papel y sin verla no hay forma de saber
                # si el fallo fue tuyo o del papel.
                R.Row([self._ico("ojo-no" if ver else "ojo", 24,
                                 T.ACCENT if ver else T.DIM,
                                 T.G_OJO_NO if ver else T.G_OJO)],
                      tag="pw-ver"))

            if err:
                pie = R.Text("Contrase\u00f1a incorrecta \u00b7 reint\u00e9ntalo",
                             T.F_SMALL, T.RED)
            elif self._mayusculas():
                # Avisar de esto es la diferencia entre una errata y diez
                # minutos de "pero si es la buena".
                pie = R.Text("Bloq May\u00fas activado", T.F_SMALL, T.ORANGE)
            else:
                pie = R.Text("\u23ce conectar \u00b7 ^H ver \u00b7 esc cancelar",
                             T.F_SMALL, T.DIM2)
            return R.Stack([cab, campo, R.Row().add(pie)],
                           gap=T.GAP_ROW, center=True)

        # ---- wifi
        nets = self.wifi_nets
        if nets is None:
            return R.Row().add(
                self._ico("wifi", 34, T.DIM, T.G_WIFI), R.Gap(18),
                R.Text("Buscando redes\u2026", T.F_TITLE, T.DIM))
        if not nets:
            return R.Row().add(
                self._ico("wifi-off", 34, T.DIM, T.G_WIFI_NO), R.Gap(18),
                R.Text("Sin redes a la vista", T.F_TITLE, T.DIM))

        # Se mide el SSID mas largo para alinear las barras de cobertura
        # en columna; si no, cada fila las pondria a una altura distinta
        # y la lista se ve descuadrada.
        ANCHO = T.WIFI_ANCHO

        # Cabecera: el nombre a la izquierda y la IP pegada a la derecha,
        # en la misma columna que la cobertura de las filas. La IP local
        # vive aqui y no en el notch porque es un dato de consulta, no de
        # vistazo, y su sitio es junto a la red a la que pertenece.
        titulo = R.Row().add(self._ico("wifi", 24, T.DIM, T.G_WIFI),
                             R.Gap(T.GAP_ITEM),
                             R.Text("Wi-Fi", T.F_TITLE, T.FG))
        head = R.Row([R.Gap(T.WIFI_PADX), titulo])
        if si.ip:
            ip = R.Text(si.ip, T.F_SMALL, T.DIM2)
            head.add(R.Gap(max(10, ANCHO - 2 * T.WIFI_PADX
                               - titulo.size(cr)[0] - ip.size(cr)[0])),
                     ip, R.Gap(T.WIFI_PADX))

        filas = []
        for ssid, sig, inuse, sec in nets:
            lvl = 1 + min(3, sig // 26)
            # A cual estas conectado lo dice el PESO del nombre, no un
            # adorno al lado: en una lista de cuatro cosas, lo que se
            # mira son los nombres.
            nombre = R.Text(self._clip(ssid, 26),
                            T.F_TITLE if inuse else T.F_SUB,
                            T.FG if inuse else T.DIM)
            # Candado y cobertura, en ese orden y pegados al borde. El
            # hueco del candado se reserva aunque la red sea abierta, o
            # la columna de la cobertura bailaria de fila en fila.
            der = R.Row([
                self._ico("lock", 18, T.DIM2, T.G_LOCK) if sec else R.Gap(18),
                R.Gap(T.GAP_ITEM),
                R.Bars(lvl, T.FG if inuse else T.DIM, T.DIM2),
            ])
            hueco = max(10, ANCHO - 2 * T.WIFI_PADX
                        - nombre.size(cr)[0] - der.size(cr)[0])
            filas.append(R.Box(R.Row([nombre, R.Gap(hueco), der]),
                               w=ANCHO, padx=T.WIFI_PADX, pady=T.WIFI_PADY,
                               radius=14, tag="wifi:" + ssid))

        # Las filas van casi pegadas y con aire DENTRO: asi se leen como
        # una lista. Separandolas tanto como el aire que llevan dentro
        # --que es como estaba- cada una parecia una tarjeta suelta.
        return R.Stack([head, R.Rule(ANCHO, T.DIM2),
                        R.Stack(filas, gap=T.WIFI_GAP)], gap=T.GAP_ITEM)

    def build_calendar(self, cr):
        hoy = datetime.date.today()
        # Mes mostrado = hoy + desplazamiento, normalizando el desborde
        # de diciembre a enero con aritmetica sobre meses absolutos.
        m = hoy.month - 1 + self.cal_off
        y, m = hoy.year + m // 12, m % 12 + 1

        CW, CH = 46, 34
        titulo = "%s %d" % (calendar.month_name[m].capitalize(), y)

        cab = R.Row().add(
            R.Row([self._ico("prev", 22, T.DIM)], tag="cal:prev"),
            R.Gap(T.GAP_ITEM),
            R.Day(CW * 5, CH, titulo, T.F_TITLE, T.FG, tag="cal:hoy"),
            R.Gap(T.GAP_ITEM),
            R.Row([self._ico("next", 22, T.DIM)], tag="cal:next"))

        # Iniciales en castellano: la X de miercoles existe justo para
        # no chocar con la M de martes.
        dias = R.Row()
        for d in ("L", "M", "X", "J", "V", "S", "D"):
            dias.add(R.Day(CW, 26, d, T.F_SMALL, T.DIM2))

        filas = [cab, dias]
        for semana in calendar.Calendar(firstweekday=0).monthdayscalendar(y, m):
            fila = R.Row()
            for n in semana:
                if n == 0:
                    fila.add(R.Day(CW, CH, "", T.F_SMALL, T.DIM2))
                    continue
                es_hoy = (n == hoy.day and m == hoy.month and y == hoy.year)
                fila.add(R.Day(CW, CH, str(n), T.F_SMALL, T.FG,
                               circle=T.ACCENT if es_hoy else None))
            filas.append(fila)
        return R.Stack(filas, gap=6, center=True)

    def _results(self, q):
        """Resultados de todos los origenes, ya ordenados.

        Cada uno es (tipo, titulo, subtitulo, icono, carga util). Tener
        un solo tipo de resultado es lo que permite que el teclado, el
        raton y el dibujado no tengan que saber de donde salio cada
        cosa.
        """
        q = q.strip()
        out = []

        # La calculadora va primero: si lo escrito es una cuenta, es
        # casi seguro lo que se busca y no un nombre de programa.
        val = sources.calc_eval(q) if q else None
        if val is not None:
            out.append(("calc", val, "%s \u00b7 \u23ce copia" % q, None, val))

        if not q:
            # Sin busqueda: primero las ventanas abiertas y luego lo mas
            # usado. En un gestor de mosaico, lo que suele querer quien
            # abre el lanzador es saltar a algo que ya tiene abierto; y
            # mientras no haya historial de uso, una rodaja alfabetica
            # de 275 aplicaciones no dice absolutamente nada.
            for wid, titulo, clase in self.wins[:3]:
                out.append(("win", titulo, "Ventana \u00b7 %s" % clase,
                            clase, wid))
            apps = sorted(self.apps,
                          key=lambda a: -sources.frec_score(a[1]))
            apps = [a for a in apps if sources.frec_score(a[1]) > 0][:5]
            out += [("app", a[0], "Aplicaci\u00f3n", a[2], a[1]) for a in apps]
            return out[:5]

        ql = q.lower()
        for wid, titulo, clase in self.wins:
            if ql in titulo.lower() or ql in clase.lower():
                out.append(("win", titulo, "Ventana \u00b7 %s" % clase,
                            clase, wid))

        for a in sources.match_apps(self.apps, q, 6):
            out.append(("app", a[0], "Aplicaci\u00f3n", a[2], a[1]))

        # Lo copiado que case con lo escrito. Solo CON busqueda: sin
        # ella, el lanzador tiene que enseñar ventanas y aplicaciones,
        # que es a lo que se abre el 95% de las veces.
        for txt in self.portapapeles.busca(q):
            una = " ".join(txt.split())
            out.append(("clip", self._clip(una, 52),
                        "Portapapeles \u00b7 \u23ce copia", None, txt))

        # Empate entre aplicaciones: gana la mas usada.
        out.sort(key=lambda r: (0 if r[0] == "calc" else
                                1 if r[0] == "win" else
                                3 if r[0] == "clip" else 2,
                                -sources.frec_score(r[4])))

        if not out and " " not in q and q.isascii():
            out.append(("cmd", q, "Ejecutar comando", None, q))
        return out[:5]

    def build_launcher(self, cr):
        st = self.launch or {"q": "", "sel": 0, "res": []}
        res = st["res"]
        ANCHO = 560

        cab = R.Row().add(
            self._ico("search", 28, T.DIM, T.G_SEARCH),
            R.Gap(T.GAP_ITEM),
            R.Field(ANCHO - 46, st["q"], T.F_SUB, T.FG,
                    caret=self.caret_on, secret=False))
        filas = [cab]

        if not res:
            filas.append(R.Row().add(
                R.Gap(T.GAP_ITEM),
                R.Text("Sin resultados" if st["q"] else "Escribe para buscar",
                       T.F_SUB, T.DIM2)))
            return R.Stack(filas, gap=T.GAP_ROW)

        sel = min(st["sel"], len(res) - 1)
        tipo, titulo, sub, icono, _carga = res[sel]

        # Destacado: lo que hara el Intro, en grande y con su tipo. Una
        # lista sola obliga a leer linea a linea para saber que esta
        # seleccionado; asi se ve de un vistazo.
        pb = sources.load_icon(icono, 56, titulo) if icono else None
        glifo, _etq = T.G_RES[tipo]
        hero = R.Row().add(
            R.Image(pb, 56) if pb is not None
            else self._ico(glifo, 44, T.ACCENT),
            R.Gap(18),
            R.Stack([
                R.Row().add(R.Text(self._clip(titulo, 28), T.F_HERO, T.FG)),
                R.Row().add(R.Text(self._clip(sub, 40), T.F_SMALL, T.DIM)),
            ], gap=4))
        filas.append(hero)
        filas.append(R.Rule(ANCHO, T.DIM2))

        for i, (t2, tit2, _s2, ic2, _p2) in enumerate(res):
            pb2 = sources.load_icon(ic2, 26, tit2) if ic2 else None
            g2, etq2 = T.G_RES[t2]
            nombre = R.Text(self._clip(tit2, 30), T.F_SMALL,
                            T.FG if i == sel else T.DIM)
            ancho_nom = nombre.size(cr)[0]
            etq = R.Text(etq2, T.F_SMALL, T.DIM2)
            # La etiqueta de tipo se alinea a la derecha con un hueco
            # calculado, para que forme columna en vez de ir pegada a
            # cada nombre.
            hueco = max(10, ANCHO - 2 * 12 - 26 - T.GAP_ITEM
                        - ancho_nom - etq.size(cr)[0])
            fila = R.Row([
                R.Image(pb2, 26) if pb2 is not None
                else self._ico(g2, 22, T.DIM2),
                R.Gap(T.GAP_ITEM), nombre, R.Gap(hueco), etq,
            ])
            filas.append(R.Box(fila, bg=T.SURF_1 if i == sel else None,
                               w=ANCHO, padx=12, pady=7, tag="app:%d" % i))

        filas.append(R.Row().add(
            R.Text("\u2191\u2193 navegar \u00b7 \u23ce abrir \u00b7 esc cerrar",
                   T.F_SMALL, T.DIM2)))
        return R.Stack(filas, gap=10)

    def _start_launcher(self):
        # Las ventanas se consultan AQUI y no en un ciclo: son ~10 ms y
        # solo importan mientras el lanzador esta abierto.
        self.wins = sources.list_windows()
        self.launch = {"q": "", "sel": 0, "res": []}
        self.launch["res"] = self._results("")
        self.activities["panel"] = Activity(
            "panel", 50, None, {"which": "launcher"}, "panel")
        def fallo():
            self.launch = None
            self.activities.pop("panel", None)
            self.on_event({"kind": "notify", "app": "Lanzador",
                           "body": "No se pudo capturar el teclado"})
            self.refresh()

        # El panel se abre YA y la captura llega detras: esperar a tenerla
        # para pintar dejaria medio segundo de pantalla muerta despues de
        # pulsar el atajo.
        self._grab_retry(Gdk.SeatCapabilities.KEYBOARD
                         | Gdk.SeatCapabilities.ALL_POINTING, fallo)
        self._blink_on()
        self.refresh()

    def _launch_sel(self):
        st = self.launch
        if not st or not st["res"]:
            return
        tipo, titulo, _sub, _ic, carga = st["res"][min(st["sel"],
                                                       len(st["res"]) - 1)]
        self._close_panel()
        self.refresh()

        if tipo == "clip":
            ok = sources.copy_clipboard(carga)
            self.on_event({"kind": "notify", "app": "Portapapeles",
                           "body": self._clip(" ".join(carga.split()), 60)
                                   if ok else "No se pudo copiar"})
            return

        if tipo == "calc":
            ok = sources.copy_clipboard(carga)
            self.on_event({"kind": "notify", "app": "Calculadora",
                           "body": ("%s copiado" % carga) if ok
                                   else "No se pudo copiar"})
            return

        if tipo == "win":
            # Saltar a una ventana ya abierta en vez de lanzar otra
            # instancia, que es lo que haria un lanzador a secas.
            self._spawn("bspc node %s -f" % carga)
            sources.frec_bump("win:" + titulo)
            return

        sources.frec_bump(carga)
        self._spawn(carga)

    def _captura_accion(self, acc):
        """Abrir, ver la carpeta o borrar la captura que se ensena."""
        act = self.activities.get("captura")
        if act is None:
            return
        ruta = act.data.get("path") or ""
        self.activities.pop("captura", None)
        if acc == "abrir" and ruta:
            self._spawn("%s %s" % (C.CMD_VISOR, shlex.quote(ruta)))
        elif acc == "carpeta":
            self._spawn("%s %s" % (C.CMD_CARPETA,
                                   shlex.quote(C.CAPTURA_DIR)))
        elif acc == "borrar":
            try:
                os.unlink(ruta)
                aviso = "Borrada"
            except OSError:
                aviso = "No se pudo borrar"
            # Se dice que se borro. Un fichero que desaparece sin mas
            # deja la duda de si llego a borrarse, y encima la copia
            # del portapapeles sigue ahi.
            self.on_event({"kind": "notify", "app": "Captura",
                           "body": aviso})
            return
        self.refresh()

    def _spawn(self, cmd):
        try:
            GLib.spawn_async(["/bin/sh", "-c", cmd],
                             flags=GLib.SpawnFlags.SEARCH_PATH)
        except Exception:
            self.on_event({"kind": "notify", "app": "Lanzador",
                           "body": "No se pudo ejecutar"})

    # ------------------------------------------------ selector de emoji

    def _start_emoji(self):
        if not sources.emoji_index():
            # Sin la lista de Unicode no hay nada que enseñar. Se dice en
            # vez de abrir una rejilla vacia, y se dice DONDE buscarla.
            self.on_event({"kind": "notify", "app": "Emoji",
                           "body": "Falta %s (paquete unicode-data)"
                                   % os.path.basename(C.EMOJI_DATA)})
            self.refresh()
            return

        # La ventana de destino se mira AHORA, antes de capturar el
        # teclado: es la que tenias delante al pulsar el atajo, y es
        # donde va a caer el emoji. Mirarla al insertar daria la ventana
        # equivocada si algo le robo el foco mientras elegias.
        self.emo_destino = sources.ventana_enfocada()
        self.emo = {"q": "", "sel": 0, "top": 0,
                    "res": sources.emoji_buscar("")}
        self.activities["panel"] = Activity(
            "panel", 50, None, {"which": "emoji"}, "panel")

        def fallo():
            self.emo = None
            self.activities.pop("panel", None)
            self.on_event({"kind": "notify", "app": "Emoji",
                           "body": "No se pudo capturar el teclado"})
            self.refresh()

        self._grab_retry(Gdk.SeatCapabilities.KEYBOARD
                         | Gdk.SeatCapabilities.ALL_POINTING, fallo)
        self._blink_on()
        self.refresh()

    def _emo_vista(self):
        """Deja visible la fila del seleccionado.

        La rejilla no se desplaza sola con la seleccion: solo cuando
        esta se sale por arriba o por abajo, y entonces lo justo para
        volver a entrar. Recentrarla en cada tecla haria que el
        contenido se moviese mientras la vista se queda quieta, que es
        lo contrario de lo que espera quien mira.
        """
        st = self.emo
        total = len(st["res"])
        filas = (total + T.EMO_COLS - 1) // T.EMO_COLS
        st["sel"] = max(0, min(st["sel"], total - 1))
        fila = st["sel"] // T.EMO_COLS
        if fila < st["top"]:
            st["top"] = fila
        elif fila >= st["top"] + T.EMO_FILAS:
            st["top"] = fila - T.EMO_FILAS + 1
        st["top"] = max(0, min(st["top"], max(0, filas - T.EMO_FILAS)))

    @staticmethod
    def _emo_cats(res):
        """[(etiqueta, indice donde empieza)] en el orden de la lista.

        Se calcula de la propia lista y no de una tabla fija: asi
        "Recientes" aparece solo cuando hay algo usado, y el orden es
        siempre el mismo que ve la rejilla.
        """
        cats = []
        for i, e in enumerate(res):
            if not cats or e[2] != cats[-1][0]:
                cats.append((e[2], i))
        return cats

    def _emo_ir(self, indice):
        """Lleva la seleccion ahi y pone ESA fila arriba del todo.

        _emo_vista solo desplaza lo justo para que se vea, que es lo que
        quieren las flechas; pero al saltar a una categoria dejaria su
        primera fila pegada abajo, con el grupo anterior ocupando la
        rejilla. Saltar a un sitio es empezar a mirar ahi.
        """
        st = self.emo
        st["sel"] = max(0, min(indice, len(st["res"]) - 1))
        filas = (len(st["res"]) + T.EMO_COLS - 1) // T.EMO_COLS
        st["top"] = max(0, min(st["sel"] // T.EMO_COLS,
                               max(0, filas - T.EMO_FILAS)))

    def _emo_grupo(self, paso):
        """Salta al primer emoji del grupo siguiente o anterior."""
        st = self.emo
        res = st["res"]
        # Los indices donde cambia la etiqueta: son los comienzos de
        # grupo. Se calculan aqui y no se guardan porque la lista cambia
        # con cada letra que se escribe.
        inicios = [0] + [i for i in range(1, len(res))
                         if res[i][2] != res[i - 1][2]]
        if paso > 0:
            self._emo_ir(next((i for i in inicios if i > st["sel"]),
                              inicios[-1]))
        else:
            previos = [i for i in inicios if i < st["sel"]]
            self._emo_ir(previos[-1] if previos else 0)

    def build_emoji(self, cr):
        st = self.emo or {"q": "", "sel": 0, "top": 0, "res": []}
        res = st["res"]
        ANCHO = T.EMO_ANCHO

        cab = R.Row().add(
            self._ico("search", 28, T.DIM, T.G_SEARCH),
            R.Gap(T.GAP_ITEM),
            R.Field(ANCHO - 28 - T.GAP_ITEM, st["q"], T.F_SUB, T.FG,
                    caret=self.caret_on, secret=False))
        if not res:
            return R.Stack([cab, R.Row().add(
                R.Gap(T.GAP_ITEM),
                R.Text("Ning\u00fan emoji se llama as\u00ed", T.F_SUB, T.DIM2))],
                gap=T.GAP_ROW)

        sel = min(st["sel"], len(res) - 1)
        # Solo las filas que tengan algo. Buscando "fuego" salen ocho
        # emoji, y cuatro filas vacias debajo serian un panel de 400 px
        # con una sola fila dentro: el panel se ajusta a su contenido,
        # como el del wifi con dos redes.
        filas = (len(res) + T.EMO_COLS - 1) // T.EMO_COLS
        rejilla = []
        for f in range(st["top"], min(st["top"] + T.EMO_FILAS, filas)):
            fila = R.Row()
            for c in range(T.EMO_COLS):
                i = f * T.EMO_COLS + c
                if i >= len(res):
                    # Lo que falta de la ULTIMA fila si va como hueco del
                    # ancho de una celda: sin el, la fila mediria menos y
                    # la isla se estrecharia al llegar al final de la
                    # lista.
                    fila.add(R.Gap(T.EMO_CELDA))
                    continue
                # SURF_2 y no el SURF_1 de las filas del lanzador: alli
                # el realce es una banda de 560 px y con muy poco
                # contraste ya se ve, aqui es un cuadrado de 52 y al
                # mismo tono no se encontraba de un vistazo.
                fila.add(R.Cell(R.Emoji(res[i][0]),
                                T.EMO_CELDA, T.EMO_CELDA,
                                bg=T.SURF_2 if i == sel else None,
                                tag="emo:%d" % i))
            rejilla.append(fila)

        nombre = R.Text(self._clip(res[sel][1], 32), T.F_SMALL, T.FG)
        grupo = R.Text(res[sel][2], T.F_SMALL, T.DIM2)
        hueco = max(10, ANCHO - nombre.size(cr)[0] - grupo.size(cr)[0])

        partes = [cab, R.Stack(rejilla, gap=0)]
        # Con busqueda NO hay barra de categorias: los resultados vienen
        # de toda la lista y mezclados, asi que una barra ahi senalaria
        # a grupos que ya no estructuran nada.
        partes.append(R.Rule(ANCHO, T.DIM2))
        if not st["q"]:
            # Debajo del filete y no encima: asi la barra pertenece al
            # pie --con el nombre y la ayuda- en vez de colgar de la
            # ultima fila de la rejilla, que es donde se veia pegada.
            partes.append(self._emo_barra(cr, res, sel, ANCHO))
        partes.append(R.Row([nombre, R.Gap(hueco), grupo]))
        partes.append(R.Row().add(R.Text(
            "\u2190\u2192\u2191\u2193 mover \u00b7 \u21e5 categor\u00eda "
            "\u00b7 \u23ce insertar \u00b7 esc cerrar",
            T.F_SMALL, T.DIM2)))
        return R.Stack(partes, gap=10)

    def _emo_barra(self, cr, res, sel, ancho):
        """Las categorias, abajo, como en el teclado de iOS."""
        cats = self._emo_cats(res)
        # La activa es la ULTIMA que empieza en o antes de la seleccion.
        activa = 0
        for n, (_etq, ini) in enumerate(cats):
            if ini <= sel:
                activa = n
        fila = R.Row()
        celda = min(T.EMO_CAT_CELDA, ancho / float(max(1, len(cats))))
        for n, (etq, _ini) in enumerate(cats):
            icono = T.EMO_CATS.get(etq)
            dibujo = (R.Emoji(icono, alpha=1.0 if n == activa
                              else T.EMO_CAT_ALFA)
                      if icono else R.Text(etq[:2], T.F_SMALL, T.DIM))
            fila.add(R.Cell(dibujo, celda, celda,
                            bg=T.SURF_2 if n == activa else None,
                            radius=12, tag="cat:%d" % n))
        # Centrada bajo la rejilla: las categorias son menos anchas que
        # las diez columnas y pegadas a la izquierda se verian sueltas.
        sobra = max(0.0, ancho - celda * len(cats))
        return R.Row([R.Gap(sobra / 2.0), fila])

    def _key_emoji(self, ev):
        if self._atajo_propio(ev, "emoji"):
            return True
        st = self.emo
        kv = ev.keyval
        pag = T.EMO_COLS * T.EMO_FILAS
        if kv == Gdk.KEY_Escape:
            self._close_panel()
            self.refresh()
            return True
        if kv in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self._emoji_sel()
            return True
        if kv == Gdk.KEY_Right:
            st["sel"] += 1
        elif kv == Gdk.KEY_Left:
            st["sel"] -= 1
        elif kv == Gdk.KEY_Down:
            # En la ultima fila incompleta, bajar lleva al final de la
            # lista en vez de no hacer nada: es el gesto de "lo de mas
            # abajo", y quedarse quieto se lee como que la tecla no va.
            st["sel"] = (st["sel"] + T.EMO_COLS
                         if st["sel"] + T.EMO_COLS < len(st["res"])
                         else len(st["res"]) - 1)
        elif kv == Gdk.KEY_Up:
            if st["sel"] >= T.EMO_COLS:
                st["sel"] -= T.EMO_COLS
        elif kv in (Gdk.KEY_Page_Down, Gdk.KEY_Next):
            st["sel"] += pag
        elif kv in (Gdk.KEY_Page_Up, Gdk.KEY_Prior):
            st["sel"] -= pag
        elif kv == Gdk.KEY_Home:
            st["sel"] = 0
        elif kv == Gdk.KEY_End:
            st["sel"] = len(st["res"]) - 1
        elif kv == Gdk.KEY_Tab:
            self._emo_grupo(+1)
        elif kv == Gdk.KEY_ISO_Left_Tab:
            self._emo_grupo(-1)
        elif kv == Gdk.KEY_BackSpace:
            st["q"] = st["q"][:-1]
            st["res"] = sources.emoji_buscar(st["q"])
            st["sel"] = st["top"] = 0
        else:
            ch = Gdk.keyval_to_unicode(kv)
            if ch < 32:
                return True
            st["q"] += chr(ch)
            st["res"] = sources.emoji_buscar(st["q"])
            st["sel"] = st["top"] = 0
        self._emo_vista()
        self.refresh()
        return True

    def _emoji_sel(self):
        st = self.emo
        if not st or not st["res"]:
            return
        ch, nombre = st["res"][min(st["sel"], len(st["res"]) - 1)][:2]
        destino = self.emo_destino
        self._close_panel()
        self.refresh()
        sources.frec_bump("emoji:" + ch)

        # El pegado es una pulsacion sintetica de Ctrl+V, asi que la
        # captura del teclado tiene que estar DE VERDAD soltada antes de
        # mandarla: si no, se la come la propia isla. _close_panel se lo
        # pide a X, y sync espera a que X lo haya hecho. Es lo mismo que
        # un retardo de cortesia, pero medido por el servidor en vez de
        # adivinado.
        gd = self.get_display()
        if gd is not None:
            gd.sync()

        def trabajo():
            # En un hilo: son ~100 ms de xclip y xdotool, y pagarlos en
            # el hilo de GTK se veria como un tiron justo en la
            # animacion de cierre.
            como = sources.pegar(ch, destino)
            GLib.idle_add(self._tras_emoji, ch, nombre, como)
        threading.Thread(target=trabajo, daemon=True).start()

    def _tras_emoji(self, ch, nombre, como):
        if como == "escrito":
            # Ya esta donde querias: avisar de lo que acabas de ver
            # aparecer solo seria ruido.
            return False
        self.on_event({"kind": "notify", "app": "Emoji",
                       "body": ("%s %s copiado" % (ch, nombre))
                               if como == "portapapeles"
                               else "No se pudo copiar %s" % ch})
        return False

    # ------------------------------------------ historial del portapapeles

    def _start_port(self):
        # La ventana de destino, ANTES de capturar el teclado: es donde
        # va a caer lo que elijas, igual que en el selector de emoji.
        self.emo_destino = sources.ventana_enfocada()
        self.port = {"q": "", "sel": 0, "res": self.portapapeles.lista()}
        self.activities["panel"] = Activity(
            "panel", 50, None, {"which": "portapapeles"}, "panel")

        def fallo():
            self.port = None
            self.activities.pop("panel", None)
            self.on_event({"kind": "notify", "app": "Portapapeles",
                           "body": "No se pudo capturar el teclado"})
            self.refresh()

        self._grab_retry(Gdk.SeatCapabilities.KEYBOARD
                         | Gdk.SeatCapabilities.ALL_POINTING, fallo)
        self._blink_on()
        self.refresh()

    def build_port(self, cr):
        st = self.port or {"q": "", "sel": 0, "res": []}
        res = st["res"]
        ANCHO = 620

        cab = R.Row().add(
            self._ico("clip", 28, T.DIM, T.G_CLIP),
            R.Gap(T.GAP_ITEM),
            R.Field(ANCHO - 28 - T.GAP_ITEM, st["q"], T.F_SUB, T.FG,
                    caret=self.caret_on, secret=False))
        filas = [cab]

        if not res:
            # Dos vacios distintos, y la diferencia importa: uno se
            # arregla copiando algo y el otro borrando lo que buscas.
            filas.append(R.Row().add(
                R.Gap(T.GAP_ITEM),
                R.Text("Nada copiado todav\u00eda" if not st["q"]
                       else "Nada que case con eso", T.F_SUB, T.DIM2)))
            return R.Stack(filas, gap=T.GAP_ROW)

        sel = min(st["sel"], len(res) - 1)
        filas.append(self._port_hero(cr, res[sel], ANCHO))
        filas.append(R.Rule(ANCHO, T.DIM2))

        for i, txt in enumerate(res[:T.PP_FILAS]):
            filas.append(self._port_fila(cr, i, txt, i == sel, ANCHO))

        filas.append(R.Row().add(R.Text(
            "\u2191\u2193 mover \u00b7 1-9 pegar \u00b7 ^P fijar \u00b7 "
            "\u2326 olvidar \u00b7 \u23ce pegar", T.F_SMALL, T.DIM2)))
        return R.Stack(filas, gap=10)

    @staticmethod
    def _port_fuente(tipo, grande=False):
        """Monoespaciada para lo que es codigo, proporcional para prosa."""
        if tipo in T.PP_MONO:
            fam, peso, px = T.F_MONO
            return (fam, peso, px + 3) if grande else T.F_MONO
        return T.F_BODY if grande else T.F_SMALL

    def _port_hero(self, cr, txt, ancho):
        """Lo seleccionado, entero y sin aplastar en una linea.

        Es la diferencia entre ver 58 caracteres y ver lo que vas a
        pegar: con dos rutas largas que empiezan igual, la lista sola no
        te deja distinguirlas.
        """
        tipo = sources.clip_tipo(txt)
        fuente = self._port_fuente(tipo, grande=True)
        ancho_car = 46 if tipo in T.PP_MONO else 52
        lineas = []
        for cruda in txt.splitlines() or [""]:
            lineas.extend(textwrap.wrap(cruda, ancho_car) or [""])
            if len(lineas) > T.PP_LINEAS:
                break
        if len(lineas) > T.PP_LINEAS:
            lineas = lineas[:T.PP_LINEAS]
            lineas[-1] = lineas[-1].rstrip() + "\u2026"

        cuerpo = R.Stack([R.Row().add(R.Text(l, fuente, T.FG))
                          for l in lineas], gap=5)
        # Un color se ensena, no se lee: el #0A84FF de al lado no dice
        # nada y la muestra si.
        rgb = sources.clip_color(txt) if tipo == "color" else None
        if rgb is not None:
            cuerpo = R.Row([R.Swatch(34, rgb), R.Gap(16), cuerpo])

        _g, etiqueta = T.PP_TIPOS.get(tipo, T.PP_TIPOS["texto"])
        n_lineas = len(txt.splitlines())
        datos = [etiqueta]
        if n_lineas > 1:
            datos.append("%d l\u00edneas" % n_lineas)
        datos.append("%d caracteres" % len(txt))
        edad = sources.clip_edad(self.portapapeles.edad(txt))
        if edad:
            datos.append(edad)
        if txt in self.portapapeles.fijados:
            datos.append("fijado")
        return R.Stack([
            cuerpo,
            R.Row().add(R.Text(" \u00b7 ".join(datos), T.F_SMALL, T.DIM)),
        ], gap=10)

    def _port_fila(self, cr, i, txt, activa, ancho):
        tipo = sources.clip_tipo(txt)
        glifo, etiqueta = T.PP_TIPOS.get(tipo, T.PP_TIPOS["texto"])
        col = T.FG if activa else T.DIM

        # El numero no es adorno: es el atajo. Pulsar 3 pega el tercero
        # sin tener que bajar con las flechas.
        # La chincheta NO ocupa el sitio del numero: el numero es el
        # atajo para pegar, y quitandoselo a la primera fila la lista
        # empezaba en 2 y no habia forma de saber que tecla pegaba esa.
        # Va junto a la etiqueta, que es donde se leen las propiedades
        # de la fila.
        fijo = txt in self.portapapeles.fijados
        num = R.Text("%d" % (i + 1), T.F_SMALL,
                     T.ACCENT if activa else T.DIM2)
        rgb = sources.clip_color(txt) if tipo == "color" else None
        cabeza = (R.Swatch(18, rgb) if rgb is not None
                  else self._ico(glifo, 20, T.DIM2 if not activa else T.DIM))

        una = " ".join(txt.split())
        cuerpo = R.Text(self._clip(una, 44), self._port_fuente(tipo), col)
        etq = R.Row([self._ico(T.G_PIN, 16, T.ACCENT), R.Gap(8),
                     R.Text(etiqueta, T.F_SMALL, T.DIM)]) if fijo \
            else R.Text(etiqueta, T.F_SMALL, T.DIM2)
        hueco = max(10, ancho - 2 * 12 - 20 - 3 * T.GAP_ITEM
                    - num.size(cr)[0] - cabeza.size(cr)[0]
                    - cuerpo.size(cr)[0] - etq.size(cr)[0])
        fila = R.Row([num, R.Gap(T.GAP_ITEM), cabeza, R.Gap(T.GAP_ITEM),
                      cuerpo, R.Gap(hueco), etq])
        return R.Box(fila, bg=T.SURF_1 if activa else None,
                     w=ancho, padx=12, pady=7, tag="pp:%d" % i)

    def _key_port(self, ev):
        if self._atajo_propio(ev, "portapapeles"):
            return True
        st = self.port
        kv = ev.keyval
        if kv == Gdk.KEY_Escape:
            self._close_panel()
            self.refresh()
            return True
        if kv in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self._port_sel()
            return True
        if kv in (Gdk.KEY_Delete, Gdk.KEY_KP_Delete):
            # Olvidar sin cerrar el panel: un historial del que no se
            # puede sacar nada acaba lleno de cosas que no quieres ver.
            if st["res"]:
                self.portapapeles.borrar(
                    st["res"][min(st["sel"], len(st["res"]) - 1)])
                st["res"] = self._port_res(st["q"])
                st["sel"] = min(st["sel"], max(0, len(st["res"]) - 1))
            self.refresh()
            return True
        if kv in (Gdk.KEY_p, Gdk.KEY_P) and (ev.state
                                             & Gdk.ModifierType.CONTROL_MASK):
            # Ctrl+P y no "p" a secas: las letras van al filtro. Fijar
            # no cierra el panel, que lo normal es fijar y seguir
            # mirando.
            if st["res"]:
                elegido = st["res"][min(st["sel"], len(st["res"]) - 1)]
                self.portapapeles.fijar(elegido)
                st["res"] = self._port_res(st["q"])
                if elegido in st["res"]:
                    st["sel"] = st["res"].index(elegido)
            self.refresh()
            return True
        if Gdk.KEY_1 <= kv <= Gdk.KEY_9 and not st["q"]:
            # Los numeros pegan directo, pero SOLO sin busqueda: si no,
            # escribir "3 cosas" en el filtro pegaria la tercera en vez
            # de escribirse.
            i = kv - Gdk.KEY_1
            if i < len(st["res"]):
                st["sel"] = i
                self._port_sel()
            return True
        if kv in (Gdk.KEY_Down, Gdk.KEY_Tab):
            st["sel"] = min(len(st["res"]) - 1, st["sel"] + 1)
        elif kv in (Gdk.KEY_Up, Gdk.KEY_ISO_Left_Tab):
            st["sel"] = max(0, st["sel"] - 1)
        elif kv == Gdk.KEY_BackSpace:
            st["q"] = st["q"][:-1]
            st["res"] = self._port_res(st["q"])
            st["sel"] = 0
        else:
            ch = Gdk.keyval_to_unicode(kv)
            if ch < 32:
                return True
            st["q"] += chr(ch)
            st["res"] = self._port_res(st["q"])
            st["sel"] = 0
        self.refresh()
        return True

    def _port_res(self, q):
        if not q.strip():
            return self.portapapeles.lista()
        return self.portapapeles.busca(q, T.PP_FILAS)

    def _port_sel(self):
        st = self.port
        if not st or not st["res"]:
            return
        txt = st["res"][min(st["sel"], len(st["res"]) - 1)]
        destino = self.emo_destino
        self._close_panel()
        self.refresh()

        # Igual que al insertar un emoji: la captura del teclado tiene
        # que estar soltada DE VERDAD antes de mandar el Ctrl+V, o se lo
        # come la propia isla. sync espera a que X lo haya hecho.
        gd = self.get_display()
        if gd is not None:
            gd.sync()

        def trabajo():
            como = sources.pegar(txt, destino)
            GLib.idle_add(self._tras_port, txt, como)
        threading.Thread(target=trabajo, daemon=True).start()

    def _tras_port(self, txt, como):
        if como == "escrito":
            return False
        self.on_event({"kind": "notify", "app": "Portapapeles",
                       "body": self._clip(" ".join(txt.split()), 60)
                               if como == "portapapeles"
                               else "No se pudo pegar"})
        return False

    def open_panel(self, which):
        act = self.activities.get("panel")
        if act is not None and act.data.get("which") == which:
            self._close_panel()                    # el mismo icono cierra
        elif which == "launcher":
            self._start_launcher()                 # necesita teclado
        elif which == "emoji":
            self._start_emoji()                    # tambien
        elif which == "portapapeles":
            self._start_port()                     # y este
        else:
            # volumen y energia caben en una fila: pildora alta en vez
            # de panel, que reserva padding vertical de tarjeta.
            mode = "pillx" if which in ("volume", "battery") else "panel"
            if which == "calendar":
                self.cal_off = 0        # se abre siempre en el mes actual
            self.activities["panel"] = Activity(
                "panel", 50, 8.0, {"which": which}, mode)
            self._grab(Gdk.SeatCapabilities.ALL_POINTING)
            if which == "volume":
                # Relectura puntual: el sondeo periodico es lento (15 s)
                # a proposito, pero al abrir el panel el dato tiene que
                # estar al dia.
                self.sys.refresh()
            if which == "wifi":
                self.wifi_nets = None
                controls.wifi_scan(self._on_wifi)
        self.refresh()

    def _on_wifi(self, nets):
        self.wifi_nets = nets
        self.known = controls.known_networks()
        self._touch_panel()
        self.refresh()
        return False

    # --------------------------------------------- captura de dispositivos

    def _grab(self, caps):
        """Captura puntero y/o teclado para el seat.

        Con el puntero capturado los clics de FUERA de la isla llegan
        aqui en vez de irse a la ventana de debajo: es lo que permite
        cerrar un panel pulsando en cualquier sitio, como un menu
        normal. La ventana es un DOCK sin foco, asi que sin captura no
        hay otra forma de enterarse.
        """
        self._ungrab()
        try:
            seat = self.get_display().get_default_seat()
            st = seat.grab(self.get_window(), caps, False,
                           None, None, None, None)
            self._grab_status = st
            self._seat = seat if st == Gdk.GrabStatus.SUCCESS else None
        except Exception:
            self._grab_status = None
            self._seat = None
        if self._seat is not None:
            self._arm_guard()
        return self._seat is not None

    def _grab_retry(self, caps, on_fail, intentos=20):
        """Insiste con la captura hasta que X la conceda.

        Al disparar el atajo desde sxhkd, X mantiene una captura activa
        de teclado para esa combinacion HASTA QUE SE SUELTAN LAS TECLAS,
        asi que el primer intento se rechaza con AlreadyGrabbed. Por eso
        abrir el panel con island-send funcionaba y con super+d no.
        Reintentar cada 25 ms durante medio segundo cubre de sobra lo que
        tarda cualquiera en levantar los dedos.
        """
        if self._grab(caps):
            return True
        if intentos <= 0:
            on_fail()
            return False

        def otra_vez():
            self._grab_retry(caps, on_fail, intentos - 1)
            return False

        GLib.timeout_add(25, otra_vez)
        return False

    def _arm_guard(self):
        """Perro guardian de la captura, por INACTIVIDAD.

        Si algo dejase el proceso colgado con el teclado o el puntero
        capturados, quedarian inservibles; a los 20 s se sueltan pase lo
        que pase. Pero el plazo se reinicia con cada tecla o clic: con un
        temporizador fijo desde el inicio, el lanzador se cerraria solo a
        mitad de una busqueda que durase mas de 20 s.
        """
        g = getattr(self, "_grab_guard", None)
        if g:
            GLib.source_remove(g)
        self._grab_guard = GLib.timeout_add_seconds(20, self._grab_timeout)

    def _ungrab(self):
        if getattr(self, "_seat", None) is not None:
            try:
                self._seat.ungrab()
            except Exception:
                pass
            self._seat = None
        g = getattr(self, "_grab_guard", None)
        if g:
            GLib.source_remove(g)
            self._grab_guard = None

    def _grab_timeout(self):
        self._grab_guard = None
        self._close_panel()
        self.refresh()
        return False

    def _close_panel(self):
        """Unica salida de un panel: suelta la captura, para el cursor
        del campo y descarta la actividad."""
        self.pw = None
        self.launch = None
        self.emo = None
        self.port = None
        self._blink_off()
        self._ungrab()
        self.activities.pop("panel", None)

    # ------------------------------------------------- campo de contrasena

    def _start_pw(self, ssid):
        self.pw = {"ssid": ssid, "text": "", "error": False,
                   "ver": False, "estado": ""}
        self.activities["panel"] = Activity(
            "panel", 50, None, {"which": "wifi-pw"}, "panel")

        # Teclado Y puntero a la vez, en UNA sola llamada: pedirlos por
        # separado haria que la segunda captura soltase la primera.
        def fallo():
            # Sin teclado no hay forma de escribir: mejor decirlo que
            # dejar un campo muerto en el que el usuario teclea en vano.
            self.pw = None
            self.activities.pop("panel", None)
            self.on_event({"kind": "notify", "app": "Wi-Fi",
                           "body": "No se pudo capturar el teclado"})
            self.refresh()

        self._grab_retry(Gdk.SeatCapabilities.KEYBOARD
                         | Gdk.SeatCapabilities.ALL_POINTING, fallo)
        self._blink_on()
        self.refresh()

    def _blink_on(self):
        """Arranca el parpadeo del cursor, cancelando el anterior.

        Cancelar primero no es limpieza: abrir un panel con otro ya
        abierto dejaba vivo el temporizador viejo, y con dos el cursor
        parpadeaba al doble. Ademas _blink_id es una sola casilla, asi
        que el segundo pisaba al primero y el primero, al quitarse solo
        mas tarde, borraba la casilla del segundo. De ahi los avisos de
        GLib al cerrar un panel.
        """
        self._blink_off()
        self.caret_on = True
        self._blink_id = GLib.timeout_add(530, self._blink)

    def _blink_off(self):
        if self._blink_id is not None:
            GLib.source_remove(self._blink_id)
            self._blink_id = None

    def _blink(self):
        """Parpadeo del cursor de los campos de texto.

        La lista de paneles con campo tiene que estar COMPLETA: se
        quedo en el lanzador y el wifi, asi que en el selector de emoji
        y en el portapapeles el cursor se congelaba al primer parpadeo,
        porque el temporizador se quitaba solo al devolver False.
        """
        self.caret_on = not self.caret_on
        self._damage()
        vivo = any(x is not None for x in (self.pw, self.launch,
                                           self.emo, self.port))
        if not vivo:
            self._blink_id = None      # se quita solo: la casilla tambien
        return vivo

    def on_key(self, widget, ev):
        if self._seat is not None:
            self._arm_guard()
        if self.launch is not None:
            return self._key_launcher(ev)
        if self.emo is not None:
            return self._key_emoji(ev)
        if self.port is not None:
            return self._key_port(ev)
        if self.pw is None:
            return False
        kv = ev.keyval
        if self.pw.get("estado") == "conectando":
            # Mientras conecta solo se admite rendirse: escribir ahi no
            # llevaria a ninguna parte y Intro lanzaria un segundo
            # nmcli contra la misma red.
            if kv == Gdk.KEY_Escape:
                self._close_panel()
                self.refresh()
            return True
        if kv in (Gdk.KEY_Caps_Lock, Gdk.KEY_Shift_Lock):
            # Se repinta para que el aviso aparezca o desaparezca en el
            # acto: es un estado del teclado, no del campo.
            self.refresh()
            return True
        if kv in (Gdk.KEY_h, Gdk.KEY_H) and (ev.state
                                             & Gdk.ModifierType.CONTROL_MASK):
            self.pw["ver"] = not self.pw.get("ver")
            self.refresh()
            return True
        if kv == Gdk.KEY_Escape:
            self._close_panel()
            self.refresh()
        elif kv in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            ssid, text = self.pw["ssid"], self.pw["text"]
            if text:
                # El panel NO se cierra: se queda enseñando que esta
                # conectando. Cerrarlo y avisar al final dejaba varios
                # segundos sin saber si se habia enterado.
                self.pw["estado"] = "conectando"
                self.pw["error"] = False
                self.refresh()
                self.ensure_tick()
                controls.wifi_connect_pw(ssid, text, self._after_wifi)
        elif kv == Gdk.KEY_BackSpace:
            self.pw["text"] = self.pw["text"][:-1]
            self.pw["error"] = False
            self.refresh()
        else:
            ch = Gdk.keyval_to_unicode(kv)
            if ch >= 32:
                self.pw["text"] += chr(ch)
                self.pw["error"] = False
                self.refresh()
        return True

    def _atajo_propio(self, ev, panel):
        """Gestiona una pulsacion CON super mientras hay panel abierto.

        Devuelve True si ya esta tratada. Dos cosas, y las dos hacen
        falta: si es el mismo atajo que lo abrio, se cierra; y en
        cualquier caso no se escribe en el campo, porque con super
        pulsado lo que hay es un atajo, no texto.
        """
        if not (ev.state & Gdk.ModifierType.MOD4_MASK):
            return False
        nombre = C.PANEL_TECLA.get(panel)
        if nombre and ev.keyval == Gdk.keyval_from_name(nombre):
            self._close_panel()
            self.refresh()
        return True

    def _key_launcher(self, ev):
        if self._atajo_propio(ev, "launcher"):
            return True
        st = self.launch
        kv = ev.keyval
        if kv == Gdk.KEY_Escape:
            self._close_panel()
            self.refresh()
            return True
        if kv in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self._launch_sel()
            return True
        if kv in (Gdk.KEY_Down, Gdk.KEY_Tab):
            st["sel"] = min(len(st["res"]) - 1, st["sel"] + 1)
        elif kv in (Gdk.KEY_Up, Gdk.KEY_ISO_Left_Tab):
            st["sel"] = max(0, st["sel"] - 1)
        elif kv == Gdk.KEY_BackSpace:
            st["q"] = st["q"][:-1]
            st["res"] = self._results(st["q"])
            st["sel"] = 0
        else:
            ch = Gdk.keyval_to_unicode(kv)
            if ch < 32:
                return True
            st["q"] += chr(ch)
            st["res"] = self._results(st["q"])
            # Al cambiar la busqueda la seleccion vuelve arriba: dejarla
            # donde estaba apuntaria a un resultado distinto del que el
            # usuario tenia delante.
            st["sel"] = 0
        self.refresh()
        return True

    def _touch_panel(self, extra=8.0):
        """Cada interaccion aplaza el cierre: si no, el panel se cerraria
        en mitad de un arrastre del volumen."""
        act = self.activities.get("panel")
        if act is not None:
            act.expires = time.monotonic() + extra

    @staticmethod
    def _clip(s, n):
        s = " ".join((s or "").split())
        return s if len(s) <= n else s[:n - 1] + "…"

    # ------------------------------------------------------------ estado

    def refresh(self, initial=False):
        self._prof["refresh"] += 1
        cr = self._measure_ctx()
        key, mode, item = self.build(cr)
        w, h = item.size(cr)
        pad = {"card": T.PAD_CARD, "panel": T.PAD_PANEL,
               "pillx": T.PAD_CARD}.get(mode, T.PAD_PILL)
        target_w = w + 2 * pad
        if mode == "pillx":
            target_h = T.H_PILL_LG
        elif mode == "panel":
            # El panel se ajusta a su contenido: la lista de wifi no mide
            # lo mismo con dos redes que con cinco.
            target_h = max(T.H_COMPACT, h + 2 * T.PANEL_PAD)
        elif mode == "card":
            target_h = T.H_CARD
        else:
            target_h = T.H_COMPACT

        if key != self.state_key:
            # Cambio de estado: cruza el contenido viejo con el nuevo.
            self.prev_content = self.content
            self._pw = getattr(self, "_cw", 0.0)
            # Las zonas del contenido anterior desaparecen con el; dejar
            # el realce vivo lo haria quedarse flotando sobre nada.
            self.hover = None
            self.sp_ha.snap(0.0)
            self.sp_fade.snap(0.0)
            self.sp_fade.set(1.0)
            self.state_key = key
        self.content = item
        # El ancho ya se acaba de medir aqui: guardarlo evita que el
        # dibujado vuelva a recorrer el arbol entero en CADA fotograma
        # para saber donde centrarlo. A 120 Hz eso son 120 recorridos
        # por segundo de algo que solo cambia cuando cambia el
        # contenido.
        self._cw = w

        if self.activities:
            self._mostrar()
        elif T.AUTOHIDE and not self.oculto and self._hide_id is None:
            # Se acabo lo que habia que ensenar. Hasta ahora el repliegue
            # solo se programaba al salir el raton o al cambiar de
            # escritorio, asi que al caducar una notificacion el notch se
            # quedaba abajo hasta que lo rozabas. Se nota sobre todo
            # encadenando capturas: la tarjeta de la anterior salia en la
            # foto siguiente.
            self._programar_ocultado()
        if ((T.WS_ANIM and not self.sp_wsx.settled)
                or (T.WS_POP and not self.sp_pop.settled)):
            self.ensure_tick()
        self._schedule_expiry()
        self.sp_w.set(target_w)
        self.sp_h.set(target_h)
        self.update_input_region()
        if initial:
            self.sp_w.snap(target_w)
            self.sp_h.snap(target_h)
            self.sp_fade.snap(1.0)
        self.ensure_tick()
        self._damage()

    def _schedule_expiry(self):
        """Temporizador exacto para el repliegue.

        No basta con mirar la caducidad dentro del bucle de animacion:
        ese bucle se PARA en cuanto los muelles se asientan, asi que una
        actividad ya expandida y quieta no tendria quien la cerrase, y
        el repliegue quedaba colgando del tick de reloj -- hasta 1 s
        tarde. Aqui se programa al milisegundo de su vencimiento.
        """
        if self._exp_id is not None:
            GLib.source_remove(self._exp_id)
            self._exp_id = None
        times = [a.expires for a in self.activities.values()
                 if a.expires is not None]
        if not times:
            return
        delay = max(0.0, min(times) - time.monotonic())
        self._exp_id = GLib.timeout_add(int(delay * 1000) + 16, self._on_expiry)

    def _on_expiry(self):
        self._exp_id = None
        self.refresh()
        return False

    # --------------------------------------------------------- animacion

    def _damage(self):
        """Redibuja solo la franja de la isla.

        La ventana mide 2880x460 para que quepa el panel de wifi; pedir
        el redibujado entero serian 1,3 millones de pixeles por
        fotograma, a 60 fps, casi todos transparentes. Acotarlo a la
        zona util baja eso en mas de un orden de magnitud.
        """
        cw = max(self.sp_w.value, self.sp_w.target) + 40
        ch = max(self.sp_h.value, self.sp_h.target) + T.TOP + 40
        # Union con la zona del fotograma ANTERIOR: al encogerse la isla,
        # lo que se pinto antes cae fuera de la zona nueva y se quedaria
        # ahi sin que nadie lo borrase (aparecian restos del contenido
        # viejo flotando a los lados).
        w = max(cw, self._prev_dmg[0])
        h = max(ch, self._prev_dmg[1])
        self._prev_dmg = (cw, ch)
        rect = cairo.RectangleInt(int((self.W - w) / 2), 0,
                                  int(w) + 1, int(h) + 1)

        # Se pinta YA, sin pasar por la cola de GTK.
        #
        # Encolando el repintado (queue_draw_area), el bucle corria a
        # 120 y el dibujado seguia saliendo a 60: GTK agrupa lo
        # pendiente y lo sirve a su reloj de fotogramas, que en GTK3 son
        # 60 fijos. Se movian los muelles el doble de veces para ensenar
        # la mitad; medido, 117 vueltas por segundo y 58 dibujados.
        #
        # begin_draw_frame y no process_updates, que hace lo mismo pero
        # esta obsoleto desde GTK 3.22.
        gw = self.get_window()
        if gw is None:
            return
        try:
            ctx = gw.begin_draw_frame(cairo.Region(rect))
        except Exception:
            # Si el compositor no deja pintar ahora, se encola y que lo
            # sirva GTK cuando pueda: mas vale un fotograma tarde que
            # una excepcion en mitad de la animacion.
            self.queue_draw_area(rect.x, rect.y, rect.width, rect.height)
            return
        try:
            cr = ctx.get_cairo_context()
            cr.rectangle(rect.x, rect.y, rect.width, rect.height)
            cr.clip()
            self.on_draw(self, cr)
        finally:
            gw.end_draw_frame(ctx)

    def _periodo_ms(self):
        """Milisegundos entre fotogramas, segun el monitor.

        Se calcula una vez. GLib solo acepta milisegundos enteros, asi
        que 120 Hz son 8 y no 8,33: salen ~119 fotogramas por segundo,
        que es un 0,5% de mas y lo tira el compositor. Pedir 9 daria
        111, que si se nota.
        """
        if self._per_ms is None:
            hz = float(T.FPS)
            if hz <= 0:
                try:
                    pant = self.get_display().get_monitor_at_window(
                        self.get_window()) or self.get_display().get_monitor(0)
                    hz = (pant.get_refresh_rate() or 60000) / 1000.0
                except Exception:
                    hz = 60.0
            self._per_ms = max(1, int(round(1000.0 / max(1.0, hz))))
        return self._per_ms

    def ensure_tick(self):
        if self._tick_id is None:
            self._last = time.monotonic()
            self._tick_id = GLib.timeout_add(self._periodo_ms(),
                                             self._on_tick, None, None)

    def _on_tick(self, widget, clock):
        self._prof["tick"] += 1
        now = time.monotonic()
        dt = now - self._last
        self._last = now

        # Ciclo de 1.4 s: mas rapido parece nervioso, mas lento no se
        # lee como progreso.
        self.anim = (self.anim + dt / 1.4) % 1.0

        moving = False
        for s in (self.sp_w, self.sp_h, self.sp_fade, self.sp_y,
                  self.sp_hx, self.sp_hy, self.sp_hw, self.sp_hh, self.sp_ha,
                  self.sp_nivel):
            moving |= s.step(dt)
        for c in self._cont.values():
            if c.sp.step(dt):
                moving = True
            elif c.previo != c.actual:
                # Al terminar, el valor viejo se olvida: mientras se
                # recuerda, las casillas miden lo que el MAS ancho de
                # los dos y la cifra se queda con un hueco delante.
                c.previo = c.actual

        # Indicador de dictado. Se mira aparte del resto para enterarse
        # de CUANDO se asienta: mientras se desvanece sigue ocupando su
        # sitio en la fila, asi que el notch no puede encogerse hasta
        # que desaparece del todo, y eso pide una reconstruccion.
        act = self.current()
        for muelle, bandera in ((self.sp_mic, "_mic_en_fila"),
                                (self.sp_rec, "_rec_en_fila")):
            movio = muelle.step(dt)
            moving |= movio
            if (not movio and muelle.target == 0.0
                    and getattr(self, bandera, False)):
                setattr(self, bandera, False)
                self.refresh()

        # La onda persigue a los niveles que manda el microfono. Llegan
        # doce veces por segundo y esto corre a sesenta: sin perseguir,
        # la onda avanzaria a saltos de cinco fotogramas.
        #
        # Sube rapido y baja despacio, y la asimetria es deliberada:
        # grabando, la onda tiene que seguir a la voz sin retraso o deja
        # de ser la señal; al soltar, lo que se quiere es VER como el
        # microfono se cierra, y a 18 eso dura 200 ms, o sea nada.
        if len(self.dict_shown) == len(self.dict_levels):
            cerrando = (act is not None and act.kind == "dictado"
                        and (act.data.get("state") or "") == "transcribiendo")
            k = min(1.0, dt * (6.0 if cerrando else 18.0))
            for i, (visto, objetivo) in enumerate(zip(self.dict_shown,
                                                      self.dict_levels)):
                nuevo = visto + (objetivo - visto) * k
                if abs(nuevo - visto) > 0.002:
                    moving = True
                self.dict_shown[i] = nuevo
        if T.WS_ANIM and self.sp_wsx.step(dt):
            moving = True
            # El contenido se construye con el valor del muelle, asi que
            # hay que rehacerlo: no basta con repintar.
            self._ws_dirty = True
        if T.WS_POP and self.sp_pop.step(dt):
            moving = True
            self._ws_dirty = True

        # Una actividad puede caducar sin que llegue ningun evento, asi
        # que hay que mirar el reloj tambien aqui.
        if self.activities and any(not a.alive(now) for a in self.activities.values()):
            self.refresh()
            moving = True

        if getattr(self, "_ws_dirty", False):
            self._ws_dirty = False
            self.refresh()

        # Una animacion ciclica no "se asienta" nunca: mientras este en
        # pantalla hay que seguir pidiendo fotogramas.
        if act is not None and act.kind == "power" and act.data.get("charging"):
            moving = True
        # Conectando a una red: la barra indeterminada no se asienta
        # nunca, va y viene mientras dure nmcli.
        if self.pw is not None and self.pw.get("estado") == "conectando":
            moving = True
        # Mientras se dicta tampoco se asienta nada: la onda la mueve el
        # microfono y los puntos de "transcribiendo" laten solos.
        if act is not None and act.kind == "dictado" and \
                (act.data.get("state") or "oyendo") in ("oyendo", "transcribiendo"):
            moving = True

        self._damage()
        if not moving:
            self._tick_id = None
            self.update_input_region()
            return False
        return True

    # --------------------------------------------------------- dibujado

    def geom(self):
        w = max(self.sp_w.value, T.H_COMPACT)
        h = self.sp_h.value
        return (self.W - w) / 2.0, T.TOP + self.sp_y.value, w, h

    # ------------------------------------------------- auto-ocultado

    def _mostrar(self):
        self._al_frente()
        if self._hide_id:
            GLib.source_remove(self._hide_id)
            self._hide_id = None
        self.oculto = False
        self.sp_y.set(0.0)
        self.ensure_tick()

    def _quiza_ocultar(self):
        """Repliega solo si no hay nada que ensenar.

        Una notificacion o un panel abierto mandan sobre el replegado:
        ocultar justo cuando acaba de aparecer algo seria perder el
        aviso.
        """
        self._hide_id = None
        if (not T.AUTOHIDE or self.activities or self.hover is not None
                or self._dentro):
            # Con el raton encima no se repliega aunque ya no quede nada
            # que ensenar: lo estas mirando tu. Antes bastaba con mirar
            # 'hover', que solo se pone sobre una zona pulsable, asi que
            # el puntero en una parte muerta del notch no contaba.
            return False
        self.oculto = True
        self.sp_y.set(-(T.H_COMPACT - T.PEEK))
        self.ensure_tick()
        return False

    def _programar_ocultado(self, ms=None):
        if not T.AUTOHIDE:
            return
        if self._hide_id:
            GLib.source_remove(self._hide_id)
        self._hide_id = GLib.timeout_add(ms or T.HIDE_MS, self._quiza_ocultar)

    def on_draw(self, widget, cr):
        t0 = time.monotonic()
        self._dibuja(cr)
        ms = (time.monotonic() - t0) * 1000.0
        self._prof["draw"] += 1
        self._prof["ms"] += ms
        if ms > self._prof["max"]:
            self._prof["max"] = ms
        return False

    def _dibuja(self, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)

        x, y, w, h = self.geom()
        # notch(), no capsule(): arriba va recto contra el borde de la
        # pantalla y solo se redondea abajo. Los filetes cierran el
        # encuentro con el borde.
        R.notch(cr, x, y, w, h, min(h / 2.0, T.NOTCH_R), T.FILLET)
        cr.set_source_rgb(*T.ISLAND)
        cr.fill_preserve()
        cr.clip()

        f = max(0.0, min(1.0, self.sp_fade.value))
        cy = y + h / 2.0

        # Realce de hover, por detras del contenido.
        ha = max(0.0, min(1.0, self.sp_ha.value)) * f
        if ha > 0.01 and self.sp_hw.value > 1:
            # El radio lo dice la zona, que es quien sabe que forma
            # tiene lo que hay debajo. Antes era "la mitad del alto,
            # hasta 22": una fila de lista de 216x46 se realzaba con una
            # capsula de extremos semicirculares, una forma que no se
            # parecia a nada de lo que habia debajo.
            r = getattr(self, "_hover_r", R.HOVER_R)
            R.capsule(cr, self.sp_hx.value, self.sp_hy.value,
                      self.sp_hw.value, self.sp_hh.value,
                      min(r, self.sp_hh.value / 2.0))
            cr.set_source_rgba(1, 1, 1, T.HOVER_A * ha)
            cr.fill()

        # El contenido saliente sube y el entrante llega desde abajo: es
        # el mismo gesto que usa iOS al cambiar de actividad y hace que
        # el cruce se lea como un relevo, no como un parpadeo.
        if self.prev_content is not None and f < 0.999:
            pw = getattr(self, "_pw", 0.0) or self.prev_content.size(cr)[0]
            cr.save()
            cr.translate(0, -10 * f)
            self._encaja(cr, pw, x, w, cy)
            self.prev_content.draw(cr, x + (w - pw) / 2.0, cy, 1.0 - f)
            cr.restore()

        # Las zonas sensibles se reinician aqui, despues de pintar el
        # contenido saliente: si no, durante el cruce quedarian activas
        # las del contenido que ya se esta yendo y un clic acertaria en
        # algo que el usuario ya no ve.
        R.begin_hits()
        if self.content is not None:
            cw = getattr(self, "_cw", 0.0) or self.content.size(cr)[0]
            cr.save()
            cr.translate(0, 10 * (1.0 - f))
            self._encaja(cr, cw, x, w, cy)
            self.content.draw(cr, x + (w - cw) / 2.0, cy, f)
            cr.restore()

        cr.reset_clip()

    def _rodillo(self, nombre, texto):
        """El contador de esa cifra, ya puesto al dia."""
        c = self._cont.get(nombre)
        if c is None:
            c = self._cont[nombre] = Contador(texto)
        elif c.set(texto):
            self.ensure_tick()
        return c

    @staticmethod
    def _pct(cr, cont, fuente, color):
        """El porcentaje en un hueco de ancho FIJO y alineado a la
        derecha.

        "5%" mide 40 px y "100%" 68, asi que la isla se reajustaba en
        CADA paso de volumen: crecia y encogia mientras subes la rueda.
        Reservando siempre lo que mide "100%", el ancho no se mueve.

        Y pegado a la derecha, no centrado: asi el simbolo de porcentaje
        se queda clavado y lo que crece hacia la izquierda son las
        cifras. Se probo con una monoespaciada --que ademas iguala el
        ancho de cada digito- y no pegaba con el resto de la isla, que
        es toda Inter.
        """
        txt = R.Rodillo(cont, fuente, color)
        hueco = (R.Text("100%", fuente, color, feats=R.TNUM).size(cr)[0]
                 - txt.size(cr)[0])
        return R.Row([R.Gap(max(0, hueco)), txt])

    def _mayusculas(self):
        """Si Bloq Mayus esta puesto AHORA. Se pregunta a GDK en vez de
        recordarlo: la tecla puede pulsarse con el panel abierto o venir
        puesta de antes."""
        try:
            km = Gdk.Keymap.get_for_display(self.get_display())
            return bool(km.get_caps_lock_state())
        except Exception:
            return False

    @staticmethod
    def _encaja(cr, ancho_contenido, x_isla, ancho_isla, cy):
        """Encoge el contenido mientras la forma no le llega.

        La forma se mueve con un muelle y el contenido se construia ya a
        su tamano final, asi que durante el crecimiento se dibujaba algo
        de 600 px dentro de una capsula de 300: como el dibujado va
        recortado a la forma, el texto salia partido por los lados.

        Escalandolo por lo que CABE, el texto y la forma van parejos: ni
        se sale ni aparece de golpe al final. El factor sube a 1 en
        cuanto la isla alcanza su tamano, asi que en reposo no hay
        ninguna escala puesta y el texto se dibuja nitido.
        """
        if ancho_contenido <= 0:
            return
        util = max(0.0, ancho_isla - 2 * T.PAD_PILL)
        k = max(T.ENCAJE_MIN, min(1.0, util / float(ancho_contenido)))
        if k > 0.999:
            return
        # El centro de la ISLA en coordenadas de pantalla, no el de
        # la ventana: el contenido esta centrado ahi, y escalando
        # alrededor de otro punto se arrastraria hacia un lado.
        cx = x_isla + ancho_isla / 2.0
        cr.translate(cx, cy)
        cr.scale(k, k)
        cr.translate(-cx, -cy)

    def update_input_region(self):
        """Solo la capsula recibe clics; el resto de la ventana deja
        pasar el raton a lo que haya debajo."""
        gw = self.get_window()
        if gw is None:
            return
        # Se usa el maximo entre el valor actual y el de destino: con
        # solo el actual, durante los ~300 ms de expansion la zona
        # pulsable iria por detras del dibujo y los clics sobre un panel
        # recien abierto se perderian.
        w = max(self.sp_w.value, self.sp_w.target, T.H_COMPACT)
        h = max(self.sp_h.value, self.sp_h.target, T.H_COMPACT)
        x = (self.W - w) / 2.0
        # Solo la parte VISIBLE del notch, recortada contra el borde de
        # la pantalla. Antes se tomaba la ventana entera desplazada, asi
        # que con el notch replegado la zona seguia midiendo 62px de
        # alto aunque solo asomaran 3: bastaba con pasar el raton por la
        # barra de pestanas del navegador para que se desplegara.
        y0 = T.TOP + self.sp_y.value
        arriba = max(0.0, y0)
        abajo = y0 + h
        if abajo <= arriba:
            rect = (int(x), 0, int(math.ceil(w)), 0)
        else:
            rect = (int(x), int(arriba), int(math.ceil(w)),
                    int(math.ceil(abajo - arriba)))
        # Cada llamada es un viaje de ida y vuelta al servidor X. Antes
        # se hacia en cada refresco aunque la geometria fuese identica.
        if rect == getattr(self, "_last_input_rect", None):
            return
        self._last_input_rect = rect
        reg = cairo.Region(cairo.RectangleInt(*rect))
        if T.AUTOHIDE:
            # Franja sensible a todo lo ancho del borde superior: es lo
            # que permite que el notch vuelva acercando el raton arriba
            # estando replegado.
            reg.union(cairo.RectangleInt(0, 0, self.W, T.HOT))
        gw.input_shape_combine_region(reg, 0, 0)

    def _hit(self, x, y):
        """Zona bajo el puntero, la MAS ESPECIFICA si hay anidadas.

        Una fila con etiqueta registra la suya antes que la de sus
        hijos, asi que devolver la primera que casara hacia que el grupo
        tapase siempre a sus elementos: pulsar un segmento de escritorio
        acertaba en la fila entera y no en el segmento.
        """
        mejor = None
        for tag, hx, hy, hw, hh, _r in R.get_hits():
            if hx <= x <= hx + hw and hy <= y <= hy + hh:
                area = hw * hh
                if mejor is None or area < mejor[0]:
                    mejor = (area, tag, (hx, hy, hw, hh, _r))
        return (mejor[1], mejor[2]) if mejor else (None, None)

    def on_click(self, widget, ev):
        tag, rect = self._hit(ev.x, ev.y)
        self._touch_panel()
        if self._seat is not None:
            self._arm_guard()

        if tag is None:
            # Con el puntero capturado esto incluye los clics de FUERA de
            # la isla, que es como se cierra un menu.
            if "panel" in self.activities:
                self._close_panel()
            else:
                act = self.current()
                if act is not None and act.kind in ("notify", "volume",
                                                    "brightness"):
                    self.activities.pop(act.kind, None)
            self.refresh()
            return True

        if tag == "dnd" or tag == "ds:dnd":
            controls.dnd_toggle()
            self.dnd = controls.dnd_paused()
            self.refresh()
        elif tag.startswith("ws"):
            # Clic izquierdo en un segmento: saltar a ese escritorio, que
            # es lo que cualquiera espera de un indicador pulsable.
            # Derecho: los ajustes del escritorio.
            if ev.button == 3:
                self.open_panel("desktop")
            elif ":" in tag:
                controls.bspwm("desktop", "-f", "^%d" % (int(tag[3:]) + 1))
        elif tag.startswith("ds:"):
            # Acciones de bspwm. Ninguna cierra el panel: se suelen
            # encadenar varias (equilibrar y luego ajustar el aire).
            acc = tag[3:]
            if acc == "monocle":
                controls.bspwm("desktop", "-l", "next")
            elif acc == "balance":
                controls.bspwm("node", "@/", "-B")
            elif acc == "rotate":
                controls.bspwm("node", "@/", "-R", "90")
            elif acc in ("gap+", "gap-"):
                g = controls.bspwm_gap() + (4 if acc == "gap+" else -4)
                controls.bspwm("config", "window_gap", str(max(0, min(60, g))))
            self._touch_panel()
            self.refresh()
        elif tag.startswith("media:"):
            controls.media(tag[6:])
            self._touch_panel()
            GLib.timeout_add(250, lambda: (self.refresh(), False)[1])
        elif tag in ("vol", "net", "bat", "clock"):
            self.open_panel({"vol": "volume", "net": "wifi",
                             "bat": "battery", "clock": "calendar"}[tag])
        elif tag in ("cal:prev", "cal:next", "cal:hoy"):
            # Navegar NO cierra el panel, a diferencia de elegir perfil o
            # red: aqui el clic es para seguir mirando, no una accion
            # terminal.
            self.cal_off = (0 if tag == "cal:hoy" else
                            self.cal_off + (1 if tag == "cal:next" else -1))
            self._touch_panel()
            self.refresh()
        elif tag == "power":
            self.open_panel("powermenu")
        elif tag.startswith("act:"):
            cmd = T.G_POWER_ACTS[int(tag[4:])][2]
            self._close_panel()
            self.refresh()
            GLib.spawn_async(["/bin/sh", "-c", cmd],
                             flags=GLib.SpawnFlags.SEARCH_PATH)
        elif tag.startswith("app:"):
            self.launch["sel"] = int(tag[4:])
            self._launch_sel()
        elif tag.startswith("emo:"):
            self.emo["sel"] = int(tag[4:])
            self._emoji_sel()
        elif tag.startswith("cat:"):
            cats = self._emo_cats(self.emo["res"])
            n = int(tag[4:])
            if n < len(cats):
                self._emo_ir(cats[n][1])
            self.refresh()
        elif tag == "pw-ver" and self.pw is not None:
            self.pw["ver"] = not self.pw.get("ver")
            self.refresh()
        elif tag.startswith("cap:"):
            self._captura_accion(tag[4:])
        elif tag.startswith("pp:"):
            self.port["sel"] = int(tag[3:])
            self._port_sel()
        elif tag == "vol-slider":
            self._drag = "vol-slider"
            self._slide(ev.x, rect)
        elif tag == "vol-mute":
            controls.toggle_mute()
            GLib.timeout_add(120, self._after_vol)
        elif tag == "vol-mixer":
            self._spawn(C.CMD_MIXER)
            self._close_panel()
            self.refresh()
        elif tag.startswith("prof:"):
            # Elegir perfil es una accion terminal: el panel se cierra,
            # como al elegir una red.
            controls.epp_set(tag[5:], self._after_prof)
            self._close_panel()
            self.refresh()
        elif tag.startswith("wifi:"):
            ssid = tag[5:]
            secure = any(n[0] == ssid and n[3] for n in (self.wifi_nets or []))
            if secure and ssid not in self.known:
                # Red protegida y sin perfil guardado: es el unico caso
                # en que hace falta la contrasena. Si ya hay perfil,
                # 'nmcli con up' usa la guardada.
                self._start_pw(ssid)
            else:
                controls.wifi_connect(ssid, self._after_wifi)
                self._close_panel()
                self.refresh()
        return True

    # ------------------------------------------------------------- hover

    @staticmethod
    def _interactive(tag):
        if tag is None:
            return False
        # El deslizador se excluye a proposito: ya da su propia
        # respuesta visual al moverse el mando, y un realce detras
        # ademas le quedaria mas ancho que la propia barra.
        if tag == "vol-slider":
            return False
        return (tag in ("vol", "net", "bat", "power", "vol-mute",
                        "vol-mixer", "clock")
                or tag == "dnd" or tag.startswith("ws")
                or tag.startswith(("prof:", "wifi:", "cal:", "act:", "app:",
                                   "ds:", "media:", "emo:", "cap:", "pp:",
                                   "cat:")) or tag == "pw-ver")

    def _set_cursor(self, pointer):
        if pointer == self._cursor_ptr:
            return
        gw = self.get_window()
        if gw is None:
            return
        name = "pointer" if pointer else "default"
        gw.set_cursor(Gdk.Cursor.new_from_name(self.get_display(), name))
        self._cursor_ptr = pointer

    def _set_hover(self, tag, rect):
        if tag == self.hover:
            return
        self.hover = tag
        if tag is None:
            self.sp_ha.set(0.0)          # se desvanece donde este
        else:
            hx, hy, hw, hh, radio = rect
            # El radio NO se anima: son unos pocos pixeles y animarlo
            # obligaria a un muelle mas para algo que nadie ve moverse.
            self._hover_r = radio
            if self.sp_ha.value < 0.05:
                # Primera zona tras entrar: aparece ya colocada, para que
                # no se vea venir volando desde la posicion anterior.
                self.sp_hx.snap(hx); self.sp_hy.snap(hy)
                self.sp_hw.snap(hw); self.sp_hh.snap(hh)
            else:
                self.sp_hx.set(hx); self.sp_hy.set(hy)
                self.sp_hw.set(hw); self.sp_hh.set(hh)
            self.sp_ha.set(1.0)
        # Con un panel abierto el contenido depende del hover (el chip
        # senalado muestra su nombre), asi que hay que reconstruirlo.
        if tag is not None and tag.startswith("app:") and self.launch:
            # Apuntar una fila la selecciona, para que raton y teclado
            # compartan una unica nocion de "el que se va a lanzar".
            self.launch["sel"] = int(tag[4:])
        if tag is not None and tag.startswith("pp:") and self.port:
            self.port["sel"] = int(tag[3:])
        if tag is not None and tag.startswith("emo:") and self.emo:
            # Lo mismo en la rejilla: apuntar una casilla la selecciona,
            # asi que el pie dice siempre el nombre de lo que hay debajo
            # del puntero.
            self.emo["sel"] = int(tag[4:])
        if tag is not None and tag.startswith("cap:"):
            # Senalar un boton aplaza el cierre. Si no, mover el raton
            # hasta "Borrar" podia gastar los ultimos segundos de la
            # tarjeta y te la encontrabas desapareciendo bajo el dedo.
            act = self.activities.get("captura")
            if act is not None and act.expires is not None:
                act.expires = max(act.expires, time.monotonic() + 3.0)
                self._schedule_expiry()
        if "panel" in self.activities or "captura" in self.activities:
            # La tarjeta de la captura tambien depende del hover: el
            # boton senalado se tine y el subtitulo dice lo que hace.
            self.refresh()
        self.ensure_tick()

    def on_motion(self, widget, ev):
        tag, rect = self._hit(ev.x, ev.y)

        if self._drag == "vol-slider" and (ev.state & Gdk.ModifierType.BUTTON1_MASK):
            for t, hx, hy, hw, hh, _r in R.get_hits():
                if t == "vol-slider":
                    self._slide(ev.x, (hx, hy, hw, hh))
                    break
            self._touch_panel()
            return False

        if self._interactive(tag):
            self._set_hover(tag, rect)
            self._set_cursor(True)
            # OJO: aqui NO se aplaza el cierre. Si el mero hecho de tener
            # el raton encima renovase el plazo, dejar el puntero quieto
            # sobre el panel lo mantendria abierto para siempre.
        else:
            self._set_hover(None, None)
            self._set_cursor(tag == "vol-slider")
        return False

    def on_enter(self, widget, ev):
        self._dentro = True
        self._mostrar()
        return False

    def on_leave(self, widget, ev):
        # Al salir del raton, ni realce ni cursor de mano.
        self._dentro = False
        self._set_hover(None, None)
        self._set_cursor(False)
        self._programar_ocultado()
        return False

    def on_release(self, widget, ev):
        self._drag = None
        return False

    def _slide(self, x, rect):
        # La zona puede venir con el radio del realce detras: aqui solo
        # interesan la x y el ancho.
        hx, hw = rect[0], rect[2]
        # La zona lleva 12px de margen a cada lado para que sea comoda de
        # pulsar; hay que descontarlos o el 0% y el 100% caerian fuera
        # del recorrido real de la barra.
        pad = 12
        frac = (x - (hx + pad)) / max(1.0, hw - 2 * pad)
        frac = max(0.0, min(1.0, frac))
        controls.set_volume(frac)
        self.sys.volume = int(round(frac * 100))
        self.sys.muted = False
        self.refresh()

    def _after_vol(self):
        self.sys.refresh()
        self.refresh()
        return False

    def _after_prof(self, ok, mode):
        if not ok:
            self.on_event({"kind": "notify", "app": "Energia",
                           "body": "No se pudo aplicar el perfil"})
        self.refresh()
        return False

    def _after_wifi(self, ok, ssid, msg=""):
        self.sys.refresh()
        if self.pw is not None:
            self.pw["estado"] = ""
        if not ok and msg == "bad-password":
            # Se vuelve al campo con el aviso en vez de cerrar: reabrir
            # el panel y buscar otra vez la red seria un castigo por
            # una errata.
            self._start_pw(ssid)
            if self.pw is not None:
                self.pw["error"] = True
                self.refresh()
            return False
        # Ahora el panel sigue abierto mientras nmcli trabaja, asi que
        # hay que cerrarlo al terminar: antes se cerraba al pulsar Intro
        # y aqui no quedaba nada que cerrar.
        if self.pw is not None:
            self._close_panel()
        self.on_event({
            "kind": "notify", "app": "Wi-Fi",
            "body": ("Conectado a %s" % ssid) if ok
                    else ("No se pudo conectar a %s" % ssid)})
        return False


def main():
    # WM_CLASS sale de prgname (instancia) y program_class (clase), y hay
    # que fijarlos ANTES de crear la ventana. Es lo que usan las reglas de
    # picom para excluir la isla del blur y de la sombra. La alternativa,
    # Gtk.Window.set_wmclass(), esta deprecada y ademas no surte efecto si
    # se llama despues de realizar la ventana.
    GLib.set_prgname("island")
    Gdk.set_program_class("Island")
    win = Island()
    # La lista de emoji (~240 ms: leer el fichero de Unicode y preguntar
    # a la fuente cual sabe dibujar) se construye en un hilo mientras
    # arranca el escritorio. Hacerlo al abrir el selector por primera
    # vez se notaria justo ahi, y hacerlo aqui en el hilo de GTK
    # retrasaria el primer dibujado de la isla.
    sources.emoji_precarga()
    Gtk.main()


if __name__ == "__main__":
    main()

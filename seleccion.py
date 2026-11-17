# -*- coding: utf-8 -*-
"""Selector de region propio, con la estetica del notch.

Se usa desde captura.py. Devuelve (x, y, w, h) o None si se cancela.

**La pantalla se congela sin congelar X.** La primera version usaba
`scrot --freeze`, que lo hace con XGrabServer: mientras eliges, NINGUN
otro cliente puede dibujar, y si el que captura se colgase el escritorio
entero se quedaria tieso detras. Aqui se hace al reves: se saca una foto
del escritorio (19 ms) y se ensena a pantalla completa. Lo que ves esta
quieto porque es una foto, no porque el servidor este bloqueado.

Y de propina, la region recortada sale de ESA foto, asi que el propio
selector no puede salir en la captura por mucho que se dibuje encima.

**Ventana POPUP y no normal.** Una ventana corriente la gestionaria
bspwm: la colocaria en el mosaico, le haria sitio a las demas y se veria
el tiron. Una POPUP es override-redirect, asi que el gestor ni se entera
y aparece a pantalla completa en el acto.
"""
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk
import time

import theme as T
import render as R

# Cuanto se oscurece lo que no esta seleccionado. Lo justo para que la
# region elegida salte a la vista sin que el resto deje de reconocerse:
# muchas veces eliges por lo que hay AL LADO de lo que quieres.
VELO = 0.55
# Arrastre minimo. Por debajo se entiende que fue un clic sin querer y
# se cancela, en vez de devolver una captura de 3x2 pixeles.
MINIMO = 8


class Seleccion(Gtk.Window):
    def __init__(self, foto):
        Gtk.Window.__init__(self, type=Gtk.WindowType.POPUP)
        self.foto = foto
        self.W, self.H = foto.get_width(), foto.get_height()
        self.ancla = None          # donde empezo el arrastre
        self.cursor = None         # donde esta el raton ahora
        self.rect = None           # resultado
        self._seat = None

        self.set_app_paintable(True)
        self.set_default_size(self.W, self.H)
        self.move(0, 0)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK
                        | Gdk.EventMask.BUTTON_RELEASE_MASK
                        | Gdk.EventMask.POINTER_MOTION_MASK
                        | Gdk.EventMask.KEY_PRESS_MASK)
        self.connect("draw", self.on_draw)
        self.connect("button-press-event", self.on_press)
        self.connect("button-release-event", self.on_release)
        self.connect("motion-notify-event", self.on_motion)
        self.connect("key-press-event", self.on_key)
        self.connect("realize", self.on_realize)

    # ------------------------------------------------------------ vida

    def on_realize(self, *_a):
        gw = self.get_window()
        gw.set_cursor(Gdk.Cursor.new_from_name(self.get_display(),
                                               "crosshair"))

    def agarrar(self, intentos=24):
        """Teclado y raton, o no habria forma de cancelar con Escape.

        Se reintenta porque sxhkd mantiene agarrado el teclado hasta que
        sueltas las teclas del atajo, y con `super + shift + s` (que
        dispara al PULSAR) todavia las tienes abajo cuando esto arranca.
        Al primer intento el servidor contesta ALREADY_GRABBED y, sin
        reintentar, el selector se cerraria solo sin decir nada. Es el
        mismo caso que el lanzador con `super + d`.
        """
        seat = self.get_display().get_default_seat()
        for i in range(intentos):
            r = seat.grab(self.get_window(),
                          Gdk.SeatCapabilities.KEYBOARD
                          | Gdk.SeatCapabilities.ALL_POINTING,
                          False, None, None, None, None)
            if r == Gdk.GrabStatus.SUCCESS:
                self._seat = seat
                return True
            if i < intentos - 1:
                time.sleep(0.025)      # 24 x 25 ms = 600 ms de margen
        return False

    def terminar(self, rect):
        self.rect = rect
        if self._seat is not None:
            self._seat.ungrab()
            self._seat = None
        self.destroy()
        Gtk.main_quit()

    # --------------------------------------------------------- eventos

    def on_press(self, _w, ev):
        if ev.button == 1:
            self.ancla = (ev.x, ev.y)
            self.cursor = (ev.x, ev.y)
            self.queue_draw()
        else:
            self.terminar(None)        # el derecho cancela, como siempre
        return True

    def on_motion(self, _w, ev):
        self.cursor = (ev.x, ev.y)
        self.queue_draw()
        return True

    def on_release(self, _w, ev):
        if ev.button != 1 or self.ancla is None:
            return True
        x, y, w, h = self._caja()
        self.terminar((x, y, w, h) if w >= MINIMO and h >= MINIMO else None)
        return True

    def on_key(self, _w, ev):
        if ev.keyval in (Gdk.KEY_Escape, Gdk.KEY_q):
            self.terminar(None)
        elif ev.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and self.ancla:
            x, y, w, h = self._caja()
            self.terminar((x, y, w, h) if w >= MINIMO and h >= MINIMO
                          else None)
        return True

    def _caja(self):
        """La seleccion, normalizada: se puede arrastrar en cualquier
        direccion y el rectangulo sale siempre con ancho y alto
        positivos."""
        ax, ay = self.ancla
        cx, cy = self.cursor
        x, y = min(ax, cx), min(ay, cy)
        return int(x), int(y), int(abs(cx - ax)), int(abs(cy - ay))

    # -------------------------------------------------------- dibujado

    def on_draw(self, _w, cr):
        # La foto del escritorio, a brillo pleno, y el velo encima.
        Gdk.cairo_set_source_pixbuf(cr, self.foto, 0, 0)
        cr.paint()
        cr.set_source_rgba(0, 0, 0, VELO)
        cr.paint()

        if self.ancla is None:
            self._guias(cr)
            self._cartel(cr)
            return False

        x, y, w, h = self._caja()
        if w and h:
            # La region elegida se repinta desde la foto: queda a brillo
            # pleno, como un agujero en el velo.
            cr.save()
            cr.rectangle(x, y, w, h)
            cr.clip()
            Gdk.cairo_set_source_pixbuf(cr, self.foto, 0, 0)
            cr.paint()
            cr.restore()

            cr.set_source_rgba(*T.FG, 0.9)
            cr.set_line_width(1.0)
            cr.rectangle(x + 0.5, y + 0.5, w - 1, h - 1)
            cr.stroke()
            self._asas(cr, x, y, w, h)
            self._medida(cr, x, y, w, h)
        return False

    def _guias(self, cr):
        """Cruz tenue por el cursor antes de empezar: dice donde vas a
        anclar la esquina sin tener que adivinarlo."""
        if self.cursor is None:
            return
        cx, cy = self.cursor
        cr.set_source_rgba(*T.FG, 0.22)
        cr.set_line_width(1.0)
        cr.move_to(0, int(cy) + 0.5); cr.line_to(self.W, int(cy) + 0.5)
        cr.move_to(int(cx) + 0.5, 0); cr.line_to(int(cx) + 0.5, self.H)
        cr.stroke()

    def _asas(self, cr, x, y, w, h):
        """Escuadras en las esquinas. Un borde de 1 px se pierde sobre
        una imagen con detalle; las esquinas marcadas se ven siempre y
        ademas dicen que eso es una seleccion y no un marco dibujado."""
        lado = min(18, w / 3.0, h / 3.0)
        if lado < 4:
            return
        cr.set_source_rgba(*T.ACCENT, 1.0)
        cr.set_line_width(3.0)
        for ex, ey, dx, dy in ((x, y, 1, 1), (x + w, y, -1, 1),
                               (x, y + h, 1, -1), (x + w, y + h, -1, -1)):
            cr.move_to(ex + dx * lado, ey + dy * 1.5)
            cr.line_to(ex + dx * 1.5, ey + dy * 1.5)
            cr.line_to(ex + dx * 1.5, ey + dy * lado)
            cr.stroke()

    def _capsula(self, cr, texto, cx, cy, fuente=None):
        """Una pastilla negra con texto, igual que las del notch."""
        t = R.Text(texto, fuente or T.F_SUB, T.FG)
        tw, th = t.size(cr)
        w, h = tw + 28, th + 16
        x, y = cx - w / 2.0, cy - h / 2.0
        x = max(8, min(self.W - w - 8, x))
        y = max(8, min(self.H - h - 8, y))
        R.capsule(cr, x, y, w, h, h / 2.0)
        cr.set_source_rgba(*T.ISLAND, 0.92)
        cr.fill()
        t.draw(cr, x + 14, y + h / 2.0, 1.0)
        return y

    def _medida(self, cr, x, y, w, h):
        """El tamano, debajo de la seleccion; dentro si no cabe fuera."""
        etiqueta = "%d × %d" % (w, h)
        debajo = y + h + 26
        if debajo > self.H - 20:
            debajo = y + h - 26
        self._capsula(cr, etiqueta, x + w / 2.0, debajo)

    def _cartel(self, cr):
        self._capsula(cr, "Arrastra para seleccionar · esc cancela",
                      self.W / 2.0, self.H / 2.0)


def elegir():
    """Congela, ensena el selector y devuelve (x, y, w, h) o None."""
    raiz = Gdk.get_default_root_window()
    foto = Gdk.pixbuf_get_from_window(raiz, 0, 0,
                                      raiz.get_width(), raiz.get_height())
    if foto is None:
        return None, None
    win = Seleccion(foto)
    win.show_all()
    if not win.agarrar():
        # Sin captura del teclado no habria forma de cancelar, y una
        # ventana a pantalla completa que no se puede cerrar es peor que
        # no capturar.
        win.destroy()
        return None, foto
    Gtk.main()
    return win.rect, foto

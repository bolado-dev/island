# -*- coding: utf-8 -*-
"""Primitivas de dibujo: capsula, texto y composicion por filas.

El contenido se modela como una fila de elementos que saben MEDIRSE
antes de dibujarse. Es necesario en ese orden: la isla tiene que conocer
el ancho final para lanzar el muelle hacia el, y el muelle empieza a
correr un fotograma antes de que ese contenido llegue a pintarse.
"""
import gi
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
gi.require_version('GdkPixbuf', '2.0')
# Sin fijar la version, importar Gdk suelto carga la 4.0 y chocaria con
# el Gtk 3 del resto del programa.
gi.require_version('Gdk', '3.0')
gi.require_version('Rsvg', '2.0')
from gi.repository import Pango, PangoCairo, GdkPixbuf, Gdk, Rsvg
import math
import os
import cairo
import theme as T

_WEIGHTS = {
    "thin": Pango.Weight.THIN, "light": Pango.Weight.LIGHT,
    "normal": Pango.Weight.NORMAL, "medium": Pango.Weight.MEDIUM,
    "semibold": Pango.Weight.SEMIBOLD, "bold": Pango.Weight.BOLD,
}

_font_cache = {}

# Cache de layouts de Pango, por (texto, fuente).
#
# Conformar texto es lo caro del dibujado, y el contenido se reconstruye
# entero en cada refresco: sin cache se volvian a conformar las mismas
# dos docenas de cadenas una y otra vez. Se limita el tamano porque las
# claves cambian solas (hora, porcentajes, SSID) y si no creceria sin
# fin.
_layout_cache = {}
_LAYOUT_MAX = 256

# Zonas sensibles al raton del ultimo fotograma. Se rellenan al DIBUJAR
# y no al construir el contenido porque la posicion final de cada
# elemento solo se conoce una vez centrada la fila dentro de la capsula,
# que a su vez depende del ancho animado de ese fotograma.
_hits = []


def begin_hits():
    del _hits[:]


def get_hits():
    return list(_hits)


def _record(tag, x, cy, w, h, pad=10):
    _hits.append((tag, x - pad, cy - h / 2.0 - pad, w + 2 * pad, h + 2 * pad))


def font_desc(spec):
    if spec in _font_cache:
        return _font_cache[spec]
    family, weight, px = spec
    d = Pango.FontDescription()
    d.set_family(family)
    d.set_weight(_WEIGHTS[weight])
    # set_absolute_size trabaja en pixeles de dispositivo, saltandose el
    # DPI configurado. Es lo que hace el render reproducible.
    d.set_absolute_size(px * Pango.SCALE)
    _font_cache[spec] = d
    return d


def capsule(cr, x, y, w, h, r=None):
    """Rectangulo redondeado exacto.

    Van los CUATRO arcos, uno por esquina. La version abreviada de dos
    arcos que se ve por ahi solo describe bien la forma cuando el radio
    es justo la mitad de la altura (una capsula); en cuanto el radio es
    menor, los dos arcos no se tocan, cairo une sus extremos con una
    recta y el contorno sale cruzado en diagonal.

    Con r = h/2 degenera por si sola en la capsula de extremos
    semicirculares, asi que sirve para los dos casos.
    """
    r = h / 2.0 if r is None else max(0.0, min(r, h / 2.0, w / 2.0))
    cr.new_sub_path()
    cr.arc(x + w - r, y + r,     r, -math.pi / 2, 0.0)            # sup. dcha
    cr.arc(x + w - r, y + h - r, r, 0.0, math.pi / 2)             # inf. dcha
    cr.arc(x + r,     y + h - r, r, math.pi / 2, math.pi)         # inf. izda
    cr.arc(x + r,     y + r,     r, math.pi, math.pi * 1.5)       # sup. izda
    cr.close_path()


# --------------------------------------------------------------- items

class Text(object):
    def __init__(self, s, font, color, alpha=1.0, tag=None):
        self.s, self.font, self.color, self.alpha = s, font, color, alpha
        self.tag = tag
        self._layout = None

    def layout(self, cr):
        if self._layout is None:
            key = (self.s, self.font)
            l = _layout_cache.get(key)
            if l is None:
                if len(_layout_cache) >= _LAYOUT_MAX:
                    _layout_cache.clear()
                l = PangoCairo.create_layout(cr)
                l.set_font_description(font_desc(self.font))
                l.set_text(self.s, -1)
                _layout_cache[key] = l
            self._layout = l
        return self._layout

    def size(self, cr):
        w, h = self.layout(cr).get_pixel_size()
        return w, h

    def draw(self, cr, x, cy, a):
        l = self.layout(cr)
        w, h = l.get_pixel_size()
        if self.tag:
            _record(self.tag, x, cy, w, h)
        cr.save()
        cr.set_source_rgba(*self.color, self.alpha * a)
        cr.move_to(x, cy - h / 2.0)
        # El layout puede venir de la cache, creado sobre OTRO contexto
        # (el de medir, que es una ImageSurface). update_layout lo
        # resincroniza con las opciones de fuente de este, que es lo que
        # evita que el texto cacheado se dibuje con otro suavizado.
        PangoCairo.update_layout(cr, l)
        PangoCairo.show_layout(cr, l)
        cr.restore()


class Image(object):
    """Icono de aplicacion o caratula.

    El pixbuf llega ya escalado al tamano final: escalar con cairo en
    cada fotograma volveria a muestrear la imagen 60 veces por segundo
    para nada, y ademas con peor filtro que el de GdkPixbuf.
    """
    def __init__(self, pixbuf, sz, radius=None, tag=None):
        self.pb = pixbuf
        self.sz = sz
        # Por defecto, esquinas redondeadas al estilo de los iconos de
        # app de iOS (~22% del lado).
        self.radius = sz * 0.22 if radius is None else radius
        self.tag = tag

    def size(self, cr):
        return self.sz, self.sz

    def draw(self, cr, x, cy, a):
        if self.tag:
            _record(self.tag, x, cy, self.sz, self.sz)
        y = cy - self.sz / 2.0
        cr.save()
        if self.radius > 0:
            capsule(cr, x, y, self.sz, self.sz, self.radius)
            cr.clip()
        Gdk.cairo_set_source_pixbuf(cr, self.pb, x, y)
        cr.paint_with_alpha(a)
        cr.restore()


class Dot(object):
    """Punto de actividad. Es el recurso que usa iOS para 'hay algo en
    marcha en segundo plano'."""
    def __init__(self, r, color):
        self.r, self.color = r, color

    def size(self, cr):
        return self.r * 2, self.r * 2

    def draw(self, cr, x, cy, a):
        cr.set_source_rgba(*self.color, a)
        cr.arc(x + self.r, cy, self.r, 0, 2 * math.pi)
        cr.fill()


class Bar(object):
    """Barra de progreso de extremos redondos (volumen, brillo)."""
    def __init__(self, w, h, frac, color, bg=T.DIM2):
        self.w, self.h, self.frac = w, h, max(0.0, min(1.0, frac))
        self.color, self.bg = color, bg

    def size(self, cr):
        return self.w, self.h

    def draw(self, cr, x, cy, a):
        y = cy - self.h / 2.0
        capsule(cr, x, y, self.w, self.h)
        cr.set_source_rgba(*self.bg, a)
        cr.fill()
        fw = self.w * self.frac
        if fw > 0.5:
            # El relleno nunca puede ser mas estrecho que su propio radio
            # o el arco se cruza y cairo pinta una lenteja al reves.
            capsule(cr, x, y, max(fw, self.h), self.h)
            cr.set_source_rgba(*self.color, a)
            cr.fill()


class Gap(object):
    def __init__(self, w):
        self.w = w

    def size(self, cr):
        return self.w, 0

    def draw(self, cr, x, cy, a):
        pass


class Row(object):
    """Fila con alineacion vertical al centro optico."""
    def __init__(self, items=None, tag=None):
        self.items = list(items or [])
        self.tag = tag

    def add(self, *items):
        self.items.extend(items)
        return self

    def size(self, cr):
        w = 0
        h = 0
        for it in self.items:
            iw, ih = it.size(cr)
            w += iw
            h = max(h, ih)
        return w, h

    def draw(self, cr, x, cy, a):
        if self.tag:
            w, h = self.size(cr)
            _record(self.tag, x, cy, w, max(h, 30), pad=6)
        for it in self.items:
            iw, _ = it.size(cr)
            it.draw(cr, x, cy, a)
            x += iw


class Stack(object):
    """Dos filas apiladas: titulo y subtitulo de una tarjeta."""
    def __init__(self, rows, gap=6, center=False):
        self.rows, self.gap, self.center = rows, gap, center

    def size(self, cr):
        w = 0
        h = -self.gap
        for r in self.rows:
            rw, rh = r.size(cr)
            w = max(w, rw)
            h += rh + self.gap
        return w, h

    def draw(self, cr, x, cy, a):
        tw, th = self.size(cr)
        y = cy - th / 2.0
        for r in self.rows:
            rw, rh = r.size(cr)
            rx = x + (tw - rw) / 2.0 if self.center else x
            r.draw(cr, rx, y + rh / 2.0, a)
            y += rh + self.gap


class Slider(object):
    """Barra arrastrable (volumen, brillo).

    Registra su zona sensible con el ancho COMPLETO de la pista, no solo
    la parte rellena: si no, al bajar el volumen a cero la zona se
    encogeria hasta desaparecer y ya no habria forma de volver a subirlo
    arrastrando.
    """
    def __init__(self, w, h, frac, color, tag=None, knob=True):
        self.w, self.h = w, h
        self.frac = max(0.0, min(1.0, frac))
        self.color, self.tag, self.knob = color, tag, knob

    def size(self, cr):
        return self.w, max(self.h, 26)

    def draw(self, cr, x, cy, a):
        if self.tag:
            _record(self.tag, x, cy, self.w, max(self.h, 26), pad=12)
        y = cy - self.h / 2.0
        capsule(cr, x, y, self.w, self.h)
        cr.set_source_rgba(*T.SURF_2, a)
        cr.fill()
        fw = self.w * self.frac
        if fw > 0.5:
            capsule(cr, x, y, max(fw, self.h), self.h)
            cr.set_source_rgba(*self.color, a)
            cr.fill()
        if self.knob:
            kr = self.h * 0.95
            kx = x + max(kr, min(self.w - kr, fw))
            cr.set_source_rgba(1, 1, 1, a)
            cr.arc(kx, cy, kr, 0, 2 * math.pi)
            cr.fill()


class Chip(object):
    """Boton redondeado. Lo usan los perfiles de energia y las redes."""
    def __init__(self, text, font, fg, bg, tag=None,
                 padx=20, pady=11, icon=None, icon_font=None, icon_col=None):
        self.text, self.font, self.fg, self.bg = text, font, fg, bg
        self.tag, self.padx, self.pady = tag, padx, pady
        self.icon, self.icon_font = icon, icon_font
        self.icon_col = icon_col or fg
        self._t = None

    def _parts(self, cr):
        if self._t is None:
            self._t = Text(self.text, self.font, self.fg)
            if self.icon is None:
                self._i = None
            elif isinstance(self.icon, str):
                self._i = Text(self.icon, self.icon_font or self.font,
                               self.icon_col)
            else:
                # Ya viene construido (un Icon de Solar): se usa tal cual.
                self._i = self.icon
        return self._t, self._i

    def size(self, cr):
        t, i = self._parts(cr)
        tw, th = t.size(cr)
        if i is None:
            return tw + 2 * self.padx, th + 2 * self.pady
        iw, ih = i.size(cr)
        # Sin texto no hay que reservar la separacion icono-texto, o el
        # chip saldria descentrado hacia la izquierda.
        gap = 10 if tw else 0
        return iw + gap + tw + 2 * self.padx, max(th, ih) + 2 * self.pady

    def draw(self, cr, x, cy, a):
        t, i = self._parts(cr)
        w, h = self.size(cr)
        if self.tag:
            _record(self.tag, x, cy, w, h, pad=0)
        capsule(cr, x, cy - h / 2.0, w, h)
        cr.set_source_rgba(*self.bg, a)
        cr.fill()
        cx = x + self.padx
        if i:
            i.draw(cr, cx, cy, a)
            cx += i.size(cr)[0] + (10 if self.text else 0)
        if self.text:
            t.draw(cr, cx, cy, a)


class Bars(object):
    """Indicador de cobertura: cuatro barras de altura creciente."""
    def __init__(self, level, color, dim, w=6, gap=4, hmax=24):
        self.level, self.color, self.dim = level, color, dim
        self.w, self.gap, self.hmax = w, gap, hmax

    def size(self, cr):
        return 4 * self.w + 3 * self.gap, self.hmax

    def draw(self, cr, x, cy, a):
        for n in range(4):
            h = self.hmax * (0.35 + 0.65 * n / 3.0)
            cr.set_source_rgba(*(self.color if n < self.level else self.dim), a)
            # Redondeadas, como todo lo demas: en esquina viva
            # desentonaban con el resto de la interfaz.
            capsule(cr, x + n * (self.w + self.gap), cy + self.hmax / 2 - h,
                    self.w, h, self.w / 2.0)
            cr.fill()


class Field(object):
    """Campo de texto: recuadro con el contenido y un cursor que parpadea.

    Dibuja puntos en vez del texto cuando es una contrasena. El cursor
    se pinta solo si 'caret' viene a True; el parpadeo lo lleva el
    temporizador de la isla, no este objeto, para que el dibujado siga
    siendo una funcion pura del estado.
    """
    def __init__(self, w, text, font, fg, caret=True, secret=True, tag=None):
        self.w, self.font, self.fg = w, font, fg
        self.caret, self.tag = caret, tag
        self.shown = ("•" * len(text)) if secret else text
        self._t = None

    def _txt(self, cr):
        if self._t is None:
            self._t = Text(self.shown, self.font, self.fg)
        return self._t

    def size(self, cr):
        _, th = self._txt(cr).size(cr)
        return self.w, th + 26

    def draw(self, cr, x, cy, a):
        w, h = self.size(cr)
        if self.tag:
            _record(self.tag, x, cy, w, h, pad=0)
        capsule(cr, x, cy - h / 2.0, w, h, min(h / 2.0, 16))
        cr.set_source_rgba(1, 1, 1, T.FIELD_A * a)
        cr.fill()
        t = self._txt(cr)
        tw, th = t.size(cr)
        tx = x + 18
        t.draw(cr, tx, cy, a)
        if self.caret:
            cr.set_source_rgba(*self.fg, a)
            cr.rectangle(tx + tw + 3, cy - th / 2.0, 2.5, th)
            cr.fill()


def notch(cr, x, y, w, h, r, fillet=0.0):
    """Notch pegado al borde superior: arriba recto, abajo redondeado.

    Si 'fillet' es mayor que cero, dibuja ademas los enlaces CONCAVOS
    con los que el notch se encuentra con el borde de la pantalla. Es
    la diferencia entre parecer tallado en el panel y parecer una pieza
    pegada encima: sin ellos el encuentro es un angulo recto duro.

    Los filetes sobresalen 'fillet' px a cada lado del ancho util, asi
    que el contenido NO debe contar con ese espacio.
    """
    r = max(0.0, min(r, h, w / 2.0))
    f = max(0.0, min(fillet, w / 2.0))
    hp = math.pi / 2.0

    cr.new_sub_path()
    if f > 0:
        cr.move_to(x - f, y)
        # Centro por FUERA del notch: de ahi que el arco quede comido
        # hacia dentro y no abombado.
        cr.arc(x - f, y + f, f, -hp, 0.0)
    else:
        cr.move_to(x, y)

    cr.line_to(x, y + h - r)
    cr.arc_negative(x + r,     y + h - r, r, math.pi, hp)      # inf. izda
    cr.arc_negative(x + w - r, y + h - r, r, hp, 0.0)          # inf. dcha

    if f > 0:
        cr.line_to(x + w, y + f)
        cr.arc(x + w + f, y + f, f, math.pi, math.pi + hp)
    else:
        cr.line_to(x + w, y)
    cr.close_path()


class BatteryAnim(object):
    """Bateria dibujada a mano, con animacion de carga.

    No es un glifo de fuente: para animar el nivel hace falta control
    del relleno fotograma a fotograma, y un glifo es una forma fija.

    'phase' (0..1) la hace avanzar la isla. El relleno solido marca la
    carga REAL y una onda mas tenue barre de ahi hasta el tope, que es
    como se lee "esta subiendo" de un vistazo.
    """
    def __init__(self, w, h, level, phase, color, charging=True):
        self.w, self.h = w, h
        self.level = max(0.0, min(1.0, level))
        self.phase = phase % 1.0
        self.color, self.charging = color, charging

    def size(self, cr):
        return self.w + 5, self.h

    def draw(self, cr, x, cy, a):
        y = cy - self.h / 2.0
        r = self.h * 0.30
        inset = 3.0

        # Carcasa
        capsule(cr, x, y, self.w, self.h, r)
        cr.set_source_rgba(1, 1, 1, 0.30 * a)
        cr.set_line_width(2.5)
        cr.stroke()

        # Borne positivo
        nub_h = self.h * 0.38
        capsule(cr, x + self.w + 1, cy - nub_h / 2.0, 4, nub_h, 2)
        cr.set_source_rgba(1, 1, 1, 0.30 * a)
        cr.fill()

        iw = self.w - 2 * inset
        ih = self.h - 2 * inset
        ix = x + inset
        iy = y + inset

        cr.save()
        capsule(cr, ix, iy, iw, ih, max(1.0, r - inset))
        cr.clip()

        # Carga real
        if self.level > 0.01:
            cr.rectangle(ix, iy, iw * self.level, ih)
            cr.set_source_rgba(*self.color, a)
            cr.fill()

        # Onda de carga: del nivel actual al tope, y vuelta a empezar
        if self.charging and self.level < 0.995:
            sweep = self.level + (1.0 - self.level) * self.phase
            # Se apaga al final del ciclo para que el reinicio no de un
            # corte seco.
            fade = 1.0 - max(0.0, (self.phase - 0.75) / 0.25)
            cr.rectangle(ix + iw * self.level, iy,
                         iw * (sweep - self.level), ih)
            cr.set_source_rgba(*self.color, 0.35 * fade * a)
            cr.fill()
        cr.restore()


class Day(object):
    """Celda de calendario: caja de ancho FIJO con el numero centrado.

    El ancho fijo es lo que mantiene las siete columnas alineadas: si
    cada celda midiera lo que ocupa su numero, el 9 y el 30 darian
    columnas de distinto ancho y la rejilla saldria en diagonal.
    """
    def __init__(self, w, h, text, font, color, circle=None, tag=None):
        self.w, self.h = w, h
        self.color, self.circle, self.tag = color, circle, tag
        self._t = Text(text, font, color) if text else None

    def size(self, cr):
        return self.w, self.h

    def draw(self, cr, x, cy, a):
        if self.tag:
            _record(self.tag, x, cy, self.w, self.h, pad=0)
        if self.circle is not None:
            r = min(self.w, self.h) / 2.0
            cr.set_source_rgba(*self.circle, a)
            cr.arc(x + self.w / 2.0, cy, r, 0, 2 * math.pi)
            cr.fill()
        if self._t is not None:
            tw, _ = self._t.size(cr)
            self._t.draw(cr, x + (self.w - tw) / 2.0, cy, a)


class Box(object):
    """Envuelve otro elemento con un fondo redondeado.

    Lo usan las filas del lanzador: la seleccionada lleva fondo y las
    demas no, pero TODAS tienen que ocupar lo mismo o la lista bailaria
    al moverse con las flechas. De ahi el ancho forzado opcional.
    """
    def __init__(self, inner, bg=None, w=None, padx=14, pady=9,
                 radius=16, tag=None):
        self.inner, self.bg, self.fw = inner, bg, w
        self.padx, self.pady, self.radius, self.tag = padx, pady, radius, tag

    def size(self, cr):
        iw, ih = self.inner.size(cr)
        return (self.fw if self.fw else iw + 2 * self.padx,
                ih + 2 * self.pady)

    def draw(self, cr, x, cy, a):
        w, h = self.size(cr)
        if self.tag:
            _record(self.tag, x, cy, w, h, pad=0)
        if self.bg is not None:
            capsule(cr, x, cy - h / 2.0, w, h, self.radius)
            cr.set_source_rgba(*self.bg, a)
            cr.fill()
        self.inner.draw(cr, x + self.padx, cy, a)


class Rule(object):
    """Linea divisoria fina."""
    def __init__(self, w, color, h=1.0):
        self.w, self.color, self.h = w, color, h

    def size(self, cr):
        return self.w, self.h

    def draw(self, cr, x, cy, a):
        cr.set_source_rgba(*self.color, 0.6 * a)
        cr.rectangle(x, cy - self.h / 2.0, self.w, self.h)
        cr.fill()


# ---------------------------------------------------------- iconos Solar

ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
_svg_cache = {}


def _svg_surface(nombre, px):
    """Rasteriza un SVG de Solar a una superficie cairo, cacheada.

    Se cachea por (nombre, tamano) porque rasterizar es caro y el
    contenido se reconstruye en cada refresco: sin cache se volveria a
    dibujar el mismo icono decenas de veces por segundo.
    """
    clave = (nombre, px)
    s = _svg_cache.get(clave)
    if s is not None:
        return s
    ruta = os.path.join(ICON_DIR, nombre + ".svg")
    if not os.path.exists(ruta):
        if os.environ.get("ISLAND_DEBUG"):
            print("SVG no existe: %s" % ruta, flush=True)
        _svg_cache[clave] = False
        return False
    try:
        handle = Rsvg.Handle.new_from_file(ruta)
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, px, px)
        cr = cairo.Context(surf)
        dim = handle.get_dimensions()
        if dim.width and dim.height:
            cr.scale(px / float(dim.width), px / float(dim.height))
        handle.render_cairo(cr)
        surf.flush()
    except Exception as e:
        import os as _os
        if _os.environ.get("ISLAND_DEBUG"):
            print("SVG fallo %r@%s: %s" % (nombre, px, e), flush=True)
        surf = False
    _svg_cache[clave] = surf
    return surf


class Icon(object):
    """Icono de Solar, teñido al color que se le pida.

    El SVG se usa como MASCARA, no se pinta directamente: asi un mismo
    fichero sirve para blanco, gris o azul segun el estado, sin tener
    que guardar una copia por color. Si el icono no existe, cae al
    glifo de respaldo para no dejar un hueco vacio.
    """
    def __init__(self, nombre, px, color, respaldo=None, font=None, tag=None):
        self.nombre, self.px, self.color = nombre, px, color
        self.tag = tag
        self._surf = _svg_surface(nombre, px)
        self._alt = (Text(respaldo, font, color)
                     if self._surf is False and respaldo else None)

    def size(self, cr):
        if self._alt is not None:
            return self._alt.size(cr)
        return self.px, self.px

    def draw(self, cr, x, cy, a):
        if self.tag:
            w, h = self.size(cr)
            _record(self.tag, x, cy, w, h)
        if self._alt is not None:
            self._alt.draw(cr, x, cy, a)
            return
        if self._surf is False:
            return        # sin SVG y sin respaldo: mejor hueco que cascar
        cr.save()
        cr.set_source_rgba(*self.color, a)
        cr.mask_surface(self._surf, x, cy - self.px / 2.0)
        cr.restore()


class WsBar(object):
    """Indicador de escritorios: pista fija mas pildora deslizante.

    La pildora azul es UN solo elemento que viaja, no el segmento
    activo ensanchandose. Con lo segundo habia un instante con dos
    azules a la vez mientras uno crecia y el otro menguaba, que se leia
    como si hubiera dos escritorios activos.

    Los huecos son todos IGUALES: asi la pildora recorre la misma
    distancia por escritorio y las zonas pulsables no se mueven al
    cambiar de uno a otro.

    'pill_x' llega ya interpolado por el muelle de la isla; aqui solo
    se dibuja donde diga.
    """
    def __init__(self, estados, pill_x, pill_w=None, prev_x=None,
                 slot_h=18, tag_pref="ws:"):
        self.estados = estados          # 'free' | 'occupied' | 'urgent'
        self.pill_x = pill_x
        # Ancho actual de la pildora, en pixeles. Al cambiar de
        # escritorio arranca en el de un punto normal y crece hasta el
        # suyo, de modo que se lee como "el punto de ese escritorio se
        # estira".
        self.pill_w = T.SEG_SLOT if pill_w is None else pill_w
        # Hueco que acaba de dejar, para apagarlo con el mismo gesto
        # invertido en vez de que desaparezca de golpe.
        self.prev_x = prev_x
        self.slot_h, self.tag_pref = slot_h, tag_pref

    @staticmethod
    def paso():
        return T.SEG_SLOT + T.SEG_GAP

    def size(self, cr):
        n = len(self.estados)
        if not n:
            return 0, self.slot_h
        return n * T.SEG_SLOT + (n - 1) * T.SEG_GAP, self.slot_h

    def draw(self, cr, x, cy, a):
        for i, estado in enumerate(self.estados):
            sx = x + i * self.paso()
            if self.tag_pref:
                _record(self.tag_pref + str(i), sx + T.SEG_SLOT / 2.0, cy,
                        T.SEG_SLOT, self.slot_h, pad=6)
            if estado == "urgent":
                col, h = T.RED, T.SEG_H
            elif estado == "occupied":
                col, h = T.FG, T.SEG_H
            else:
                col, h = T.DIM2, T.SEG_H_OFF
            bx = sx + (T.SEG_SLOT - T.SEG_BAR) / 2.0
            capsule(cr, bx, cy - h / 2.0, T.SEG_BAR, h, h / 2.0)
            cr.set_source_rgba(*col, a)
            cr.fill()

        # La pildora va ENCIMA y tapa la marca del escritorio en el que
        # esta, asi que la pista se dibuja sin tratar al activo como un
        # caso aparte.
        #
        # Crece desde el ancho de un punto hasta el suyo, centrada en el
        # hueco: asi el estiramiento sale de los dos lados a la vez y no
        # parece que empuje hacia la derecha.
        pw = max(T.SEG_H, self.pill_w)
        # El fundido va atado al crecimiento, no a un muelle aparte: asi
        # no pueden desacompasarse y hace falta un estado menos.
        k = (pw - T.SEG_BAR) / float(max(1e-6, T.SEG_SLOT - T.SEG_BAR))
        k = max(0.0, min(1.0, k))

        # Salida: el hueco anterior hace el gesto al reves, encogiendo y
        # apagandose con el MISMO avance. Al cambiar de escritorio la
        # pildora desaparecia de golpe de donde estaba, que era el
        # momento mas brusco que quedaba.
        if self.prev_x is not None and k < 0.999:
            sw = T.SEG_SLOT - (T.SEG_SLOT - T.SEG_BAR) * k
            sx = x + self.prev_x + (T.SEG_SLOT - sw) / 2.0
            capsule(cr, sx, cy - T.SEG_H / 2.0, sw, T.SEG_H, T.SEG_H / 2.0)
            cr.set_source_rgba(*T.ACCENT, a * (1.0 - k))
            cr.fill()

        px = x + self.pill_x + (T.SEG_SLOT - pw) / 2.0
        alfa = T.POP_ALFA_MIN + (1.0 - T.POP_ALFA_MIN) * k
        capsule(cr, px, cy - T.SEG_H / 2.0, pw, T.SEG_H, T.SEG_H / 2.0)
        cr.set_source_rgba(*T.ACCENT, a * alfa)
        cr.fill()

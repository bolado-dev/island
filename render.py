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


# Numero de vuelta de dibujado. Medir un arbol cuesta: una fila pide el
# tamano de cada hijo para colocarlo, una pila pide el de cada fila para
# centrarla, y eso se repetia ENTERO en cada fotograma aunque nada
# hubiera cambiado. Con el numero de vuelta, cada elemento se mide una
# vez por vuelta y las demas veces devuelve lo que ya sabe; y como la
# vuelta cambia, lo que si cambia de tamano --una cifra rodando, un
# campo de texto- se sigue midiendo cuando toca.
_vuelta = 0


def begin_frame():
    global _vuelta
    _vuelta += 1


def begin_hits():
    del _hits[:]


def get_hits():
    return list(_hits)


# Radio por defecto del realce del raton. 16 y no "la mitad del alto":
# con la mitad, una fila de 46 px de alto y 216 de ancho se realzaba con
# una capsula de extremos semicirculares flotando sobre el texto, que es
# una forma que no se parece a nada de lo que hay debajo.
HOVER_R = 16


def _record(tag, x, cy, w, h, pad=10, radius=None):
    """Apunta una zona sensible y CON QUE FORMA se realza.

    La forma viaja con la zona porque solo aqui se sabe: un chip
    redondeado, una celda de la rejilla y una fila de lista tienen
    radios distintos, y el realce tiene que adoptar el de lo que hay
    debajo o se ve como una pegatina encima.
    """
    rw, rh = w + 2 * pad, h + 2 * pad
    r = HOVER_R if radius is None else radius
    _hits.append((tag, x - pad, cy - h / 2.0 - pad, rw, rh,
                  min(r, rh / 2.0, rw / 2.0)))


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
    def __init__(self, s, font, color, alpha=1.0, tag=None, feats=None):
        self.s, self.font, self.color, self.alpha = s, font, color, alpha
        self.tag, self.feats = tag, feats
        self._layout = None

    def layout(self, cr):
        if self._layout is None:
            key = (self.s, self.font, self.feats)
            l = _layout_cache.get(key)
            if l is None:
                if len(_layout_cache) >= _LAYOUT_MAX:
                    _layout_cache.clear()
                l = PangoCairo.create_layout(cr)
                l.set_font_description(font_desc(self.font))
                if self.feats:
                    # Cifras tabulares y demas. Van por atributos del
                    # layout y no por la descripcion de fuente, que no
                    # tiene donde guardarlas.
                    al = Pango.AttrList()
                    al.insert(Pango.attr_font_features_new(self.feats))
                    l.set_attributes(al)
                l.set_text(self.s, -1)
                _layout_cache[key] = l
            self._layout = l
        return self._layout

    def size(self, cr):
        if getattr(self, '_v', None) == _vuelta:
            return self._sz
        w, h = self.layout(cr).get_pixel_size()
        self._v, self._sz = _vuelta, (w, h)
        return self._sz

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


# Cifras tabulares: todos los digitos del mismo ancho. Sin esto, en
# Inter el "1" mide 13 px y el "4" 23, asi que el reloj cambiaba de
# ancho al pasar los minutos --y con el, la isla entera- y un digito
# rodando no tendria una casilla fija donde hacerlo.
TNUM = "tnum=1"


class Rodillo(object):
    """Cifras que cambian rodando, como un reloj de aletas.

    Solo se mueve lo que cambia: al pasar de 23:58 a 23:59, el 8 sale
    por arriba y el 9 entra por abajo mientras el resto se queda
    quieto. Es lo que hace que el ojo vea QUE ha cambiado sin tener que
    leer el numero entero.

    El estado (texto anterior, actual y por donde va) no vive aqui: el
    contenido de la isla se reconstruye cuando cambia algo, asi que un
    objeto de dibujo no puede recordar nada entre fotogramas.
    """
    def __init__(self, est, font, color, tag=None):
        self.est, self.font, self.color, self.tag = est, font, color, tag

    def _celdas(self, cr):
        """[(caracter nuevo, caracter viejo, ancho)] alineado a la
        DERECHA: los numeros crecen hacia la izquierda, asi que al pasar
        de 9% a 10% lo que se corresponde es el % con el % y el 9 con el
        0, no el 9 con el 1."""
        a, b = self.est.actual, self.est.previo
        n = max(len(a), len(b))
        a, b = a.rjust(n), b.rjust(n)
        out = []
        for nuevo, viejo in zip(a, b):
            # El ancho es el del MAS ancho de los dos: al pasar de 100%
            # a 99% la casilla del primer digito la ocupa un espacio, y
            # midiendo solo lo nuevo el 1 que todavia esta saliendo se
            # recortaba a la mitad.
            w = max(Text(c, self.font, self.color, feats=TNUM).size(cr)[0]
                    for c in (nuevo, viejo))
            out.append((nuevo, viejo, w))
        return out

    def size(self, cr):
        celdas = self._celdas(cr)
        alto = Text(self.est.actual or "0", self.font, self.color,
                    feats=TNUM).size(cr)[1]
        return sum(c[2] for c in celdas), alto

    def draw(self, cr, x, cy, a):
        w, h = self.size(cr)
        if self.tag:
            _record(self.tag, x, cy, w, h)
        p = max(0.0, min(1.0, self.est.p))
        for nuevo, viejo, cw in self._celdas(cr):
            if nuevo == viejo or p >= 0.999:
                Text(nuevo, self.font, self.color,
                     feats=TNUM).draw(cr, x, cy, a)
            else:
                # Recortado a su casilla: lo que entra y lo que sale no
                # pueden invadir al vecino ni salirse de la isla.
                cr.save()
                cr.rectangle(x, cy - h / 2.0, cw, h)
                cr.clip()
                # Sin fundido: un reloj de aletas no transparenta, y el
                # recorte ya impide que se pisen. Fundiendolos, a mitad
                # de camino los dos digitos se veian lavados.
                #
                # El sentido lo dice el contador: subiendo, lo viejo se
                # va por arriba y lo nuevo entra por abajo; bajando, al
                # reves. Dibujado igual en los dos casos, la animacion
                # no diria nada.
                d = getattr(self.est, "dir", 1)
                Text(viejo, self.font, self.color,
                     feats=TNUM).draw(cr, x, cy - d * h * p, a)
                Text(nuevo, self.font, self.color,
                     feats=TNUM).draw(cr, x, cy + d * h * (1.0 - p), a)
                cr.restore()
            x += cw


class Cifras(object):
    """Cifras que se leen EN VIVO al dibujar, en un hueco de ancho fijo.

    Las centesimas de un cronometro cambian cien veces por segundo.
    Reconstruir el contenido para moverlas seria volver a medir con
    Pango el panel entero cien veces por segundo, asi que el texto sale
    de una funcion al dibujar --igual que la barra lee su muelle- y el
    hueco mide lo que mida 'molde', que es el caso mas ancho. Con el
    ancho fijado por el molde, la isla no se reajusta con cada centesima.

    Lo que cambia a ritmo de PERSONA (los segundos) no se dibuja aqui:
    eso es un Rodillo, porque ahi si hay un cambio que merece animarse.
    """
    def __init__(self, fn, molde, font, color, tag=None):
        self.fn, self.molde = fn, molde
        self.font, self.color, self.tag = font, color, tag

    def _molde(self):
        return Text(self.molde, self.font, self.color, feats=TNUM)

    def size(self, cr):
        return self._molde().size(cr)

    def draw(self, cr, x, cy, a):
        w, h = self.size(cr)
        if self.tag:
            _record(self.tag, x, cy, w, h)
        Text(self.fn(), self.font, self.color, feats=TNUM).draw(cr, x, cy, a)


class Baja(object):
    """Baja a su hijo unos pixeles sin cambiar lo que ocupa.

    Para que las centesimas del cronometro se apoyen en la misma linea
    que las cifras grandes: una fila alinea por el CENTRO, y un texto a
    mitad de cuerpo centrado al lado de otro mas grande parece flotar en
    el aire en vez de ir detras de el.
    """
    def __init__(self, hijo, dy):
        self.hijo, self.dy = hijo, dy

    def size(self, cr):
        return self.hijo.size(cr)

    def draw(self, cr, x, cy, a):
        self.hijo.draw(cr, x, cy + self.dy, a)


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


class Thumb(object):
    """Miniatura de proporcion libre, con las esquinas redondeadas.

    Image no vale: es cuadrada, porque un icono de aplicacion y una
    caratula lo son. Una captura de pantalla no, y meterla en un
    cuadrado la deformaria o recortaria justo la parte que te hizo
    capturarla.

    El alto manda y el ancho sale de la proporcion del fichero, asi que
    todas las tarjetas miden lo mismo de alto aunque capture una
    pantalla apaisada o una ventana estrecha.
    """
    def __init__(self, pixbuf, alto, radius=10, tag=None):
        self.pb, self.alto, self.radius, self.tag = pixbuf, alto, radius, tag
        prop = (pixbuf.get_width() / float(pixbuf.get_height())
                if pixbuf is not None and pixbuf.get_height() else 1.0)
        # Tope de proporcion: una captura de una ventana muy alargada
        # (una terminal a pantalla completa) daria una miniatura de 400
        # px de ancho y la tarjeta no cabria en el notch.
        self.ancho = max(alto * 0.6, min(alto * 2.4, alto * prop))

    def size(self, cr):
        return self.ancho, self.alto

    def draw(self, cr, x, cy, a):
        if self.tag:
            _record(self.tag, x, cy, self.ancho, self.alto, pad=0)
        y = cy - self.alto / 2.0
        cr.save()
        capsule(cr, x, y, self.ancho, self.alto, self.radius)
        cr.clip()
        if self.pb is not None:
            # El pixbuf llega escalado al ALTO; el sobrante de ancho se
            # recorta por el centro, que es donde esta lo que importa.
            pw = self.pb.get_width()
            Gdk.cairo_set_source_pixbuf(cr, self.pb,
                                        x - (pw - self.ancho) / 2.0, y)
            cr.paint_with_alpha(a)
        else:
            cr.set_source_rgba(*T.SURF_2, a)
            cr.paint()
        cr.restore()
        # Un filo tenue: sobre el negro de la isla, una captura oscura
        # se quedaria sin borde y pareceria un agujero.
        capsule(cr, x + 0.5, y + 0.5, self.ancho - 1, self.alto - 1,
                self.radius)
        cr.set_source_rgba(1, 1, 1, 0.14 * a)
        cr.set_line_width(1.0)
        cr.stroke()


class Swatch(object):
    """Cuadrado de color con las esquinas redondeadas.

    Para un #rrggbb del portapapeles: el nombre de un color no dice
    nada y el color si. Cuadrado y no circulo porque es una MUESTRA de
    pintura, no un indicador de estado --que es lo que son los puntos
    de esta barra-, y conviene que no se confundan.
    """
    def __init__(self, lado, color, tag=None):
        self.lado, self.color, self.tag = lado, color, tag

    def size(self, cr):
        return self.lado, self.lado

    def draw(self, cr, x, cy, a):
        y = cy - self.lado / 2.0
        if self.tag:
            _record(self.tag, x, cy, self.lado, self.lado)
        capsule(cr, x, y, self.lado, self.lado, self.lado * 0.28)
        cr.set_source_rgba(*self.color, a)
        cr.fill_preserve()
        # Un filo claro: un color oscuro sobre el negro de la isla seria
        # un agujero y no una muestra.
        cr.set_source_rgba(1, 1, 1, 0.22 * a)
        cr.set_line_width(1.0)
        cr.stroke()


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


def _frac(v):
    """El valor, leido EN VIVO si viene de un muelle.

    El contenido de la isla no se reconstruye en cada fotograma --solo
    se repinta-, asi que un numero guardado al construir se queda
    congelado: la barra marcaria el valor que tenia al llegar el evento
    y no se moveria nunca. Aceptando el muelle --o una funcion- en vez
    de su valor, el dibujado lee el de ESTE fotograma. Es lo mismo que
    hace la onda del dictado con la lista de niveles.
    """
    if callable(v):
        x = v()
    else:
        x = v.value if hasattr(v, "value") else v
    return max(0.0, min(1.0, x))


class Bar(object):
    """Barra de progreso de extremos redondos (volumen, brillo)."""
    def __init__(self, w, h, frac, color, bg=T.DIM2):
        self.w, self.h, self.frac = w, h, frac
        self.color, self.bg = color, bg

    def size(self, cr):
        return self.w, self.h

    def draw(self, cr, x, cy, a):
        y = cy - self.h / 2.0
        capsule(cr, x, y, self.w, self.h)
        cr.set_source_rgba(*self.bg, a)
        cr.fill()
        fw = self.w * _frac(self.frac)
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
        if getattr(self, '_v', None) == _vuelta:
            return self._sz
        w = 0
        h = 0
        for it in self.items:
            iw, ih = it.size(cr)
            w += iw
            h = max(h, ih)
        self._v, self._sz = _vuelta, (w, h)
        return self._sz

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
        if getattr(self, '_v', None) == _vuelta:
            return self._sz
        w = 0
        h = -self.gap
        for r in self.rows:
            rw, rh = r.size(cr)
            w = max(w, rw)
            h += rh + self.gap
        self._v, self._sz = _vuelta, (w, h)
        return self._sz

    def draw(self, cr, x, cy, a):
        tw, th = self.size(cr)
        y = cy - th / 2.0
        for r in self.rows:
            rw, rh = r.size(cr)
            rx = x + (tw - rw) / 2.0 if self.center else x
            r.draw(cr, rx, y + rh / 2.0, a)
            y += rh + self.gap


class BarIndef(object):
    """Barra de progreso SIN progreso: un segmento que va y viene.

    Para esperas que no saben cuanto van a durar, como conectarse a una
    red: nmcli no informa de por donde va, asi que una barra que se
    llenara al 60% estaria inventandose un dato. Esto dice "sigo", que
    es lo unico que se sabe de verdad.
    """
    def __init__(self, w, h, fase, color, bg=T.SURF_2, trozo=0.32):
        self.w, self.h, self.fase = w, h, fase
        self.color, self.bg, self.trozo = color, bg, trozo

    def size(self, cr):
        return self.w, self.h

    def draw(self, cr, x, cy, a):
        y = cy - self.h / 2.0
        capsule(cr, x, y, self.w, self.h)
        cr.set_source_rgba(*self.bg, a)
        cr.fill()
        # Ida y vuelta con el mismo ciclo que ya late en la isla: en vez
        # de dar la vuelta y reaparecer por el otro lado --que se lee
        # como un salto- rebota en los extremos.
        f = (self.fase.value if hasattr(self.fase, "value") else self.fase) % 1.0
        t = 2.0 * f if f < 0.5 else 2.0 * (1.0 - f)
        seg = self.w * self.trozo
        cx = (self.w - seg) * t
        capsule(cr, x + cx, y, seg, self.h)
        cr.set_source_rgba(*self.color, a)
        cr.fill()


class Chispa(object):
    """Historial de carga como area rellena.

    Lee la lista EN VIVO, igual que la onda del dictado: el contenido
    de la isla no se reconstruye en cada muestra, asi que una copia
    tomada al construir se quedaria congelada en el primer valor.

    Area y no barras: lo que importa de una grafica de carga a 40 px de
    ancho no es cada muestra, es la FORMA --si viene subiendo o si fue
    un pico y ya paso-, y el relleno la cuenta de un vistazo.
    """
    def __init__(self, valores, w, h, color, alfa=0.30):
        self.valores, self.w, self.h = valores, w, h
        self.color, self.alfa = color, alfa
        self._tex = None
        self._pts = None

    def size(self, cr):
        return self.w, self.h

    def draw(self, cr, x, cy, a):
        vals = self.valores
        n = len(vals)
        if n < 2:
            return
        # Un punto por cada cuatro pixeles como mucho. Con noventa
        # muestras en doscientos pixeles, la mitad caen encima de otro
        # y lo unico que hacen es alargar el trazado -- y cada line_to
        # es una llamada desde Python, que es lo que de verdad cuesta
        # aqui: medido, 0,9 ms por fotograma antes de esto.
        paso_i = max(1, int(round(n / max(2.0, self.w / 4.0))))
        pts = tuple(max(0.0, min(1.0, v)) for v in list(vals)[::paso_i])

        # La grafica se guarda dibujada. Los datos cambian una vez cada
        # dos segundos y la isla repinta treinta veces por segundo: sin
        # esto se vuelve a trazar la misma curva sesenta veces por cada
        # vez que de verdad cambia algo. Comparar los puntos cuesta
        # microsegundos; trazarla, medio milisegundo.
        if pts != self._pts or self._tex is None:
            self._pts = pts
            self._tex = self._pinta(pts)
        cr.save()
        cr.set_source_surface(self._tex, x, cy - self.h / 2.0)
        cr.paint_with_alpha(a)
        cr.restore()

    def _pinta(self, pts):
        """El trazado se construye UNA vez: se traza la linea
        conservandolo, se le cierran los bajos y se rellena. Antes se
        recorrian los puntos dos veces, una por cada cosa."""
        w, h = int(self.w), int(self.h)
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(surf)
        dx = self.w / float(len(pts) - 1) if len(pts) > 1 else self.w
        cr.move_to(0, h - pts[0] * h)
        for i, v in enumerate(pts):
            cr.line_to(i * dx, h - v * h)
        cr.set_source_rgba(*self.color, 1.0)
        cr.set_line_width(1.6)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.stroke_preserve()
        cr.line_to((len(pts) - 1) * dx, h)
        cr.line_to(0, h)
        cr.close_path()
        cr.set_source_rgba(*self.color, self.alfa)
        cr.fill()
        surf.flush()
        return surf


class Columnas(object):
    """Una barra por nucleo, de abajo arriba.

    Con doce nucleos, un numero por cada uno seria una tabla que hay
    que leer. Doce barras se ven de golpe: lo que se busca aqui es si
    la carga esta repartida o si hay uno clavado al 100%.
    """
    def __init__(self, valores, w, gap, h, color, bg=T.SURF_2):
        self.valores, self.w, self.gap, self.h = valores, w, gap, h
        self.color, self.bg = color, bg

    def size(self, cr):
        n = max(1, len(self.valores))
        return n * self.w + (n - 1) * self.gap, self.h

    def draw(self, cr, x, cy, a):
        y0 = cy + self.h / 2.0
        for v in self.valores:
            v = max(0.0, min(1.0, v))
            capsule(cr, x, y0 - self.h, self.w, self.h, self.w / 2.0)
            cr.set_source_rgba(*self.bg, a)
            cr.fill()
            alto = max(self.w, self.h * v)
            capsule(cr, x, y0 - alto, self.w, alto, self.w / 2.0)
            cr.set_source_rgba(*self.color, a)
            cr.fill()
            x += self.w + self.gap


class Aros(object):
    """Dos arcos concentricos, como el reloj de Apple.

    Dos columnas de seis pixeles eran dos rayas: se veia que habia
    algo, no cuanto marcaba. Un anillo da mucha mas superficie de color
    en el mismo sitio --el trazo recorre todo el perimetro en vez de
    subir por una linea recta-- y el gesto de "se va llenando en
    sentido horario" se lee sin leer ningun numero.

    Fuera el procesador y dentro la memoria, en ese orden a proposito:
    el de fuera es el arco mas largo y el que primero se ve, y de los
    dos el que de verdad se mira de reojo es la carga.

    Lee las listas EN VIVO, igual que Columnas: el contenido de la isla
    no se reconstruye en cada muestra, asi que un valor copiado al
    construir se quedaria clavado en el primero.
    """
    def __init__(self, fuera, dentro, d, grosor, col_fuera, col_dentro,
                 hueco=2.0, bg=T.SURF_2):
        self.fuera, self.dentro = fuera, dentro
        self.d, self.grosor, self.hueco = d, grosor, hueco
        self.col_fuera, self.col_dentro = col_fuera, col_dentro
        self.bg = bg

    def size(self, cr):
        return self.d, self.d

    def draw(self, cr, x, cy, a):
        # Si viene un punto actual de lo anterior --un texto dibujado
        # con Pango lo deja puesto--, el primer arco se traeria una
        # linea desde el hasta el borde del anillo.
        cr.new_path()
        cx = x + self.d / 2.0
        r = (self.d - self.grosor) / 2.0
        cr.set_line_width(self.grosor)
        for vals, col in ((self.fuera, self.col_fuera),
                          (self.dentro, self.col_dentro)):
            if r < self.grosor * 0.6:
                break
            v = max(0.0, min(1.0, vals[0] if vals else 0.0))
            # La pista entera, con remate plano: es una circunferencia
            # cerrada y los extremos no se ven.
            cr.set_line_cap(cairo.LINE_CAP_BUTT)
            cr.set_source_rgba(*self.bg, a)
            cr.arc(cx, cy, r, 0, 2 * math.pi)
            cr.stroke()
            if v > 0.004:
                # El arco lleno arranca ARRIBA y gira en sentido
                # horario: es de donde sale la lectura de reloj. Con
                # remate redondo, y por eso el minimo no es cero sino un
                # arco corto: al 1% se ve un punto, no nada.
                cr.set_line_cap(cairo.LINE_CAP_ROUND)
                cr.set_source_rgba(*col, a)
                ini = -math.pi / 2.0
                cr.arc(cx, cy, r, ini, ini + 2 * math.pi * v)
                cr.stroke()
            r -= self.grosor + self.hueco


class Slider(object):
    """Barra arrastrable (volumen, brillo).

    Registra su zona sensible con el ancho COMPLETO de la pista, no solo
    la parte rellena: si no, al bajar el volumen a cero la zona se
    encogeria hasta desaparecer y ya no habria forma de volver a subirlo
    arrastrando.
    """
    def __init__(self, w, h, frac, color, tag=None, knob=True):
        self.w, self.h = w, h
        self.frac = frac
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
        fw = self.w * _frac(self.frac)
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


# Texturas de resplandor ya generadas. La clave lleva el tamano
# REDONDEADO y el color cuantizado: mientras la isla se expande su
# anchura cambia en cada fotograma, y sin redondear se generaria una
# textura nueva 120 veces por segundo.
_glow_cache = {}
_GLOW_MAX = 24


def _glow_tex(w, h, color):
    esc = T.GLOW_ESC
    tw = max(1, int((w + 2 * T.GLOW_M) / esc))
    th = max(1, int((h + 2 * T.GLOW_M) / esc))
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, tw, th)
    cr = cairo.Context(surf)
    cr.scale(1.0 / esc, 1.0 / esc)
    n = T.GLOW_CAPAS
    # De fuera hacia dentro, sumando. Cada capa es la silueta de la
    # isla crecida un poco mas, asi que la luz CAE siguiendo su forma en
    # vez de ser un ovalo pegado detras.
    for i in range(n):
        k = i / float(n - 1) if n > 1 else 1.0     # 1 = la mas pegada
        crece = T.GLOW_M * (1.0 - k) ** T.GLOW_CURVA
        # La silueta va CENTRADA en la textura, con el margen por los
        # cuatro lados. Dibujandola pegada arriba, el halo salia 84 px
        # mas alto que la isla: se amontonaba en las esquinas de arriba
        # (que ademas caen fuera de la pantalla) y por abajo no llegaba.
        x = T.GLOW_M - crece
        y = T.GLOW_M - crece
        notch(cr, x, y, w + 2 * crece, h + 2 * crece,
              min((h + 2 * crece) / 2.0, T.NOTCH_R + crece), 0.0)
        cr.set_source_rgba(color[0], color[1], color[2], 1.0 / n)
        cr.fill()
    surf.flush()
    return surf


# El resplandor de DENTRO se guarda normalizado: la elipse se define en
# fracciones del tamano de la isla, asi que una sola textura por color
# sirve para cualquier anchura. Estirarla es justo lo que la hace
# "medio radial estirado".
_dentro_cache = {}
_DENTRO_TEX = (128, 64)


def _dentro_tex(color):
    tw, th = _DENTRO_TEX
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, tw, th)
    cr = cairo.Context(surf)
    g = cairo.RadialGradient(tw * 0.5, 0, 0,
                             tw * 0.5, 0, tw * T.GLOW_IN_RX)
    r, v, a = color
    # La caida, repartida en cinco paradas. Con dos o tres, el centro
    # se queda como un punto brillante y el resto cae de golpe: se ve
    # DONDE esta el foco, que es justo lo contrario de difuminado. Asi
    # no hay un punto, hay una zona.
    for pos, k in ((0.0, 1.0), (0.35, 0.80), (0.60, 0.45),
                   (0.80, 0.18), (1.0, 0.0)):
        g.add_color_stop_rgba(pos, r, v, a, k)
    # La elipse: ancha y baja. El centro va EN el canto de arriba, asi
    # que lo que se ve es la mitad de abajo.
    cr.save()
    cr.scale(1.0, th * T.GLOW_IN_RY / (tw * T.GLOW_IN_RX))
    cr.set_source(g)
    cr.rectangle(0, 0, tw, th / (th * T.GLOW_IN_RY / (tw * T.GLOW_IN_RX)))
    cr.fill()
    cr.restore()
    surf.flush()
    return surf


def resplandor_dentro(cr, x, y, w, h, color, alpha, crece=0.0):
    """La luz DENTRO del notch: medio radial estirado, pegado al canto
    de arriba.

    Va despues de recortar a la silueta y antes del contenido, asi que
    el texto queda por encima y se sigue leyendo igual. Es la misma
    idea que el halo de fuera pero al reves: en vez de iluminar el
    escritorio, ilumina el propio cuerpo negro.
    """
    if alpha <= 0.004:
        return
    clave = (int(color[0] * 24), int(color[1] * 24), int(color[2] * 24))
    tex = _dentro_cache.get(clave)
    if tex is None:
        if len(_dentro_cache) >= 24:
            _dentro_cache.clear()
        tex = _dentro_cache[clave] = _dentro_tex(color)
    tw, th = tex.get_width(), tex.get_height()
    # El alto de la luz tiene tope: en un panel alto la elipse llegaria
    # hasta abajo y seria un tinte, no una luz que entra por arriba.
    alto = min(h, T.GLOW_IN_MAXH) * (1.0 + crece)
    ancho = w * (1.0 + crece)
    cr.save()
    # Lo que crece lo hace desde el centro del canto, que es donde esta
    # el foco de la elipse: creciendo desde la esquina, el latido se
    # leeria como un desplazamiento lateral.
    #
    # Y el canto es el de ABAJO: la textura se pinta con el alto en
    # negativo, que la voltea. Arriba el notch esta pegado al borde de
    # la pantalla y la luz muere contra un canto recto; abajo monta
    # sobre las dos esquinas redondas, que es la unica forma libre que
    # tiene, y se lee como luz del propio cuerpo.
    cr.translate(x - w * crece / 2.0, y + h if T.GLOW_IN_ABAJO else y)
    cr.scale(ancho / float(tw),
             (-alto if T.GLOW_IN_ABAJO else alto) / float(th))
    cr.set_source_surface(tex, 0, 0)
    cr.get_source().set_filter(cairo.FILTER_BILINEAR)
    cr.paint_with_alpha(alpha)
    cr.restore()


def resplandor(cr, x, y, w, h, color, alpha):
    """La luz que echa la isla por los bordes.

    Se dibuja ANTES de la isla y por fuera de ella: dentro no se ve,
    porque el cuerpo es negro opaco y lo tapa. Lo que se ve es el halo
    de color sobre el escritorio.
    """
    if alpha <= 0.004:
        return
    clave = (int(w) // 16 * 16, int(h) // 8 * 8,
             int(color[0] * 24), int(color[1] * 24), int(color[2] * 24))
    tex = _glow_cache.get(clave)
    if tex is None:
        if len(_glow_cache) >= _GLOW_MAX:
            _glow_cache.clear()
        tex = _glow_cache[clave] = _glow_tex(clave[0] or 16, clave[1] or 8,
                                             color)
    tw, th = tex.get_width(), tex.get_height()
    # La textura se genero para el tamano redondeado: al pintarla se
    # estira al de verdad. Un halo desenfocado estirado unos pixeles no
    # se distingue de uno generado a medida, y asi la cache sirve para
    # toda la animacion de expansion.
    dw = w + 2 * T.GLOW_M
    dh = h + 2 * T.GLOW_M
    cr.save()
    cr.translate(x - T.GLOW_M, y - T.GLOW_M)
    cr.scale(dw / float(tw), dh / float(th))
    cr.set_source_surface(tex, 0, 0)
    cr.get_source().set_filter(cairo.FILTER_BILINEAR)
    cr.paint_with_alpha(alpha)
    cr.restore()


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
            _record(self.tag, x, cy, w, h, pad=0, radius=self.radius)
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


class Wave(object):
    """Onda del microfono: una barra por muestra reciente, la nueva a la
    derecha.

    Es la señal REAL que entra, no una animacion decorativa. La
    diferencia importa: con una onda falsa, un micro silenciado o un
    cable suelto se ven exactamente igual que una grabacion buena, y te
    enteras treinta segundos despues, al leer la transcripcion vacia.

    Las barras viejas se van apagando hacia la izquierda. Eso da la
    sensacion de desplazamiento sin mover nada: lo unico que cambia
    entre fotogramas es la altura y el alfa de cada barra, que es
    bastante mas barato que desplazar un trazado.
    """
    def __init__(self, levels, color, n, w, gap, hmax, hmin):
        self.levels = levels
        self.color = color
        self.n, self.w, self.gap = n, w, gap
        self.hmax, self.hmin = hmax, hmin

    def size(self, cr):
        return self.n * self.w + (self.n - 1) * self.gap, self.hmax

    def draw(self, cr, x, cy, a):
        # Se pinta siempre el mismo numero de barras: con menos muestras
        # que barras, las que faltan van a la izquierda y en silencio,
        # asi que la onda "entra" en vez de aparecer de golpe.
        faltan = self.n - len(self.levels)
        vals = [0.0] * max(0, faltan) + list(self.levels)[-self.n:]
        for i, v in enumerate(vals):
            h = self.hmin + (self.hmax - self.hmin) * max(0.0, min(1.0, v))
            # La mas nueva a plena luz; las viejas se apagan, pero nunca
            # del todo: a cero parecerian un hueco en la onda.
            alfa = (0.45 + 0.55 * (i + 1) / float(self.n)) * a
            cr.set_source_rgba(*self.color, alfa)
            capsule(cr, x + i * (self.w + self.gap), cy - h / 2.0,
                    self.w, h, self.w / 2.0)
            cr.fill()


class Pulse(object):
    """Tres puntos que laten por turnos: 'esto esta trabajando'.

    Se usa mientras transcribe, que es el unico tramo en el que la isla
    no tiene nada que contar y no se sabe cuanto va a durar. Una barra
    de progreso mentiria, porque whisper no informa de su avance.
    """
    def __init__(self, phase, color, r=5, gap=9, n=3):
        self.phase, self.color = phase % 1.0, color
        self.r, self.gap, self.n = r, gap, n

    def size(self, cr):
        return self.n * 2 * self.r + (self.n - 1) * self.gap, 2 * self.r

    def draw(self, cr, x, cy, a):
        for i in range(self.n):
            # Un tercio de ciclo de desfase entre puntos: el ojo lee la
            # secuencia como un desplazamiento, no como tres parpadeos.
            f = (self.phase - i / float(self.n)) % 1.0
            alfa = (0.25 + 0.75 * (0.5 - 0.5 * math.cos(2 * math.pi * f))) * a
            cr.set_source_rgba(*self.color, alfa)
            cr.arc(x + i * (2 * self.r + self.gap) + self.r, cy, self.r,
                   0, 2 * math.pi)
            cr.fill()


class Alfa(object):
    """Envuelve a otro elemento y lo dibuja con su alfa multiplicado.

    Sirve para que una pieza suelta entre con un fundido propio sin
    tocar el del resto del contenido. No cambia el tamaño: el hueco ya
    esta reservado desde el primer fotograma, asi que la fila no se
    recoloca mientras aparece.

    `k` puede ser un numero o cualquier cosa con `.value` (un muelle).
    Lo segundo es lo normal aqui: el contenido NO se reconstruye en cada
    fotograma, asi que un numero capturado al construir dejaria el
    fundido congelado en su primer valor.
    """
    def __init__(self, hijo, k):
        self.hijo = hijo
        self.k = k

    def _alfa(self):
        k = self.k
        k = k.value if hasattr(k, "value") else k
        return max(0.0, min(1.0, k))

    def size(self, cr):
        return self.hijo.size(cr)

    def draw(self, cr, x, cy, a):
        k = self._alfa()
        if k <= 0.001:
            return
        self.hijo.draw(cr, x, cy, a * k)


# ---------------------------------------------------------------- emoji

# Cache propia, aparte de la de los textos.
#
# Una pagina del selector son 50 emoji, y navegando se recorren los
# 1914: compartir la cache de textos la haria desbordar y vaciarse cada
# cuatro paginas, llevandose por delante el reloj y los porcentajes, que
# si se repiten en cada fotograma.
_emoji_cache = {}
_EMOJI_MAX = 2048


def _emoji_layout(cr, ch):
    l = _emoji_cache.get(ch)
    if l is None:
        if len(_emoji_cache) >= _EMOJI_MAX:
            _emoji_cache.clear()
        l = PangoCairo.create_layout(cr)
        l.set_font_description(font_desc(T.F_EMOJI))
        l.set_text(ch, -1)
        _emoji_cache[ch] = l
    return l


def emoji_soportados(entradas):
    """Filtra los emoji que la fuente instalada NO sabe dibujar.

    Hace falta porque los datos de Unicode van por delante de las
    fuentes: el fichero del sistema puede describir emoji que la Noto
    instalada no tiene, y en la rejilla saldrian como cuadros vacios.

    No se puede preguntar por el numero de glifos desconocidos, que es
    lo que uno esperaria: fontconfig tapa el hueco con OTRA fuente, asi
    que Pango informa de cero y el cuadro aparece igual. Lo que si se ve
    es el ANCHO. Un emoji dibujado de verdad ocupa una casilla; una
    secuencia que la fuente no conoce se descompone en sus piezas y
    ocupa dos o mas. Comprobado con secuencias inventadas: salen al
    doble de ancho exacto.

    Son ~150 ms para los 1914, de una vez por arranque.
    """
    if not entradas:
        return []
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)
    cr = cairo.Context(s)
    ref = _emoji_layout(cr, "\U0001F600").get_pixel_size()[0]
    tope = ref * 1.4
    out = []
    for e in entradas:
        l = _emoji_layout(cr, e[0])
        if l.get_pixel_size()[0] <= tope and l.get_unknown_glyphs_count() == 0:
            out.append(e)
    # Los layouts de los descartados no vuelven a hacer falta.
    _emoji_cache.clear()
    return out


class Emoji(object):
    """Un emoji, con los colores de la fuente.

    No es un Text con otra fuente, y la diferencia esta medida: una
    fuente de color se pinta con SUS colores e ignora por completo el
    origen de cairo, el alfa incluido. Pidiendo rgba(1,1,1,0) el emoji
    sale igual de opaco (misma suma de alfa con 1.0, 0.5 y 0.0), asi que
    con Text se habria colado entero en mitad de los fundidos de la
    isla, sin desvanecerse con el resto del contenido.

    Dibujarlo en un grupo y volcarlo con paint_with_alpha si funde: a
    mitad de fundido el alfa maximo es 128 de 255, y a cero no queda
    nada.
    """
    def __init__(self, ch, alpha=1.0, tag=None):
        self.ch, self.alpha, self.tag = ch, alpha, tag

    def size(self, cr):
        return _emoji_layout(cr, self.ch).get_pixel_size()

    def draw(self, cr, x, cy, a):
        l = _emoji_layout(cr, self.ch)
        w, h = l.get_pixel_size()
        if self.tag:
            _record(self.tag, x, cy, w, h)
        PangoCairo.update_layout(cr, l)
        cr.push_group()
        cr.move_to(x, cy - h / 2.0)
        cr.set_source_rgba(1, 1, 1, 1)
        PangoCairo.show_layout(cr, l)
        cr.pop_group_to_source()
        cr.paint_with_alpha(max(0.0, min(1.0, self.alpha * a)))


class Cell(object):
    """Casilla de tamano fijo que centra lo que lleva dentro.

    Box fuerza el ancho pero alinea a la izquierda, que es lo que quiere
    una lista. Una rejilla quiere lo contrario: que cada cosa caiga en el
    centro de su casilla, para que las columnas salgan rectas aunque lo
    de dentro mida distinto.
    """
    def __init__(self, inner, w, h, bg=None, radius=14, tag=None):
        self.inner, self.w, self.h = inner, w, h
        self.bg, self.radius, self.tag = bg, radius, tag

    def size(self, cr):
        return self.w, self.h

    def draw(self, cr, x, cy, a):
        if self.tag:
            _record(self.tag, x, cy, self.w, self.h, pad=0,
                    radius=self.radius)
        if self.bg is not None:
            m = 3.0           # aire para que el realce no toque al vecino
            capsule(cr, x + m, cy - self.h / 2.0 + m,
                    self.w - 2 * m, self.h - 2 * m, self.radius)
            cr.set_source_rgba(*self.bg, a)
            cr.fill()
        iw, _ih = self.inner.size(cr)
        self.inner.draw(cr, x + (self.w - iw) / 2.0, cy, a)

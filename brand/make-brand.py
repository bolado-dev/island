#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Genera el logo y el banner del proyecto.

Los dibuja con el MISMO codigo que pinta la interfaz (render.notch,
render.capsule, los colores de theme). Asi la silueta de la marca no es
una imitacion hecha en un editor que se desincroniza en cuanto cambian
las proporciones: es la forma real, con sus enlaces concavos y su radio
inferior.

    python3 brand/make-brand.py

Escribe en docs/: logo.svg, logo.png, banner.png
"""
import os
import sys
import math
import cairo
import gi

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
import theme as T
import render as R

DOCS = os.path.join(RAIZ, "docs")
VIOLETA_A = (0.482, 0.247, 0.894)    # el violeta del fondo de las capturas
VIOLETA_B = (0.357, 0.169, 0.878)


def texto(cr, txt, familia, peso, px, color, x, y, centrado=False):
    cap = PangoCairo.create_layout(cr)
    d = Pango.FontDescription()
    d.set_family(familia)
    d.set_weight(peso)
    d.set_absolute_size(px * Pango.SCALE)
    cap.set_font_description(d)
    cap.set_text(txt, -1)
    w, h = cap.get_pixel_size()
    cr.save()
    cr.set_source_rgba(*color)
    cr.move_to(x - (w / 2.0 if centrado else 0), y)
    PangoCairo.show_layout(cr, cap)
    cr.restore()
    return w, h


def contenido_notch(cr, x, y, w, h):
    """Lo que lleva dentro el notch en reposo, a escala del banner."""
    cy = y + h / 2.0
    texto(cr, "9:41", "Inter Display", Pango.Weight.SEMIBOLD,
          h * 0.46, T.FG + (1.0,), x + h * 0.38, cy - h * 0.30)

    # Indicador de escritorios: dos ocupados, el tercero activo.
    sx = x + w * 0.42
    paso = h * 0.30
    for i in range(7):
        activo = (i == 2)
        bw = h * 0.44 if activo else h * 0.13
        bh = h * 0.095
        col = T.ACCENT if activo else (T.FG if i < 2 else T.DIM2)
        R.capsule(cr, sx, cy - bh / 2.0, bw, bh, bh / 2.0)
        cr.set_source_rgba(*col, 1.0)
        cr.fill()
        sx += bw + paso * 0.55

    # Bateria, a la derecha.
    bx = x + w - h * 1.30
    bw2, bh2 = h * 0.52, h * 0.26
    R.capsule(cr, bx, cy - bh2 / 2.0, bw2, bh2, bh2 * 0.34)
    cr.set_source_rgba(*T.FG, 0.92)
    cr.set_line_width(max(1.0, h * 0.035))
    cr.stroke()
    R.capsule(cr, bx + bh2 * 0.14, cy - bh2 * 0.26,
              bw2 * 0.58, bh2 * 0.52, bh2 * 0.18)
    cr.set_source_rgba(*T.FG, 0.92)
    cr.fill()


def logo(px=512):
    """Marca cuadrada: el notch colgando de un tile redondeado."""
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, px, px)
    cr = cairo.Context(surf)
    k = px / 48.0                      # el diseno esta pensado en 48

    g = cairo.LinearGradient(0, px, px, 0)
    g.add_color_stop_rgb(0, *VIOLETA_A)
    g.add_color_stop_rgb(1, *VIOLETA_B)
    R.capsule(cr, 0, 0, px, px, px * 0.22)
    cr.set_source(g)
    cr.fill()

    # Mismas proporciones que el icono del portfolio: notch de 26x17
    # sobre 48, radio inferior 6, filete 4.
    R.notch(cr, 11 * k, 0, 26 * k, 17 * k, 6 * k, 4 * k)
    cr.set_source_rgb(*T.ISLAND)
    cr.fill()

    R.capsule(cr, 19 * k, 6.6 * k, 10 * k, 3.2 * k, 1.6 * k)
    cr.set_source_rgb(*T.ACCENT)
    cr.fill()

    surf.write_to_png(os.path.join(DOCS, "logo.png"))
    return px


def banner(w=1280, h=640):
    """Vista social de GitHub. 1280x640 es lo que pide."""
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(surf)

    g = cairo.LinearGradient(0, h, w, 0)
    g.add_color_stop_rgb(0.0, 0.33, 0.16, 0.74)
    g.add_color_stop_rgb(0.55, *VIOLETA_A)
    g.add_color_stop_rgb(1.0, 0.56, 0.31, 0.93)
    cr.rectangle(0, 0, w, h)
    cr.set_source(g)
    cr.fill()

    # El notch cuelga del borde SUPERIOR del banner, igual que de la
    # pantalla: es la parte de la marca que no se puede mover de sitio.
    nw, nh = 620.0, 54.0
    nx = (w - nw) / 2.0
    R.notch(cr, nx, 0, nw, nh, 30, 18)
    cr.set_source_rgb(*T.ISLAND)
    cr.fill()
    contenido_notch(cr, nx, 0, nw, nh)

    texto(cr, "island", "Inter Display", Pango.Weight.SEMIBOLD,
          128, T.FG + (1.0,), w / 2.0, h * 0.30, centrado=True)
    texto(cr, "Un notch para bspwm con la mec\u00e1nica del Dynamic Island",
          "Inter", Pango.Weight.MEDIUM, 31, (1, 1, 1, 0.82),
          w / 2.0, h * 0.585, centrado=True)
    texto(cr, "GTK 3  ·  cairo  ·  60 fps  ·  X11",
          "Inter", Pango.Weight.MEDIUM, 23, (1, 1, 1, 0.52),
          w / 2.0, h * 0.745, centrado=True)

    surf.write_to_png(os.path.join(DOCS, "banner.png"))
    return w, h


if __name__ == "__main__":
    os.makedirs(DOCS, exist_ok=True)
    print("logo.png   %dx%d" % (logo(), logo()))
    print("banner.png %dx%d" % banner())

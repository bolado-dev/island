#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Capturas de pantalla para la isla: disparas y el notch te la ensena.

    captura.py select     # una region, con la interfaz de flameshot
    captura.py window     # la ventana enfocada
    captura.py screen     # la pantalla entera

Tres decisiones que explican la forma de esto:

**El notch se aparta antes de disparar.** La tarjeta de la captura
ANTERIOR sigue a la vista cuando encadenas dos, que es el caso normal, y
saldria en la foto. Se le pide que se repliegue y se espera a que lo
haga (config.CAPTURA_ESPERA). No es un retardo de cortesia: esta medido.

**La miniatura la hace este proceso, no la isla.** Medido en esta
maquina: sacarla del PNG completo (2880x1800, 627 KB) son 34 ms y
sacarla de la miniatura ya hecha, 1. Treinta veces menos, y sobre todo
no son 34 ms en el hilo de GTK --dos fotogramas perdidos- justo en la
animacion de entrada de la tarjeta. Aqui no estorban a nadie.

**Al portapapeles siempre.** Es lo que uno espera de una captura, y es
lo que ya hacia el atajo de flameshot. Que ademas quede el fichero es
para poder volver a ella; que este copiada es para usarla ya.
"""
import os
import sys
import time
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
import sources

import gi
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf

RUN = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "island-captura")
# Alto de la miniatura. Se genera al doble para que no se vea blanda en
# una pantalla HiDPI, que es justo donde se mira una captura.
THUMB_H = 144

MODOS = {
    # scrot 2.0: --freeze congela la pantalla mientras seleccionas, que
    # es lo que evita que lo que querias capturar cambie debajo del
    # raton. --line sin opacidad porque el borde de seleccion se dibuja
    # sobre la imagen congelada.
    # --freeze congela la pantalla mientras eliges, que es lo que
    # permite capturar un menu abierto sin que se cierre al mover el
    # raton. Lo hace con XGrabServer, asi que mientras dura NINGUN otro
    # cliente de X puede dibujar: la isla se queda quieta y xdotool no
    # llega. Es tambien el motivo del tope de 60 s de mas abajo, que no
    # es decorativo: si scrot se colgase, el escritorio entero se
    # quedaria congelado hasta que alguien lo matase.
    "select": ["--freeze", "--select", "--line", "mode=edge"],
    "window": ["--focused", "--border"],
    "screen": [],
}


PIDF = os.path.join(RUN, "pid")


def ya_hay_una():
    """True si otra captura esta en marcha.

    Importa de verdad con la seleccion: scrot congela la pantalla
    mientras eliges, y dos a la vez dejan dos pantallas congeladas una
    encima de otra, cada una esperando su arrastre. Pasa solo con
    repetir el atajo sin querer.
    """
    try:
        with open(PIDF) as f:
            otro = int(f.read().strip())
    except (OSError, ValueError):
        return False
    try:
        os.kill(otro, 0)          # solo pregunta si existe
        return True
    except OSError:
        return False


def apartar_notch():
    """Pide a la isla que se quite de en medio y espera a que lo haga."""
    if sources.enviar_evento(kind="dismiss", target="captura"):
        time.sleep(C.CAPTURA_ESPERA)


def _con_flameshot(destino):
    """Seleccion con la interfaz de flameshot, en crudo.

    --raw escupe el PNG por la salida estandar en vez de guardarlo, asi
    que el fichero lo escribe esto: un solo sitio decide donde van las
    capturas y como se llaman, y flameshot no ensena ademas su propio
    aviso de guardado encima de la tarjeta de la isla.

    Cancelar (Escape) devuelve cero bytes, que no es un fallo.
    """
    try:
        r = subprocess.run(["flameshot", "gui", "--raw"],
                           capture_output=True, timeout=180)
    except FileNotFoundError:
        return None, "falta"
    except subprocess.SubprocessError:
        return None, "La captura no termino"
    if r.returncode != 0 or not r.stdout:
        return None, ""
    with open(destino, "wb") as f:
        f.write(r.stdout)
    return destino, ""


def disparar(modo):
    os.makedirs(C.CAPTURA_DIR, exist_ok=True)
    destino = os.path.join(C.CAPTURA_DIR, time.strftime(C.CAPTURA_FMT))

    if modo == "select" and C.CAPTURA_SELECTOR == "flameshot":
        ruta, err = _con_flameshot(destino)
        if err != "falta":
            return ruta, err
        # Sin flameshot instalado no se queda uno sin capturar: cae a
        # scrot, que es la dependencia que el proyecto si declara.

    try:
        r = subprocess.run(["scrot", "-q", "100"] + MODOS[modo] + [destino],
                           capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        return None, "Falta scrot"
    except subprocess.SubprocessError:
        return None, "La captura no termino"
    if r.returncode != 0 or not os.path.exists(destino):
        # Cancelar la seleccion con Escape es la salida normal, no un
        # fallo: no se avisa de nada.
        return None, ""
    return destino, ""


def miniatura(ruta):
    """Miniatura proporcional. Devuelve (ruta, ancho, alto) del original."""
    try:
        pb = GdkPixbuf.Pixbuf.new_from_file(ruta)
    except Exception:
        return None, 0, 0
    w, h = pb.get_width(), pb.get_height()
    os.makedirs(RUN, exist_ok=True)
    chica = os.path.join(RUN, "thumb.png")
    escala = min(1.0, THUMB_H / float(h))
    try:
        pb.scale_simple(max(1, int(w * escala)), max(1, int(h * escala)),
                        GdkPixbuf.InterpType.BILINEAR).savev(chica, "png",
                                                             [], [])
    except Exception:
        return None, w, h
    return chica, w, h


def al_portapapeles(ruta):
    try:
        with open(ruta, "rb") as f:
            subprocess.run(["xclip", "-selection", "clipboard",
                            "-t", "image/png"], stdin=f, timeout=5)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def main(modo):
    if modo not in MODOS:
        print(__doc__)
        return 2
    os.makedirs(RUN, exist_ok=True)
    if ya_hay_una():
        return 0
    with open(PIDF, "w") as f:
        f.write(str(os.getpid()))
    apartar_notch()
    ruta, err = disparar(modo)
    if ruta is None:
        if err:
            sources.enviar_evento(kind="notify", app="Captura", body=err)
        return 0 if not err else 1

    chica, w, h = miniatura(ruta)
    copiada = al_portapapeles(ruta)
    sources.enviar_evento(kind="captura", path=ruta, thumb=chica or "",
                          title=os.path.basename(ruta),
                          text="%d × %d" % (w, h) if w else "",
                          hint="copiada" if copiada else "guardada")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "select"))
    finally:
        try:
            os.unlink(PIDF)
        except OSError:
            pass

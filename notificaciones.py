# -*- coding: utf-8 -*-
"""Servidor de notificaciones: la isla, en D-Bus.

Hasta ahora en medio habia un dunst con `skip_display = true` --o sea,
sin pintar nada- que recibia la notificacion y se la pasaba a la isla
por un script. Ese relevo PIERDE lo que mas importa:

  - Electron (Discord, Slack, Signal...) manda el avatar como pixeles
    dentro de la propia llamada, en la pista `image-data`. dunst la
    guarda en memoria para dibujarla y no se la da a los scripts: al
    hook le llega el icono VACIO. Medido.
  - Chrome manda la ruta de un fichero temporal que borra enseguida.
    Cuando dunst ejecuta el script, ya no existe. Medido tambien.

Recibiendo la llamada nosotros no hay nada que perder: los pixeles
vienen dentro y el fichero se lee en el acto.

Y se va con el relevo todo lo que hacia falta para apanarlo: el script,
el `dunstctl history | jq` con el que se averiguaba de que web venia
cada aviso --ahora las URL vienen en la propia llamada- y el propio
dunst.

Lo que NO hace todavia: botones de accion, responder desde el notch e
historial. Nada de eso cabia antes y ahora si cabe; no esta hecho.
"""
import os
import subprocess

import gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gio, GLib, GdkPixbuf

import config as C

RUTA = "/org/freedesktop/Notifications"
NOMBRE = "org.freedesktop.Notifications"

# Lo que decimos saber hacer. Se declara SOLO lo que de verdad se hace:
# anunciar "actions" sin pintar botones haria que las aplicaciones
# ofrecieran respuestas que no llevan a ninguna parte.
CAPACIDADES = ["body", "body-markup", "icon-static", "persistence"]

INTROSPECCION = """
<node>
  <interface name='org.freedesktop.Notifications'>
    <method name='GetCapabilities'>
      <arg type='as' name='capabilities' direction='out'/>
    </method>
    <method name='Notify'>
      <arg type='s' name='app_name' direction='in'/>
      <arg type='u' name='replaces_id' direction='in'/>
      <arg type='s' name='app_icon' direction='in'/>
      <arg type='s' name='summary' direction='in'/>
      <arg type='s' name='body' direction='in'/>
      <arg type='as' name='actions' direction='in'/>
      <arg type='a{sv}' name='hints' direction='in'/>
      <arg type='i' name='expire_timeout' direction='in'/>
      <arg type='u' name='id' direction='out'/>
    </method>
    <method name='CloseNotification'>
      <arg type='u' name='id' direction='in'/>
    </method>
    <method name='GetServerInformation'>
      <arg type='s' name='name' direction='out'/>
      <arg type='s' name='vendor' direction='out'/>
      <arg type='s' name='version' direction='out'/>
      <arg type='s' name='spec_version' direction='out'/>
    </method>
    <signal name='NotificationClosed'>
      <arg type='u' name='id'/>
      <arg type='u' name='reason'/>
    </signal>
    <signal name='ActionInvoked'>
      <arg type='u' name='id'/>
      <arg type='s' name='action_key'/>
    </signal>
  </interface>
</node>
"""

URGENCIAS = {0: "low", 1: "normal", 2: "critical"}

# Tope del plazo que puede pedir una aplicacion, en segundos.
TTL_MAX = 8.0

# Razones de cierre del spec: 1 caduco, 2 lo cerro el usuario, 3 lo
# cerro la aplicacion, 4 cualquier otra.
CADUCO, USUARIO, APLICACION = 1, 2, 3


def _pixbuf_de_datos(var, lado):
    """La pista image-data: (ancho, alto, salto, alfa, bits, canales, bytes).

    Es la imagen EN CRUDO dentro de la llamada. Asi manda Electron el
    avatar, y es justo lo que no sobrevivia al relevo.
    """
    try:
        w, h, salto, alfa, bits, _canales, datos = var
        pb = GdkPixbuf.Pixbuf.new_from_bytes(
            GLib.Bytes.new(bytes(datos)), GdkPixbuf.Colorspace.RGB,
            bool(alfa), int(bits), int(w), int(h), int(salto))
        return _escala(pb, lado)
    except Exception:
        return None


def _escala(pb, lado):
    if pb is None:
        return None
    if pb.get_width() == lado and pb.get_height() == lado:
        return pb
    return pb.scale_simple(lado, lado, GdkPixbuf.InterpType.BILINEAR)


def _pixbuf_de_ruta(ruta, lado):
    if not ruta:
        return None
    if ruta.startswith("file://"):
        from urllib.parse import urlparse, unquote
        ruta = unquote(urlparse(ruta).path)
    if not ruta.startswith("/") or not os.path.exists(ruta):
        return None
    try:
        return _escala(GdkPixbuf.Pixbuf.new_from_file(ruta), lado)
    except Exception:
        return None


class Servidor(object):
    """Toma el nombre de D-Bus y convierte cada llamada en un evento.

    El evento tiene la MISMA forma que el que llega por la tuberia
    (island-send), asi que la isla no tiene que saber de donde vino.
    """

    def __init__(self, al_llegar, lado=52):
        self.al_llegar = al_llegar
        self.lado = lado
        self.pausado = False        # el "no molestar", ahora de casa
        self.conn = None
        self.reg = None
        self._siguiente = 1
        self._vivas = {}            # id -> fuente del temporizador
        self._id = Gio.bus_own_name(
            Gio.BusType.SESSION, NOMBRE,
            # REPLACE para echar a quien tenga el nombre, y ALLOW para
            # dejar que otro nos lo quite a nosotros: si algun dia se
            # vuelve a dunst, basta con arrancarlo.
            Gio.BusNameOwnerFlags.REPLACE | Gio.BusNameOwnerFlags.ALLOW_REPLACEMENT,
            self._bus, None, self._perdido)

    # ------------------------------------------------------------ bus

    def _bus(self, conn, _nombre):
        self.conn = conn
        info = Gio.DBusNodeInfo.new_for_xml(INTROSPECCION)
        self.reg = conn.register_object(RUTA, info.interfaces[0],
                                        self._llamada, None, None)

    def _perdido(self, _conn, _nombre):
        # Lo normal es que no pase nunca. Si pasa, el escritorio se
        # queda sin notificaciones y hay que enterarse.
        print("isla: perdido %s (otro demonio lo ha tomado)" % NOMBRE,
              flush=True)

    def _llamada(self, _conn, _emisor, _ruta, _iface, metodo, params, inv):
        if metodo == "GetCapabilities":
            inv.return_value(GLib.Variant("(as)", (CAPACIDADES,)))
        elif metodo == "GetServerInformation":
            inv.return_value(GLib.Variant("(ssss)",
                                          ("island", "bolado-dev",
                                           "1.0", "1.2")))
        elif metodo == "Notify":
            inv.return_value(GLib.Variant("(u)", (self._notify(*params),)))
        elif metodo == "CloseNotification":
            self.cierra(int(params[0]), APLICACION)
            inv.return_value(None)
        else:
            inv.return_value(None)

    # -------------------------------------------------------- avisos

    def _notify(self, app, reemplaza, icono_app, titulo, cuerpo,
                _acciones, pistas, caduca):
        pistas = dict(pistas or {})
        nid = int(reemplaza) or self._nuevo_id()

        # Los OSD de volumen y brillo tienen su propia pildora en la
        # isla: los scripts llaman a island-send y dejan notify-send de
        # respaldo por si la isla no esta. Si llegan los dos, se veria
        # el mando y ademas una tarjeta diciendo lo mismo.
        if (app or "").strip().lower() in C.NOTIS_IGNORA:
            return nid

        # Un aviso que reemplaza a otro hereda su sitio: se cancela el
        # temporizador del viejo o cerraria al nuevo antes de tiempo.
        self._para(nid)

        if self.pausado:
            # "No molestar": se acepta y se contesta con su id --el spec
            # no tiene forma de decir "no lo he enseñado"- pero no se
            # enseña. Igual que hacia dunst.
            return nid

        ev = {"kind": "notify", "id": nid,
              "app": app or "", "title": titulo or "", "body": cuerpo or "",
              "urgency": URGENCIAS.get(_byte(pistas.get("urgency")), "normal"),
              "hint": _pistas_texto(pistas, cuerpo)}

        # La imagen, por orden de preferencia del spec: los pixeles que
        # vienen dentro mandan sobre cualquier ruta, y la ruta propia de
        # la notificacion sobre el icono de la aplicacion.
        pb = None
        for clave in ("image-data", "image_data", "icon_data"):
            if clave in pistas:
                pb = _pixbuf_de_datos(pistas[clave], self.lado)
                if pb is not None:
                    break

        # Las dos formas de decir una imagen por su sitio y no por sus
        # pixeles. Van juntas porque libnotify mete el icono de la linea
        # de ordenes (notify-send -i) en image-path y no en app_icon,
        # asi que mirar solo uno de los dos deja sin icono a medio
        # escritorio.
        sitios = [_str(pistas[c]) for c in ("image-path", "image_path")
                  if c in pistas]
        if icono_app:
            sitios.append(icono_app)
        if pb is None:
            for sitio in sitios:
                pb = _pixbuf_de_ruta(sitio, self.lado)
                if pb is not None:
                    break

        if pb is not None:
            ev["pix"] = pb
            ev["propio"] = True
        else:
            # Lo que no es una ruta es un nombre del tema de iconos: lo
            # resuelve la isla, que ya sabe y tiene su cache.
            nombre = next((s for s in sitios
                           if s and not s.startswith(("/", "file://"))), "")
            if nombre:
                ev["icon"] = nombre

        # El plazo que pide la aplicacion, con tope. Chrome pide 25
        # segundos para un mensaje de WhatsApp: en una burbuja que se
        # aparta se tolera, pero esto es el notch, y 25 segundos con la
        # isla abierta por un aviso que ya has leido es demasiado.
        if caduca is not None and int(caduca) > 0:
            ev["ttl"] = min(int(caduca) / 1000.0, TTL_MAX)
        self.al_llegar(ev)

        # El spec pide avisar al cerrarse, y no es cortesia: Chrome
        # espera ese aviso para soltar el temporal del avatar, y hay
        # aplicaciones que no mandan el siguiente hasta que se cierra el
        # anterior.
        espera = ev.get("ttl") or (None if ev["urgency"] == "critical"
                                   else 5.0)
        if espera:
            self._vivas[nid] = GLib.timeout_add(
                int(espera * 1000) + 250, self._caduca, nid)
        return nid

    def _nuevo_id(self):
        self._siguiente += 1
        return self._siguiente

    def _para(self, nid):
        fuente = self._vivas.pop(nid, None)
        if fuente:
            GLib.source_remove(fuente)

    def _caduca(self, nid):
        self._vivas.pop(nid, None)
        self._avisa_cierre(nid, CADUCO)
        return False

    def cierra(self, nid, razon=USUARIO):
        self._para(nid)
        self._avisa_cierre(nid, razon)

    def _avisa_cierre(self, nid, razon):
        if self.conn is None:
            return
        try:
            self.conn.emit_signal(None, RUTA, NOMBRE, "NotificationClosed",
                                  GLib.Variant("(uu)", (nid, razon)))
        except Exception:
            pass

    # --------------------------------------------------- no molestar

    def alterna_pausa(self):
        self.pausado = not self.pausado
        return self.pausado


def _byte(var):
    try:
        return int(var)
    except Exception:
        return 1


def _str(var):
    try:
        return str(var)
    except Exception:
        return ""


def _pistas_texto(pistas, cuerpo):
    """Las migas que sirven para saber de que servicio web viene.

    Antes salian de `dunstctl history | jq`; ahora vienen en la propia
    llamada. Las URL del cuerpo se sacan igual que hacia dunst: del
    marcado <a href>, que es lo unico que trae el origen en una
    notificacion de Chrome.
    """
    import re
    trozos = []
    for clave in ("desktop-entry", "x-dunst-stack-tag",
                  "x-canonical-private-synchronous", "category"):
        v = pistas.get(clave)
        if v is not None:
            trozos.append(_str(v))
    trozos += re.findall(r'href=[\'"]?([^\'" >]+)', cuerpo or "")
    return " ".join(t for t in trozos if t)


def para_dunst():
    """Aparta a dunst, si estaba.

    No basta con tomarle el nombre: se quedaria corriendo sin hacer
    nada, y ademas el servicio de activacion de D-Bus lo volveria a
    levantar en cuanto algo preguntase por el.
    """
    try:
        subprocess.run(["pkill", "-x", "dunst"], timeout=2)
    except Exception:
        pass

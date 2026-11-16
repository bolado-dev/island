import config as C
# -*- coding: utf-8 -*-
"""Constantes visuales de la isla.

Todos los tamanos van en PIXELES DE DISPOSITIVO, no en puntos. La
pantalla es 2880x1800 con Xft.dpi=168 y scale_factor de GTK = 1, asi que
si dejasemos que Pango interpretase puntos el resultado dependeria de un
ajuste global que puede cambiar. Con set_absolute_size() el render es
determinista: lo que se pide es lo que se dibuja.

Equivalencia con los cuerpos que usaba la polybar anterior:
    pt * 168/72 = px     (11pt -> 25.7px,  15pt -> 35px)
"""

# ---------------------------------------------------------------- color
# Colores de sistema de Apple en modo oscuro (valores literales de
# UIColor). El unico acento es el azul; el verde y el rojo solo aparecen
# cuando significan algo (VPN levantada, bateria critica).
ISLAND   = (0.00, 0.00, 0.00)        # negro puro y OPACO
FG       = (1.00, 1.00, 1.00)
DIM      = (0.557, 0.557, 0.576)     # systemGray
DIM2     = (0.282, 0.282, 0.290)     # systemGray5
ACCENT   = (0.039, 0.518, 1.000)     # systemBlue  #0A84FF
GREEN    = (0.188, 0.820, 0.345)     # systemGreen #30D158
RED      = (1.000, 0.271, 0.227)     # systemRed   #FF453A
ORANGE   = (1.000, 0.624, 0.039)     # systemOrange

# Superficies secundarias (chips, pistas, campos). Van deliberadamente
# oscuras: en un panel AMOLED cada pixel encendido consume, y el negro
# del cuerpo es negro de verdad (pixel apagado). Subirlas "para que se
# vean" echaria a perder justo eso. Centralizadas aqui en vez de
# repartidas por el codigo para poder ajustar el conjunto de una vez.
SURF_1   = (0.085, 0.085, 0.090)     # chip en reposo       ~rgb(22,22,23)
SURF_2   = (0.180, 0.180, 0.190)     # pista del deslizador ~rgb(46,46,48)
HOVER_A  = 0.12                      # alfa del realce de hover
FIELD_A  = 0.07                      # alfa del fondo de un campo

# --------------------------------------------------------------- metrica
H_COMPACT = 62        # alto en reposo (igual que el chip de polybar)
H_PILL    = 62        # expansion horizontal: misma altura, mas ancho
# Pildora alta: para controles de una sola fila (volumen, energia). No
# cabe en los 62 del reposo porque un chip con icono ya mide ~51 y se
# quedaria pegado a los bordes.
H_PILL_LG = 78
H_CARD    = 112
PANEL_PAD = 30        # aire vertical dentro de un panel

# Radio maximo de las esquinas. En la pildora compacta (62px) la mitad
# de la altura son 31, asi que no la toca y sigue siendo una capsula
# exacta. En un panel alto, en cambio, radio = altura/2 convertiria la
# forma en un ovalo y los extremos redondos se comerian casi 100px por
# lado: el deslizador de volumen se salia por los bordes.
RADIUS_MAX = 44

# Radio de las esquinas INFERIORES del notch. Mayor que el de un panel
# flotante porque aqui solo hay dos esquinas que redondear y la forma
# pide mas curva abajo para compensar el canto recto de arriba.
NOTCH_R   = 34       # expansion vertical: tarjeta de dos lineas
# Pegado al borde superior: el notch cuelga del borde, no flota.
TOP       = 0

# ---------------------------------------------------------------------
# Auto-ocultado.
#
# bspwm reserva el padding superior en TODO el ancho, asi que con el
# notch fijo quedaban inservibles los ~1000px vacios a cada lado. Si se
# repliega, se puede poner top_padding = 0 y las ventanas usan la
# pantalla entera; el notch baja al acercar el raton al borde.
#
# A False vuelve a estar siempre visible y se reserva ALTO_RESERVADO.
# ---------------------------------------------------------------------
AUTOHIDE  = True
PEEK      = 3         # sliver que asoma al estar replegado
# Franja sensible del borde superior. Puede ser muy estrecha sin coste:
# para desplegarlo a proposito se lleva el raton al borde y el puntero
# se queda clavado en y=0, asi que con 2px se acierta siempre. Cuanto
# mas estrecha, menos se dispara al pasar por encima camino de otra
# cosa.
HOT       = 2
HIDE_MS   = 700       # espera antes de replegarse al salir el raton
# Al cambiar de escritorio el notch asoma solo y se queda este rato.
# Mas largo que HIDE_MS porque aqui hay algo QUE MIRAR: la pildora
# viajando tarda ~380 ms, y replegarse a los 700 no dejaria leer donde
# ha quedado.
REVEAL_MS = 1500
ALTO_RESERVADO = 62   # top_padding cuando AUTOHIDE esta a False

# Radio de los enlaces concavos con el borde de la pantalla. A 0 el
# encuentro es un angulo recto y el notch parece pegado encima en vez
# de tallado en el panel.
FILLET    = 16
# Paddings por tipo de forma, no uno solo para todo. Una pildora
# compacta y un panel con lista no piden el mismo aire: con un valor
# unico, o la pildora queda hinchada o el panel queda apretado.
PAD_PILL  = 20        # pildora compacta y expansiones horizontales
PAD_CARD  = 30        # tarjetas (notificacion, musica)
PAD_PANEL = 34        # paneles con controles
GAP_GROUP = 26        # separacion ENTRE grupos
GAP_ITEM  = 14        # separacion DENTRO de un grupo
GAP_ROW   = 20        # separacion vertical entre filas de un panel

# Ancho de la columna del indicador en las listas (el punto de "red
# conectada"). Fijarlo permite que el titulo del panel y los nombres
# queden alineados en la misma vertical.
COL_MARK  = 22

# Indicador de escritorios: una pista de huecos IGUALES con una
# pildora azul que se desliza entre ellos. Huecos iguales es lo que
# permite que la pildora viaje a velocidad constante y que las zonas
# pulsables no se muevan al cambiar de escritorio.
SEG_SLOT  = 15        # ancho de cada hueco
SEG_GAP   = 5         # separacion entre huecos
SEG_BAR   = 8         # ancho de la marca de un escritorio no activo
SEG_H     = 6         # grosor de ocupado
SEG_H_OFF = 4         # grosor de vacio

# Animar o no el salto de la pildora al cambiar de escritorio.
#
# A False la pildora ya esta colocada cuando el notch acaba de bajar.
# El cambio de escritorio lo decides tu y lo acabas de pulsar: no hay
# nada que anunciar, y ver la pildora cruzando por encima de los
# escritorios de en medio distrae mas de lo que informa. El despliegue
# del notch ya es aviso de sobra.
#
# A True vuelve a deslizarse con muelle (ver SP_WS_* mas abajo).
WS_ANIM   = False
SP_WS_RESP = 0.32     # periodo del muelle, si WS_ANIM esta a True
SP_WS_DAMP = 0.82

# En cambio, la pildora SI crece al llegar: aparece como un punto del
# tamano de los demas y se estira hasta su ancho. Es la confirmacion de
# que el cambio ha ocurrido, pero ocurre DONDE vas, no por el camino, asi
# que no arrastra la mirada por los escritorios de en medio.
#
# Amortiguacion casi critica: crece y para, sin rebotar. Con rebote el
# gesto se lee como un golpe; sin el, como que el punto se abre. Y el
# periodo es largo para que el estiramiento tenga fotogramas suficientes
# y no parezca un cambio de tamano seco.
#
# Ademas la pildora entra con un fundido: al cambiar de escritorio
# aparece de golpe en el hueco nuevo, y llegar en azul pleno era lo mas
# brusco de todo el gesto, mas que el rebote. No arranca transparente
# del todo (POP_ALFA_MIN) para que no parezca que parpadea.
WS_POP      = True
SP_POP_RESP = 0.42
SP_POP_DAMP = 0.95
POP_ALFA_MIN = 0.30

# Altura de ventana: tiene que caber el panel MAS ALTO, que ahora es el
# lanzador (campo de busqueda + cinco filas de 54px = ~426px), no la
# lista de wifi. Con 460 el lanzador salia cortado por abajo.
# La ventana sobrante es transparente y deja pasar
# los clics, asi que pasarse no tiene coste visual; el de dibujado se
# evita redibujando solo la zona de la isla (ver _damage en islandd).
WIN_H     = 620

# --------------------------------------------------------------- fuentes
# (familia, peso, px). El peso va aparte en vez de pegado al nombre
# ("Inter Display SemiBold") porque asi Pango escoge el corte dentro de
# la familia; con el peso en el nombre, si fontconfig no encuentra esa
# familia exacta cae a la de por defecto SIN avisar, y el fallo solo se
# nota comparando anchos de texto.
F_CLOCK   = ("Inter Display", "semibold", 35)
F_BODY    = ("Inter Display", "medium",   26)
F_SMALL   = ("Inter",         "medium",   22)
F_TITLE   = ("Inter Display", "semibold", 27)
F_SUB     = ("Inter",         "medium",   24)
F_ICON    = ("Iosevka Nerd Font", "normal", 28)
F_ICON_L  = ("Iosevka Nerd Font", "normal", 34)

# ---------------------------------------------------------------- glifos
# Solo del rango Font Awesome: es estable tanto en Nerd Fonts v2 (que es
# lo que hay instalado) como en v3. Los glifos del rango Material de v2
# se movieron en v3 y dejarian cuadros.
G_WIFI    = ""
G_WIFI_NO = ""
G_POWER   = ""
G_VOL     = ["", "", ""]
G_MUTE    = ""
G_BAT     = ["", "", "", "", ""]
G_BOLT    = ""
G_BELL    = ""
G_LOCK    = ""
G_MUSIC   = ""
G_SUN     = ""
G_MIC_OFF = ""
G_MIC     = "\uf130"
G_CHECK   = "\uf00c"


# Perfiles de energia. Iconos en vez de los nombres completos:
# cuatro chips de texto ocupaban 658px de ancho, mas que el propio
# notch en reposo. El chip activo (o el senalado) si muestra su
# nombre al lado, asi que no se pierde legibilidad.
# Nombre del SVG de Solar por perfil (ver ~/.config/island/icons).
G_PROF = {
    "auto":                "prof-auto",   # sincronizacion: sigue al cargador
    "performance":         "prof-perf",   # cohete
    "balance_performance": "prof-bal",    # balanza
    "balance_power":       "prof-save",   # hoja
}


# Acciones del menu de apagado, con los mismos glifos que usaba
# powermenu.sh para que el cambio de rofi al notch no altere el
# aspecto de las opciones.
G_SEARCH = "\uf002"
G_POWER_ACTS = [
    # (etiqueta, icono, comando). Los comandos viven en config.py para
    # que cambiarlos no obligue a tocar el tema.
    ("Bloquear",      "lock",    C.CMD_LOCK),
    ("Suspender",     "moon",    C.CMD_SUSPEND),
    ("Cerrar sesion", "logout",  C.CMD_LOGOUT),
    ("Reiniciar",     "restart", C.CMD_REBOOT),
    ("Apagar",        "power",   C.CMD_POWEROFF),
]


# Tipos de resultado del lanzador: glifo y etiqueta.
G_RES = {
    "app":  ("\uf009", "Aplicaci\u00f3n"),
    "win":  ("\uf2d2", "Ventana"),
    "calc": ("\uf1ec", "Resultado"),
    "cmd":  ("\uf120", "Ejecutar"),
}
F_HERO = ("Inter Display", "semibold", 32)


# ---------------------------------------------------------------------
# Conjunto de iconos en uso.
#
# A False se usan los glifos de Nerd Font (lo de siempre). A True, los
# SVG de Solar de ~/.config/island/icons. La tabla de abajo traduce el
# nombre interno al glifo, asi que el interruptor cambia TODO el
# escritorio sin tocar ni una sola llamada.
# ---------------------------------------------------------------------
USAR_SOLAR = False

ICON_GLYPH = {
    "vol-mute": G_MUTE, "vol-low": G_VOL[0], "vol-mid": G_VOL[1],
    "vol-high": G_VOL[2],
    "wifi": G_WIFI, "wifi-off": G_WIFI_NO,
    "bat-0": G_BAT[0], "bat-1": G_BAT[1], "bat-2": G_BAT[2],
    "bat-3": G_BAT[3], "bat-4": G_BAT[4], "bolt": G_BOLT,
    "power": G_POWER, "lock": G_LOCK, "bell": G_BELL, "bell-off": "\uf1f6",
    "music": G_MUSIC, "search": G_SEARCH, "sun": G_SUN,
    "mic": G_MIC, "mic-off": G_MIC_OFF, "check": G_CHECK,
    "prev": "\uf053", "next": "\uf054",
    "prof-auto": "\uf021", "prof-perf": "\uf135",
    "prof-bal": "\uf24e", "prof-save": "\uf06c",
    "calc": "\uf1ec", "moon": "\uf186", "logout": "\uf08b",
    "restart": "\uf021", "app": "\uf009", "cmd": "\uf120",
    "window": "\uf2d2",
    "media-prev": "\uf048", "media-play": "\uf04b",
    "media-pause": "\uf04c", "media-next": "\uf051",
    "monocle": "\uf2d0", "balance": "\uf07e", "rotate": "\uf01e",
    "gap-plus": "\uf065", "gap-minus": "\uf066",
}


# ---------------------------------------------------------------------
# Dictado
#
# La onda son barras de la senal REAL del micro, no una animacion
# decorativa: si no entra audio se queda plana, y eso es justo lo que
# hay que ver antes de hablar treinta segundos para nada.
# ---------------------------------------------------------------------
DICT_BARS    = 18     # barras visibles de la onda
DICT_BAR_W   = 5
DICT_BAR_GAP = 4
DICT_BAR_H   = 34     # alto maximo de una barra
DICT_BAR_MIN = 4      # alto en silencio: la onda no desaparece del todo
DICT_COLOR   = RED    # grabando. El rojo es la convencion universal
DICT_WORK    = ACCENT # transcribiendo
DICT_OK      = GREEN  # texto listo
# Texto transcrito que cabe en la tarjeta antes de recortar.
DICT_MAXTXT  = 78

# -*- coding: utf-8 -*-
"""Ajustes propios de cada maquina.

Separados de theme.py a proposito: ahi va el aspecto, aqui los comandos
y rutas que cambian de un equipo a otro. Es el unico fichero que
deberias necesitar tocar para que la isla funcione en tu sistema.
"""
import os

# ----------------------------------------------------------- comandos

# Bloqueo de pantalla. slock, betterlockscreen, swaylock... lo que uses.
CMD_LOCK      = "i3lock"

# Emulador de terminal, para los .desktop marcados con Terminal=true.
# Debe aceptar el ejecutable a continuacion (lo tipico es '-e').
CMD_TERMINAL  = "kitty -e"

# Mezclador de audio que abre el boton del panel de volumen.
CMD_MIXER     = "pavucontrol"

# Acciones de sesion del menu de apagado.
CMD_SUSPEND   = "systemctl suspend"
CMD_LOGOUT    = "bspc quit"
CMD_REBOOT    = "systemctl reboot"
CMD_POWEROFF  = "systemctl poweroff"

# ---------------------------------------------------- perfiles de energia

# Script que fija el Energy Performance Preference de intel_pstate. Se
# invoca con sudo -n, asi que necesita una regla en /etc/sudoers.d que
# lo permita sin contrasena (ver el README).
#
# Si no existe, el panel de energia oculta los perfiles y muestra solo
# el estado de la bateria: no hay nada que romper.
EPP_SET  = "/usr/local/bin/power-epp-set.sh"
EPP_CONF = "/etc/power-epp.conf"

# ---------------------------------------------------------------- VPN

# Fichero opcional con una etiqueta para la VPN: si existe y tiene
# contenido, se muestra junto a la IP de tun0 en la live activity.
# Formato: "<ip> <nombre>" o solo "<nombre>".
#
# Nacio para apuntar la maquina objetivo en Hack The Box, pero sirve
# para cualquier cosa que quieras ver mientras el tunel este arriba.
VPN_LABEL_FILE = os.path.expanduser("~/.config/island/vpn-label")

# ------------------------------------------------------------- red

# Interfaces que se consultan. Cambia 'wlan0' si la tuya se llama de
# otra forma (ip -br link).
IFACE_WIFI = "wlan0"
IFACE_VPN  = "tun0"


# --------------------------------------------------------------- dictado
# Dictado por voz (dictado.py). El binario y el modelo viven fuera del
# repo a proposito: son 181 MB y un ejecutable compilado para ESTA
# maquina, no configuracion que se pueda versionar.
#
#   git clone https://github.com/ggml-org/whisper.cpp ~/.local/share/whisper.cpp
#   cd ~/.local/share/whisper.cpp && cmake -B build -DCMAKE_BUILD_TYPE=Release
#   cmake --build build -j
#   ./models/download-ggml-model.sh small-q5_1
#
# El modelo se eligio midiendo en esta maquina, sin GPU: `small-q5_1`
# transcribe 11 s de audio en 2,9 s (unas 4 veces mas rapido que hablar)
# y `large-v3-turbo-q5_0` tarda 18,7 s, o sea mas que la propia frase.
DICT_WHISPER = "~/.local/share/whisper.cpp/build/bin/whisper-cli"
DICT_MODEL   = "~/.local/share/whisper.cpp/models/ggml-small-q5_1.bin"
DICT_LANG    = "es"
# 10 de los 12 nucleos: dejar dos libres evita que la transcripcion
# atragante al propio escritorio mientras dibuja la onda.
DICT_THREADS = 10
# Tope de grabacion. Si algo se queda colgado, que no grabe toda la
# noche: son 120 s de audio y de disco por cada pulsacion olvidada.
DICT_MAX_S   = 120
# Tecla del push-to-talk, como la llama X (ver `xmodmap -pke`). El
# ayudante la vigila mientras graba y para en cuanto se suelta, pase lo
# que pase con los modificadores: el atajo de soltado de sxhkd solo casa
# si se suelta la tecla ANTES que super, y al levantar la mano suele ser
# al reves. Vacia = no vigilar, solo el atajo.
DICT_TECLA = "v"

# Pista que se le da a whisper antes de transcribir. No es una orden,
# es contexto: el modelo lo toma como "lo que se venia diciendo", asi
# que arrastra su estilo. Sirve sobre todo para que puntue y use
# mayusculas, que en dictado corto es donde mas falla.
#
# Deliberadamente GENERICO. Meter aqui jerga propia mejora esas
# palabras y empeora el resto: el modelo intenta encajarlas donde no
# tocan, y lo normal es dictar frases corrientes. Si algun dia hace
# falta un vocabulario propio, va en una linea aparte y se añade solo
# cuando se note el fallo.
DICT_PROMPT = ("Transcripcion en espanol de Espana, con puntuacion y "
               "mayusculas correctas.")

# Segundos que tiene que durar un trabajo de la IA para que el notch
# avise al terminar. 0 = avisar siempre, que es como esta.
#
# Nacio en 10 con el argumento de que una respuesta de tres segundos la
# ves tu solo y avisar de todas convierte el notch en ruido. El
# argumento era malo: si estas mirando la ventana, el aviso no sale
# igualmente (lo filtra el foco, no el reloj), asi que lo unico que
# hacia el minimo era tragarse justo los avisos de lo que acaba rapido
# mientras tu estas en otra cosa. Subirlo otra vez solo tiene sentido
# si alguna CLI resulta apagar el girador a mitad de trabajo.
TRABAJO_MINIMO = 0.0

# Historial del portapapeles, para el lanzador. CLIP_CADA es cada
# cuantos segundos se mira (0 lo apaga); CLIP_MAX, cuantas cosas se
# recuerdan. Nada de esto toca el disco: por el portapapeles pasan
# contraseñas, y lo que no se guarda no se filtra.
CLIP_MAX  = 20
CLIP_CADA = 3

# ---------------------------------------------------------------- emoji
# Selector de emoji (super + .). Los datos NO se versionan: los trae el
# sistema. emoji-test.txt es la lista oficial del consorcio Unicode, con
# el orden y los grupos ya decididos por ellos, y viene en el paquete
# `unicode-data`. Mantener aqui una copia propia seria quedarse atras en
# cada version de Unicode sin ganar nada.
#
# Si el fichero no esta, el selector lo dice y no se abre.
EMOJI_DATA = "/usr/share/unicode/emoji/emoji-test.txt"

# Nombres y palabras clave en espanol, para poder buscar "fuego" y no
# "fire". Los genera fetch-icons.sh desde CLDR; si falta el fichero se
# busca en ingles, que es lo que trae emoji-test.txt.
EMOJI_ES = os.path.expanduser("~/.config/island/emoji-es.json")

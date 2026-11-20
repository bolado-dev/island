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
# En minusculas y con el nombre que le da X: "space", no "Space". Con
# la mayuscula XStringToKeysym devuelve 0, no se vigila nada y el
# dictado se queda grabando hasta el tope.
DICT_TECLA = "space"

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

# ------------------------------------------------------------ capturas
# Capturas de pantalla (captura.py). Donde van los ficheros y como se
# llaman. El formato es el de strftime; con segundos a proposito, que
# dos capturas seguidas dentro del mismo minuto no se pisen.
CAPTURA_DIR = os.path.expanduser("~/ScreenShots")
CAPTURA_FMT = "%Y-%m-%d_%H-%M-%S.png"

# Con que se abre una captura al pulsar "Abrir", y con que su carpeta.
# xdg-open respeta lo que tengas asociado; si prefieres un visor
# concreto, ponlo aqui.
CMD_VISOR    = "xdg-open"
CMD_CARPETA  = "xdg-open"

# Segundos que se espera, tras pedirle a la isla que se repliegue, antes
# de disparar la captura. Si no, una tarjeta todavia a la vista (la de
# la captura ANTERIOR, que es el caso frecuente) sale en la foto. Medido
# en esta maquina: el repliegue tarda 0,35 s.
CAPTURA_ESPERA = 0.40

# Quien dibuja la seleccion de region: "isla" o "scrot".
#
# "isla" es el selector propio (seleccion.py): congela el escritorio,
# lo atenua y deja elegir con el mismo lenguaje visual que el notch,
# escuadras azules en las esquinas y el tamano en una pastilla.
#
# "scrot" es el respaldo para una maquina sin GTK a mano. Funciona, pero
# no pinta NADA encima: solo cambia el cursor y traza una linea fina al
# arrastrar, asi que al pulsar el atajo parece que no ha pasado nada.
CAPTURA_SELECTOR = "isla"

# ------------------------------------------------- atajos de los paneles
# La tecla de cada panel, para que repetir su atajo lo CIERRE.
#
# Tiene que coincidir con tu sxhkdrc, y la isla no puede preguntarselo:
# mientras un panel esta abierto tiene agarrado el teclado, asi que
# sxhkd no llega a ver la combinacion y no puede volver a dispararla.
# La segunda pulsacion le llega a la isla como una tecla normal --por
# eso "super + d" con el lanzador abierto escribia una "d" en la
# busqueda- y es ella quien decide cerrarse.
PANEL_TECLA = {
    "launcher":     "d",
    "emoji":        "period",
    "portapapeles": "v",
}

# ----------------------------------------------- reloj: crono y pomodoro
# El panel del reloj (clic en la hora) lleva cronometro, temporizador y
# pomodoro. Aqui van las duraciones y el aviso, que es lo unico que
# cambia de una persona a otra.

# Atajos de minutos del temporizador, en segundos. Cinco: los que caben
# en el ancho del calendario sin apretar.
TEMP_ATAJOS = (60, 300, 600, 1500, 3600)

# Pomodoro clasico: 25 de trabajo, 5 de descanso y uno largo de 15 cada
# cuatro. Son los numeros de Cirillo, que es lo que espera cualquiera
# que haya oido la palabra.
POMO_TRABAJO = 25 * 60
POMO_CORTO   = 5 * 60
POMO_LARGO   = 15 * 60
POMO_CADA    = 4

# Aviso al acabar una cuenta atras. Un temporizador que solo avisa en
# pantalla no sirve para nada: lo pones justo para irte a hacer otra
# cosa.
#
# El reproductor se invoca con el fichero como unico argumento. Vacio
# ("") deja el aviso en silencio, y si el fichero no existe tampoco se
# intenta: no hay nada que romper.
SONIDO       = "pw-play"
SONIDO_FIN   = "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga"
SONIDO_FASE  = "/usr/share/sounds/freedesktop/stereo/complete.oga"

# ------------------------------------------------- notificaciones
# Que la isla sea el servidor de notificaciones del escritorio: toma
# org.freedesktop.Notifications en D-Bus y recibe los avisos de primera
# mano, en vez de que se los pase otro demonio.
#
# Es lo unico que permite enseñar el AVATAR de quien escribe: Electron
# (Discord, Slack, Signal) manda la imagen como pixeles dentro de la
# propia llamada, y un relevo como dunst la guarda para dibujarla sin
# pasarsela a nadie; y Chrome manda la ruta de un temporal que borra
# antes de que al relevo le de tiempo a leerlo.
#
# A True se aparta a dunst al arrancar (pkill). Para volver atras:
# pon esto a False y descomenta 'dunst &' en tu bspwmrc.
SERVIDOR_NOTIS = True

# Aplicaciones cuyas notificaciones se tiran: la isla ya enseña eso
# mismo de otra forma. Son los OSD de volumen y brillo, que llaman a
# island-send y dejan notify-send de respaldo por si la isla no esta.
NOTIS_IGNORA = ("volumen", "brillo", "volume", "brightness")

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

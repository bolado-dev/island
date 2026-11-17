#!/bin/sh
# Baja de Solar los iconos que usa la isla y los deja en ./icons.
#
# No se versionan dentro del repo para no redistribuir un juego de
# iconos ajeno. Solo hacen falta si pones USAR_SOLAR = True en theme.py;
# por defecto se usan glifos de Nerd Fonts y este script sobra.
#
# Solar: https://www.figma.com/community/file/1166831539721848736
set -eu
DIR="$(cd "$(dirname "$0")" && pwd)"
URL="https://cdn.jsdelivr.net/npm/@iconify-json/solar/icons.json"

echo "Bajando el conjunto de Solar (~12 MB)..."
python3 - "$DIR" "$URL" <<'PY'
import json, os, sys, urllib.request
dest = os.path.join(sys.argv[1], "icons")
os.makedirs(dest, exist_ok=True)
j = json.loads(urllib.request.urlopen(sys.argv[2], timeout=120).read())

# alias interno -> nombre en Solar. Estilo "bold" en todos: a 26-56 px
# los trazos de "linear" se emborronan.
QUIERO = {
    "wifi": "wi-fi-bold", "wifi-off": "wi-fi-cross-bold",
    "vol-mute": "volume-cross-bold", "vol-low": "volume-small-bold",
    "vol-mid": "volume-bold", "vol-high": "volume-loud-bold",
    "bat-0": "battery-low-bold", "bat-1": "battery-low-bold",
    "bat-2": "battery-half-bold", "bat-3": "battery-full-bold",
    "bat-4": "battery-full-bold", "bolt": "battery-charge-bold",
    "power": "power-bold", "lock": "lock-bold", "bell": "bell-bold",
    "bell-off": "bell-off-bold", "music": "music-note-2-bold",
    "search": "magnifer-bold-duotone", "sun": "sun-bold",
    "prev": "alt-arrow-left-bold", "next": "alt-arrow-right-bold",
    "prof-auto": "refresh-bold", "prof-perf": "rocket-bold",
    "prof-bal": "speedometer-middle-bold", "prof-save": "leaf-bold",
    "calc": "calculator-bold", "moon": "moon-bold",
    "logout": "logout-bold", "restart": "restart-bold",
    "app": "widget-2-bold", "cmd": "command-bold",
    "window": "window-frame-bold",
    "media-prev": "skip-previous-bold", "media-play": "play-bold",
    "media-pause": "pause-bold", "media-next": "skip-next-bold",
    "monocle": "maximize-square-bold", "balance": "transfer-horizontal-bold",
    "rotate": "restart-bold", "gap-plus": "maximize-bold",
    "gap-minus": "minimize-bold",
}
W, H = j.get("width", 24), j.get("height", 24)
hechos = faltan = 0
for alias, nombre in QUIERO.items():
    ic = j["icons"].get(nombre)
    if ic is None:
        faltan += 1
        continue
    w, h = ic.get("width", W), ic.get("height", H)
    # fill="currentColor" se conserva: el color NO va en el SVG, se
    # aplica al pintar con una mascara de cairo.
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" '
           'width="%d" height="%d">%s</svg>') % (w, h, w, h, ic["body"])
    open(os.path.join(dest, alias + ".svg"), "w").write(svg)
    hechos += 1
print("  %d iconos en %s%s" % (hechos, dest,
      ("  (%d sin encontrar)" % faltan) if faltan else ""))
PY
echo "Listo. Pon USAR_SOLAR = True en theme.py para usarlos."

# --- logos de las IA, para el indicador de dictado -------------------
#
# Estos SI hacen falta siempre, no solo con USAR_SOLAR: el notch los usa
# para decir a que IA va a ir lo que dictes. Tampoco se versionan, y
# aqui el motivo pesa mas que con Solar: son marcas registradas de sus
# dueños. Si falta el fichero no se rompe nada, el notch enseña el
# nombre en texto.
#
# simple-icons: https://simpleicons.org (los trazos, CC0)
echo "Bajando los logos de las IA..."
python3 - "$DIR" <<'PY2'
import os, re, sys, urllib.request
dest = os.path.join(sys.argv[1], "icons")
os.makedirs(dest, exist_ok=True)
BASE = "https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/%s.svg"
# alias de sources.IAS -> nombre del icono en simple-icons
QUIERO = {"ia-claude": "claude", "ia-gemini": "googlegemini"}
for alias, nombre in QUIERO.items():
    try:
        svg = urllib.request.urlopen(BASE % nombre, timeout=60).read().decode()
    except Exception as e:
        print("  %s: no se pudo bajar (%s)" % (alias, e))
        continue
    # El <title> sobra y el relleno tambien: se pinta como mascara, asi
    # que el color lo pone el tema y no el fichero.
    svg = re.sub(r"<title>.*?</title>", "", svg, flags=re.S)
    open(os.path.join(dest, alias + ".svg"), "w").write(svg)
    print("  %s.svg" % alias)
PY2

# --- nombres de emoji en castellano, para el selector ----------------
#
# Sin esto el selector busca en ingles, que es lo que trae el fichero
# del sistema: escribes "fire" y sale el fuego, pero "fuego" no
# encuentra nada. Con esto van los dos.
#
# Tampoco se versiona. Aqui el motivo no es la licencia (CLDR es
# Unicode-3.0, y permite redistribuir) sino que es un dato derivado de
# algo que se actualiza solo: regenerarlo es una orden, y tenerlo
# dentro del repo significa tenerlo desactualizado.
#
# Hacen falta los DOS ficheros. annotations tiene los emoji de un
# codepoint y annotationsDerived los compuestos (la familia de cuatro,
# las banderas, los oficios): con el primero solo se traduce el 83%.
#
# CLDR: https://github.com/unicode-org/cldr (Unicode-3.0)
echo "Bajando los nombres de emoji en castellano..."
python3 - "$DIR" <<'PY3'
import json, os, sys, urllib.request, xml.etree.ElementTree as ET
BASE = ("https://raw.githubusercontent.com/unicode-org/cldr/main/common/"
        "%s/es.xml")
nombres, claves = {}, {}
for cual in ("annotations", "annotationsDerived"):
    try:
        datos = urllib.request.urlopen(BASE % cual, timeout=120).read()
    except Exception as e:
        print("  %s: no se pudo bajar (%s)" % (cual, e))
        continue
    for a in ET.fromstring(datos).iter("annotation"):
        cp, txt = a.get("cp"), (a.text or "").strip()
        if a.get("type") == "tts":
            nombres[cp] = txt
        else:
            claves[cp] = txt

if not nombres:
    print("  sin datos: el selector buscara en ingles")
    sys.exit(0)

# Un solo objeto emoji -> [nombre, claves]. Las claves se guardan tal
# cual vienen, separadas por "|": solo se usan para buscar dentro, asi
# que partirlas en una lista seria un fichero mas grande sin ninguna
# ventaja.
salida = {cp: [n, claves.get(cp, "")] for cp, n in nombres.items()}
dest = os.path.join(sys.argv[1], "emoji-es.json")
with open(dest, "w", encoding="utf-8") as f:
    json.dump(salida, f, ensure_ascii=False, separators=(",", ":"))
print("  %d nombres en %s (%d KB)"
      % (len(salida), dest, os.path.getsize(dest) // 1024))
PY3

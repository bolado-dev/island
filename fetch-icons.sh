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

#!/bin/sh
# Hook de dunst -> isla.
# dunst invoca con: $1 appname  $2 summary  $3 body  $4 icon  $5 urgency
APP="$1"; SUM="$2"; BODY="$3"; ICON="$4"; URG="$5"

case "$APP" in
    volumen|brillo|volume|brightness) exit 0 ;;
esac

# Los argumentos del hook no traen ni la URL de origen ni la etiqueta de
# agrupacion, y son las unicas pistas para saber de que sitio web viene
# una notificacion de Chrome. Se sacan del historial, que en este punto
# ya contiene la notificacion recien llegada (comprobado).
EXTRA=$(dunstctl history 2>/dev/null \
        | jq -r '.data[0][0] | ((.urls.data // "") + " " + (.stack_tag.data // ""))' \
          2>/dev/null)

exec "$HOME/.config/island/island-send" notify \
     --app "${APP:-$SUM}" --title "$SUM" --body "${BODY:-$SUM}" \
     --urgency "${URG:-normal}" --icon "$ICON" --hint "$EXTRA"

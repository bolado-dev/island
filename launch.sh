#!/bin/sh
# Lanza la isla y la mantiene viva.
#
# El reinicio automatico es la contrapartida de haber sustituido a
# polybar: si el widget se cae, el escritorio se queda SIN barra. El
# limite de reintentos evita que un fallo permanente (una dependencia
# que desaparece) se convierta en un bucle cerrado comiendo CPU.

DIR="$HOME/.config/island"
LOG="${XDG_RUNTIME_DIR:-/tmp}/island.log"

# El hueco superior lo fija la propia isla al arrancar, segun
# theme.AUTOHIDE: con auto-ocultado va a 0 y las ventanas usan la
# pantalla entera. Ponerlo aqui tambien dejaria dos fuentes de
# verdad que se contradicen.

# Mata cualquier instancia previa sin tocar este propio script.
for pid in $(pgrep -f "python3 .*islandd\.py"); do
    [ "$pid" != "$$" ] && kill "$pid" 2>/dev/null
done
sleep 0.3

fails=0
while [ "$fails" -lt 10 ]; do
    start=$(date +%s)
    python3 "$DIR/islandd.py" >>"$LOG" 2>&1
    end=$(date +%s)
    # Si aguanto mas de 30 s, no es un fallo de arranque: se reinicia
    # con el contador a cero.
    if [ $((end - start)) -gt 30 ]; then
        fails=0
    else
        fails=$((fails + 1))
    fi
    sleep 2
done

echo "isla: 10 fallos seguidos de arranque, me rindo. Revisa $LOG" >&2

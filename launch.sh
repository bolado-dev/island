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

# Una sola isla por sesion, y el candado es lo que lo garantiza.
#
# Antes solo se mataba "cualquier instancia previa" del PROCESO, no del
# supervisor, y eso tiene un agujero: arrancando launch.sh dos veces, el
# segundo mata al hijo del primero, el primero lo resucita a los dos
# segundos y te quedas con DOS islas para siempre, una dibujando encima
# de la otra. Pasa de verdad --aparecieron dos, con 213 y 317 s de CPU
# cada una- y encima solo una de ellas se queda con el nombre de
# notificaciones de D-Bus: la otra se lo pierde y sigue pintando.
#
# El descriptor 9 queda abierto mientras viva este script, asi que el
# candado lo sostiene el supervisor. El hijo no lo hereda (9>&- mas
# abajo) o al morir el supervisor seguiria cerrado desde el hijo.
LOCK="${XDG_RUNTIME_DIR:-/tmp}/island.lock"
exec 9>"$LOCK"
if ! flock -n 9; then
    echo "isla: ya hay otra corriendo (candado $LOCK), no arranco otra" >&2
    exit 0
fi

# Y aun asi se mata lo que haya quedado suelto: un islandd sin
# supervisor (porque lo mataron a el y no al hijo) no lo ve el candado.
# El patron va ANCLADO a proposito. Sin ^...$ casa con cualquier linea
# de ordenes que mencione islandd.py --un grep, un editor, el shell de
# quien este trasteando- y se la lleva por delante. Visto y sufrido.
for pid in $(pgrep -f "^python3 $DIR/islandd\.py$"); do
    [ "$pid" != "$$" ] && kill "$pid" 2>/dev/null
done
sleep 0.3

fails=0
while [ "$fails" -lt 10 ]; do
    start=$(date +%s)
    python3 "$DIR/islandd.py" 9>&- >>"$LOG" 2>&1
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

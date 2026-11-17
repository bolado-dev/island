#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dictado por voz para la isla: hablas y el texto aparece donde estabas.

    dictado.py toggle     # lo que se ata a una tecla en sxhkd
    dictado.py start|stop|cancel
    dictado.py demo ["frase"]   # sin microfono, para ver como queda

Tres decisiones que explican la forma de esto:

**La ventana de destino se mira al EMPEZAR, no al terminar.** Mientras
hablas puedes cambiar de ventana sin darte cuenta (una notificacion que
roba el foco, un gesto del raton). Si el texto fuera a parar a donde
este el foco al soltar la tecla, acabaria escrito en cualquier sitio, y
es texto que ya no esta en ninguna otra parte.

**El nivel del microfono se manda a la isla, no se dibuja aqui.** La
onda que se ve es la señal real: con una animacion decorativa, un micro
silenciado se veria igual que una grabacion buena y te enterarias al
leer la transcripcion vacia.

**Nada de dependencias nuevas.** Graba `pw-record` (PipeWire, que ya
esta), transcribe `whisper-cli` (compilado aparte, ver config.py) y el
nivel sale de `array` de la biblioteca estandar. La isla presume de no
costar nada en reposo; el dictado no la puede convertir en otra cosa.
"""
import os
import sys
import json
import math
import time
import array
import ctypes
import signal
import subprocess
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
import sources

RUN = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "island-dictado")
PIDF = os.path.join(RUN, "pid")
WAV = os.path.join(RUN, "audio.wav")
FIFO = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "island.fifo")

# Con ISLAND_DEBUG se escribe una linea por fase con el tiempo que
# costo. Es la unica forma de saber donde se va el retardo entre soltar
# la tecla y ver el texto: el que graba es un proceso suelto sin
# terminal a la que quejarse.
TRAZA = os.path.join(RUN, "traza.log")


def traza(que, t0):
    if not os.environ.get("ISLAND_DEBUG"):
        return
    try:
        with open(TRAZA, "a") as fh:
            fh.write("%-16s %6.0f ms\n" % (que, (time.monotonic() - t0) * 1000))
    except OSError:
        pass


NOMBRE_FLUJO = "island-dictado"
RATE = 16000                 # lo que quiere whisper; remuestrear seria peor
CHUNK = 0.08                 # cada cuanto se manda un nivel a la isla
SILENCIO_DB = -50.0          # suelo de la onda
TECHO_DB = -10.0             # a partir de aqui la barra esta llena


# --------------------------------------------------------------- isla

def enviar(**campos):
    """Escribe el evento en el FIFO de la isla, sin pasar por
    `island-send`: durante la grabacion esto se llama doce veces por
    segundo, y lanzar un proceso de Python por cada nivel costaria mas
    que grabar."""
    if not os.path.exists(FIFO):
        return
    campos.setdefault("kind", "dictado")
    try:
        fd = os.open(FIFO, os.O_WRONLY | os.O_NONBLOCK)
        os.write(fd, (json.dumps(campos) + "\n").encode())
        os.close(fd)
    except OSError:
        pass                 # la isla no esta escuchando: no es motivo para fallar


# ------------------------------------------------------------ teclado

_X = {"dpy": None, "lib": None}


def _x11():
    """Conexion minima con el servidor X, por ctypes.

    Sin python-xlib y sin lanzar `xinput` doce veces por segundo: es la
    misma idea que leer la IP por ioctl en vez de llamar a `ip`.
    """
    if _X["dpy"] is None:
        try:
            lib = ctypes.CDLL("libX11.so.6")
            lib.XOpenDisplay.restype = ctypes.c_void_p
            dpy = lib.XOpenDisplay(None)
            _X["lib"], _X["dpy"] = lib, (dpy or False)
        except OSError:
            _X["dpy"] = False
    return _X["lib"], _X["dpy"]


def tecla_pulsada(nombre):
    """True si esa tecla esta fisicamente pulsada ahora mismo.

    Existe porque sxhkd no puede contestar a esto. El atajo de SOLTADO
    (`@super + v`) solo casa si la v se suelta ANTES que super, y al
    levantar la mano del teclado lo normal es lo contrario: entonces no
    lo ve nadie y el dictado se queda grabando para siempre. Atar
    tambien el soltado de super no vale: agarrar un modificador rompe la
    propia combinacion, comprobado, y dejaba de funcionar hasta el caso
    que antes iba bien.

    Preguntarle al servidor X por la tecla es la verdad, y no depende
    del orden en que se suelte nada.
    """
    lib, dpy = _x11()
    if not dpy:
        return False
    sym = lib.XStringToKeysym(nombre.encode())
    if not sym:
        return False
    kc = lib.XKeysymToKeycode(ctypes.c_void_p(dpy), sym)
    if not kc:
        return False
    mapa = (ctypes.c_char * 32)()
    lib.XQueryKeymap(ctypes.c_void_p(dpy), mapa)
    return bool(mapa[kc >> 3][0] & (1 << (kc & 7)))


# ------------------------------------------------------------- ventana

def foco():
    """La ventana enfocada. La deteccion vive en sources, que es de
    donde la lee tambien la isla: dos copias de "esto es Claude" se
    separan en cuanto una de las dos aprenda a reconocer otra IA."""
    return sources.ventana_enfocada()


# -------------------------------------------------------------- nivel

def nivel(pcm):
    """RMS de un trozo de PCM a 0..1, en escala logaritmica.

    Lineal no sirve: la voz normal se queda en el 5% del fondo de escala
    y la onda no se movia. En dB, el silencio de una habitacion y una
    frase dicha a medio metro se separan bien.
    """
    if not pcm:
        return 0.0
    muestras = array.array("h")
    muestras.frombytes(pcm[:len(pcm) // 2 * 2])
    if not muestras:
        return 0.0
    suma = 0
    for m in muestras:
        suma += m * m
    rms = math.sqrt(suma / float(len(muestras)))
    if rms < 1:
        return 0.0
    db = 20.0 * math.log10(rms / 32768.0)
    return max(0.0, min(1.0, (db - SILENCIO_DB) / (TECHO_DB - SILENCIO_DB)))


# ----------------------------------------------------------- grabacion

def grabar(destino):
    """Graba hasta que llegue SIGUSR1, mandando el nivel a la isla.

    El nivel sale de releer la cola del propio fichero que escribe
    `pw-record`, no de un segundo flujo de audio: abrir el microfono dos
    veces es pedirle al servidor de sonido que lo mezcle para nada.
    """
    # El flujo se presenta con nombre propio para que el aviso de
    # "micro abierto" de la isla sepa que este es suyo y no se avise a
    # si mismo cada vez que dictas.
    entorno = dict(os.environ,
                   PIPEWIRE_PROPS='{ node.name = "%s" }' % NOMBRE_FLUJO)
    rec = subprocess.Popen(
        ["pw-record", "--rate", str(RATE), "--channels", "1",
         "--format", "s16", WAV], env=entorno,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Un Event y no una bandera: al soltar la tecla, la espera de abajo
    # termina en el acto en vez de aguantar hasta el final del trozo en
    # curso. Son 80 ms, pero son los 80 ms que van justo despues de
    # dejar de hablar, que es donde mas se notan.
    parar = threading.Event()
    signal.signal(signal.SIGUSR1, lambda *_: parar.set())
    signal.signal(signal.SIGTERM, lambda *_: parar.set())

    # Push-to-talk solo si la tecla esta pulsada AHORA. Si se llego aqui
    # por el interruptor (super+shift+v) esta suelta, y vigilarla
    # pararia la grabacion en el primer parpadeo.
    vigila = bool(C.DICT_TECLA) and tecla_pulsada(C.DICT_TECLA)

    enviar(state="oyendo", value=0.0, app=destino["app"],
           ia=destino.get("ia", ""))

    pos = 44                                   # saltar la cabecera del wav
    t0 = time.monotonic()
    while not parar.is_set():
        if parar.wait(CHUNK):
            break
        if vigila and not tecla_pulsada(C.DICT_TECLA):
            break
        if rec.poll() is not None:             # pw-record se murio solo
            break
        if time.monotonic() - t0 > C.DICT_MAX_S:
            break
        try:
            with open(WAV, "rb") as fh:
                fh.seek(pos)
                trozo = fh.read()
                pos += len(trozo)
        except OSError:
            trozo = b""
        enviar(state="oyendo", value=nivel(trozo), app=destino["app"],
               ia=destino.get("ia", ""))

    t_suelta = time.monotonic()
    # SIGINT y no kill: pw-record cierra la cabecera del wav al salir, y
    # sin cabecera el fichero no es un wav que whisper pueda abrir.
    if rec.poll() is None:
        rec.send_signal(signal.SIGINT)
        try:
            rec.wait(timeout=3)
        except subprocess.TimeoutExpired:
            rec.kill()
    traza("cerrar micro", t_suelta)
    return time.monotonic() - t0


# ------------------------------------------------------- transcripcion

BASURA = ("[BLANK_AUDIO]", "(música)", "(music)", "[Música]", "[MÚSICA]",
          "(sonido)", "[ Silencio ]", "(silencio)")


def ventana(dur):
    """Tokens de contexto de audio para `dur` segundos de grabacion.

    Whisper codifica SIEMPRE una ventana de 30 s: hables dos segundos o
    veinte, el codificador cuesta lo mismo. Recortarla a lo que de
    verdad hay es la optimizacion mas grande que admite esto, y medida
    en esta maquina con el modelo small:

        2,5 s de audio, ventana entera   2488 ms
        2,5 s de audio, ventana ajustada  918 ms   (mismo texto, coma a coma)
        11 s de audio,  ventana entera   4934 ms
        11 s de audio,  ventana ajustada 3075 ms   (mismo texto)

    50 tokens por segundo es la relacion real (30 s -> 1500). El 35% y
    los 64 de propina no son por gusto: quedarse CORTO recorta el audio
    y se pierden palabras del final, que es un fallo mucho peor que
    tardar un poco mas.
    """
    return max(256, min(1500, int(dur * 50 * 1.35) + 64))


def transcribir(dur=0.0):
    whisper = os.path.expanduser(C.DICT_WHISPER)
    modelo = os.path.expanduser(C.DICT_MODEL)
    if not (os.path.exists(whisper) and os.path.exists(modelo)):
        return "", "Falta whisper o el modelo"
    t0 = time.monotonic()
    try:
        r = subprocess.run(
            [whisper, "-m", modelo, "-f", WAV, "-l", C.DICT_LANG,
             "-t", str(C.DICT_THREADS), "-nt", "-np",
             "-ac", str(ventana(dur)),
             # La pista de estilo y, con ella, quitar los tokens que no
             # son habla: son los que producen los "(música)" y
             # "[BLANK_AUDIO]" que luego hay que limpiar a mano.
             "--prompt", C.DICT_PROMPT, "-sns"],
            capture_output=True, text=True, timeout=180)
    except Exception as e:
        return "", str(e)[:60]
    traza("whisper", t0)
    texto = " ".join(r.stdout.split())
    for b in BASURA:
        texto = texto.replace(b, " ")
    return " ".join(texto.split()), ""


# ---------------------------------------------------------- escritura

def escribir(texto, destino):
    """Deja el texto donde estabas, por el portapapeles.

    El pegado vive en sources.pegar, no aqui: el selector de emoji
    necesita exactamente lo mismo (dejar algo en la ventana que tenias
    delante) y dos copias de esto se habrian separado en cuanto una de
    las dos aprendiese algo, igual que iba a pasar con la deteccion de
    las IA. Lo que se queda aqui es la traza, que solo le interesa al
    dictado.
    """
    t0 = time.monotonic()
    como = sources.pegar(texto, destino)
    if como == "escrito":
        traza("pegar", t0)
    return como


# ---------------------------------------------------------------- demo

# Frase por defecto del demo. Larga como para que la onda tenga ritmo y
# corta como para caber en una linea de la tarjeta.
DEMO_FRASE = "A\u00f1ade un bot\u00f3n para exportar el informe a CSV"


def _silabas(palabra):
    """Cuantos golpes de voz tiene una palabra, a ojo pero no al azar.

    Grupos de vocales seguidas cuentan como uno (los diptongos se dicen
    de una vez). No es silabeo correcto —no mira hiatos ni acentos— y no
    hace falta que lo sea: solo decide cuantas rafagas tiene esa palabra
    en la onda.
    """
    VOCALES = "aeiou\u00e1\u00e9\u00ed\u00f3\u00fa\u00fc"
    n, dentro = 0, False
    for c in palabra.lower():
        v = c in VOCALES
        if v and not dentro:
            n += 1
        dentro = v
    return max(1, n)


def _pcm_demo(frase, semilla=7):
    """PCM sintetico con la envolvente de alguien diciendo esa frase.

    La gracia es que NO dibuja la onda: fabrica audio y lo deja pasar por
    el mismo `nivel()` que procesa el microfono. Asi el demo recorre el
    mismo camino que una grabacion de verdad y la onda no puede acabar
    pareciendose a algo que el micro nunca produciria.

    Una rafaga por silaba, huecos cortos entre silabas y largos entre
    palabras, y una pausa en cada coma. El ruido va con semilla fija: un
    demo que sale distinto cada vez no sirve para comparar dos versiones
    ni para volver a grabar el mismo GIF.
    """
    import random
    rnd = random.Random(semilla)

    # Niveles en RMS de muestra de 16 bits. Salen de la escala de
    # nivel(): -18 dBFS cae en 0,8 de la onda, que es una voz normal a
    # medio metro, y -48 en 0,05, que es el fondo de una habitacion.
    RMS_FUERTE, RMS_FLOJA, RMS_FONDO = 4100.0, 2300.0, 130.0

    tramos = []          # (segundos, rms objetivo)
    for palabra in frase.split():
        for i in range(_silabas(palabra)):
            # La primera silaba de cada palabra suena algo mas fuerte:
            # sin esa diferencia la onda sale como un peine regular, que
            # es justo lo que no parece una voz.
            base = RMS_FUERTE if i == 0 else RMS_FLOJA
            tramos.append((rnd.uniform(0.11, 0.19),
                           base * rnd.uniform(0.75, 1.15)))
            tramos.append((rnd.uniform(0.02, 0.05), RMS_FONDO))
        tramos.append((rnd.uniform(0.06, 0.12), RMS_FONDO))
        if palabra.endswith(","):
            tramos.append((0.22, RMS_FONDO))

    pcm = array.array("h")
    for segundos, rms in tramos:
        n = int(segundos * RATE)
        # Ruido uniforme: su RMS es la amplitud entre raiz de tres, y
        # como nivel() solo mide RMS, no hace falta nada mas elaborado.
        amp = rms * math.sqrt(3.0)
        for _ in range(n):
            pcm.append(int(max(-32768, min(32767, rnd.uniform(-amp, amp)))))
    return pcm


def demo(frase=None):
    """Simula un dictado entero sin abrir el microfono.

    Para ver como queda la tarjeta y para grabar el GIF del README. No
    graba, no transcribe y no pega nada: solo manda a la isla los mismos
    eventos que mandaria un dictado de verdad, al mismo ritmo.

    La ventana de destino SI es real, asi que si lo lanzas desde una
    terminal con una IA dentro sale su logo, igual que al dictar.
    """
    frase = frase or DEMO_FRASE
    destino = sources.ventana_enfocada()
    pcm = _pcm_demo(frase)
    paso = int(CHUNK * RATE)

    enviar(state="oyendo", value=0.0, app=destino["app"],
           ia=destino.get("ia", ""))
    t0 = time.monotonic()
    for i in range(0, len(pcm), paso):
        enviar(state="oyendo", value=nivel(pcm[i:i + paso].tobytes()),
               app=destino["app"], ia=destino.get("ia", ""))
        # Al reloj y no acumulando esperas: enviar tarda lo suyo, y
        # sumando sleeps fijos la onda se iria quedando atras de lo que
        # tardaria el audio de verdad.
        siguiente = (i // paso + 1) * CHUNK
        espera = t0 + siguiente - time.monotonic()
        if espera > 0:
            time.sleep(espera)

    dur = len(pcm) / float(RATE)
    enviar(state="transcribiendo", app=destino["app"],
           ia=destino.get("ia", ""))
    # Whisper tarda aproximadamente la cuarta parte de lo que has
    # hablado (medido: 11 s de audio en 2,9), asi que el demo espera eso
    # y no un numero redondo.
    time.sleep(dur / 4.0)
    enviar(state="listo", text=frase, app=destino["app"],
           ia=destino.get("ia", ""), title="escrito")


# ------------------------------------------------------------- mandos

def vivo():
    try:
        with open(PIDF) as fh:
            pid = int(fh.read().strip())
        os.kill(pid, 0)
        return pid
    except Exception:
        return 0


def start():
    if vivo():
        return
    os.makedirs(RUN, exist_ok=True)
    destino = foco()

    # Doble fork: el proceso que graba tiene que sobrevivir a la orden
    # que lo lanzo, porque sxhkd mata al hijo directo en cuanto termina
    # el atajo.
    if os.fork():
        return
    os.setsid()
    if os.fork():
        os._exit(0)
    with open(PIDF, "w") as fh:
        fh.write(str(os.getpid()))
    try:
        dur = grabar(destino)
        if dur < 0.4:
            enviar(state="error", text="Demasiado corto", app=destino["app"],
                   ia=destino.get("ia", ""))
            os._exit(0)
        enviar(state="transcribiendo", app=destino["app"],
               ia=destino.get("ia", ""))
        texto, err = transcribir(dur)
        if err:
            enviar(state="error", text=err, app=destino["app"])
        elif not texto:
            enviar(state="error", text="No he o\u00eddo nada", app=destino["app"])
        else:
            como = escribir(texto, destino)
            enviar(state="listo", text=texto, app=destino["app"],
                   ia=destino.get("ia", ""),
                   title="escrito" if como == "escrito" else "copiado")
    finally:
        for f in (PIDF, WAV):
            try:
                os.remove(f)
            except OSError:
                pass
        os._exit(0)


def stop():
    pid = vivo()
    if pid:
        os.kill(pid, signal.SIGUSR1)


def cancel():
    pid = vivo()
    if pid:
        os.kill(pid, signal.SIGTERM)
    enviar(state="cancelado", text="Cancelado", ttl=1.5)


if __name__ == "__main__":
    accion = sys.argv[1] if len(sys.argv) > 1 else "toggle"
    if accion == "toggle":
        stop() if vivo() else start()
    elif accion == "start":
        start()
    elif accion == "stop":
        stop()
    elif accion == "cancel":
        cancel()
    elif accion == "demo":
        demo(sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        print(__doc__)
        sys.exit(2)

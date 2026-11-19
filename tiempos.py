# -*- coding: utf-8 -*-
"""Cronometro, temporizador y pomodoro.

Aqui no se dibuja nada: solo vive el TIEMPO, que es un dato con reglas
propias --pausas, fases, rondas- y se puede probar sin abrir una
ventana. Quien pinta lee de aqui.

Todo se mide con time.monotonic() y no con la hora del sistema. Un
cronometro atado al reloj de pared daria un salto de una hora al
cambiar el horario de verano, y se iria al pasado cada vez que ntp
corrige la hora hacia atras: justo lo que no puede pasarle a algo cuya
unica razon de ser es medir cuanto ha pasado.

Y nada de esto se guarda en disco. Un cronometro que sobrevive a
reiniciar el escritorio no es un cronometro, es un registro: si el
proceso se va, lo que estabas midiendo ya no vale.
"""
import math
import time


def mmss(seg, techo=False):
    """Segundos a "M:SS", o a "H:MM:SS" si pasa de la hora.

    'techo' es para las cuentas atras: recien arrancado un
    temporizador de 25 minutos quedan 24,999 segundos, y truncando
    marcaria 24:59 antes de que te hayas soltado el raton. Hacia arriba
    muestra 25:00 el primer segundo, que es lo que acabas de pedir.
    """
    seg = max(0.0, seg)
    t = int(math.ceil(seg - 1e-6) if techo else seg)
    h, m, s = t // 3600, (t // 60) % 60, t % 60
    if h:
        return "%d:%02d:%02d" % (h, m, s)
    return "%d:%02d" % (m, s)


def centesimas(seg):
    """Las centesimas, con su coma. Separadas del resto a proposito:
    cambian cien veces por segundo, asi que no pueden salir del mismo
    sitio que las cifras que ruedan."""
    return ",%02d" % (int(max(0.0, seg) * 100) % 100)


class Cronometro(object):
    """Cuenta hacia arriba. Guarda lo acumulado y el instante del ultimo
    arranque, no una lista de tramos: para saber el total basta sumar."""

    def __init__(self):
        self.t0 = None          # None = parado
        self.acum = 0.0

    @property
    def corriendo(self):
        return self.t0 is not None

    @property
    def activo(self):
        """Hay algo que ensenar, aunque este en pausa."""
        return self.corriendo or self.acum > 0.0

    @property
    def valor(self):
        if self.t0 is None:
            return self.acum
        return self.acum + (time.monotonic() - self.t0)

    def alterna(self):
        if self.t0 is None:
            self.t0 = time.monotonic()
        else:
            self.acum = self.valor
            self.t0 = None

    def reinicia(self):
        self.t0, self.acum = None, 0.0

    def texto(self):
        return mmss(self.valor)


class Cuenta(object):
    """Cuenta atras. La usan el temporizador y cada fase del pomodoro.

    'total' no es decoracion: es lo que da sentido a la barra de
    progreso. Al alargar la cuenta con +1 min crece tambien el total,
    para que la barra siga avanzando en vez de dar un salto atras.
    """

    def __init__(self, total=0.0):
        self.total = float(total)
        self.resta = float(total)
        self.t0 = None

    @property
    def corriendo(self):
        return self.t0 is not None

    @property
    def activa(self):
        return self.total > 0.0

    @property
    def restante(self):
        if self.t0 is None:
            return self.resta
        return max(0.0, self.resta - (time.monotonic() - self.t0))

    @property
    def acabada(self):
        return self.activa and self.restante <= 0.0

    @property
    def frac(self):
        """Lo ya transcurrido, de 0 a 1."""
        if not self.activa:
            return 0.0
        return max(0.0, min(1.0, 1.0 - self.restante / self.total))

    def arranca(self, total=None):
        if total is not None:
            self.total = self.resta = float(total)
        if self.resta <= 0.0:
            return
        self.t0 = time.monotonic()

    def pausa(self):
        if self.t0 is not None:
            self.resta = self.restante
            self.t0 = None

    def alterna(self):
        if self.t0 is None:
            if self.resta <= 0.0:
                self.resta = self.total     # acabada: vuelve a empezar
            self.arranca()
        else:
            self.pausa()

    def reinicia(self):
        """Desde el principio, con el mismo total y parada."""
        self.t0, self.resta = None, self.total

    def borra(self):
        self.t0, self.resta, self.total = None, 0.0, 0.0

    def suma(self, seg):
        """Alarga (o acorta) sin perder el ritmo ni la barra.

        Lo ya transcurrido no se toca NUNCA: el total se recalcula como
        "lo que llevas" mas "lo que queda". Asi, al quitar mas minutos
        de los que faltaban, la cuenta se da por terminada en vez de
        desaparecer como si nunca hubiera existido.
        """
        ido = self.total - self.restante
        r = max(0.0, self.restante + seg)
        self.resta = r
        self.total = ido + r
        if self.t0 is not None:
            self.t0 = time.monotonic()

    def texto(self):
        return mmss(self.restante, techo=True)


class Pomodoro(object):
    """Trabajo, descanso corto y, cada cuatro, uno largo.

    La fase se encadena sola al terminar: parar la cuenta y esperar a
    que vuelvas a pulsar convertiria el descanso en algo que hay que
    administrar, y el pomodoro existe justo para no tener que pensar en
    el reloj.
    """
    # (fase, siguiente etiqueta visible)
    NOMBRES = {"trabajo": "Trabajo", "corto": "Descanso",
               "largo": "Descanso largo"}

    def __init__(self, trabajo=25 * 60, corto=5 * 60, largo=15 * 60, cada=4):
        self.duracion = {"trabajo": trabajo, "corto": corto, "largo": largo}
        self.cada = max(1, cada)
        self.fase = "trabajo"
        self.ronda = 0                  # pomodoros de trabajo completados
        self.cuenta = Cuenta(trabajo)

    @property
    def corriendo(self):
        return self.cuenta.corriendo

    @property
    def activo(self):
        """Empezado: o corre, o esta en pausa a medias."""
        return self.corriendo or self.ronda > 0 or self.cuenta.frac > 0.0

    @property
    def nombre(self):
        return self.NOMBRES[self.fase]

    @property
    def trabajando(self):
        return self.fase == "trabajo"

    @property
    def hechos(self):
        """Pomodoros de la tanda actual, para los puntitos."""
        n = self.ronda % self.cada
        if n == 0 and self.ronda and not self.trabajando:
            # Descanso largo: la tanda esta COMPLETA. El resto se
            # quedaria a cero justo al acabarla, que es el unico momento
            # en que los cuatro puntos significan algo.
            return self.cada
        return n

    def alterna(self):
        self.cuenta.alterna()

    def reinicia(self):
        self.fase, self.ronda = "trabajo", 0
        self.cuenta = Cuenta(self.duracion["trabajo"])

    def avanza(self, seguir=True):
        """Pasa a la fase siguiente y devuelve cual es."""
        if self.trabajando:
            self.ronda += 1
            self.fase = "largo" if self.ronda % self.cada == 0 else "corto"
        else:
            self.fase = "trabajo"
        self.cuenta = Cuenta(self.duracion[self.fase])
        if seguir:
            self.cuenta.arranca()
        return self.fase

    def texto(self):
        return self.cuenta.texto()


class Tiempos(object):
    """Los tres a la vez, que es como los mira la isla."""

    ORDEN = ("crono", "temp", "pomo")

    def __init__(self, trabajo=25 * 60, corto=5 * 60, largo=15 * 60, cada=4):
        self.crono = Cronometro()
        self.temp = Cuenta()
        self.pomo = Pomodoro(trabajo, corto, largo, cada)

    def uno(self, cual):
        return {"crono": self.crono, "temp": self.temp,
                "pomo": self.pomo}[cual]

    def corriendo(self, cual=None):
        if cual is not None:
            return self.uno(cual).corriendo
        return any(self.uno(c).corriendo for c in self.ORDEN)

    def activos(self):
        """[(cual, texto, corriendo)] de lo que haya que ensenar en el
        notch en reposo. En pausa tambien sale: olvidarse de un
        cronometro parado es justo lo que el indicador evita."""
        out = []
        for cual in self.ORDEN:
            o = self.uno(cual)
            if cual == "temp":
                vivo = o.activa and not o.acabada
            else:
                vivo = o.activo
            if vivo:
                out.append((cual, o.texto(), o.corriendo))
        return out

    def textos(self):
        """Lo que se esta mostrando, para enterarse de cuando cambia sin
        reconstruir nada."""
        return dict((c, self.uno(c).texto()) for c in self.ORDEN)

    def cuentas(self):
        """Las cuentas atras, con su nombre: son las que acaban y hay que
        vigilar con un temporizador exacto."""
        return (("temp", self.temp), ("pomo", self.pomo.cuenta))

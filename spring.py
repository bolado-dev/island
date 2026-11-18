# -*- coding: utf-8 -*-
"""Muelle amortiguado, parametrizado como los de SwiftUI.

Se usa un muelle y no una curva de Bezier porque la isla puede cambiar
de destino A MITAD de animacion (llega una notificacion mientras se
repliega otra). Una curva habria que reiniciarla, y se ve el salto; el
muelle arrastra la velocidad que ya llevaba y el cambio es continuo.
"""
import math


class Spring:
    # response: periodo natural en segundos (cuanto tarda en "responder")
    # damping:  1.0 = critico (sin rebote); <1 rebota al llegar
    # escala: cuanto vale UNA unidad de este muelle en pixeles. Los que
    # mueven geometria van en pixeles y valen 1; los que mueven una
    # fraccion de 0 a 1 (fundidos, niveles) valen ~100, asi que se les
    # pasa escala=0.01. Sin eso, el umbral de "ya ha llegado" --pensado
    # en pixeles- se cumple casi al salir: un muelle de 0 a 1 se daba
    # por asentado con un 25% del recorrido aun por hacer y pegaba el
    # ultimo tramo de un salto. De ahi que bajarle la amortiguacion no
    # cambiara nada: nunca llegaba a la parte donde rebota.
    def __init__(self, value=0.0, response=0.38, damping=0.82, escala=1.0):
        self.value = float(value)
        self.target = float(value)
        self.vel = 0.0
        self.escala = float(escala)
        self.configure(response, damping)

    def configure(self, response, damping):
        self.w = 2.0 * math.pi / response   # frecuencia angular natural
        self.z = damping

    def step(self, dt):
        # Integracion semi-implicita de Euler: actualiza velocidad y
        # DESPUES posicion con esa velocidad nueva. Es estable con dt
        # irregulares, cosa que la de Euler explicita no garantiza.
        # El tope de dt evita que un paron del proceso (swap, GC) mande
        # el muelle a tomar viento con un salto enorme.
        dt = min(dt, 1.0 / 30.0)
        x = self.value - self.target
        a = -2.0 * self.z * self.w * self.vel - (self.w ** 2) * x
        self.vel += a * dt
        self.value += self.vel * dt
        if self.settled:
            # Aterrizar EXACTO al parar. El umbral esta pensado en
            # pixeles, asi que un muelle que trabaje en otra escala
            # (una opacidad de 0 a 1) se detendria notablemente corto de
            # su destino y se quedaria ahi para siempre.
            self.value = self.target
            self.vel = 0.0
            return False
        return True

    @property
    def settled(self):
        # Umbrales en px, convertidos a las unidades de este muelle: por
        # debajo de un cuarto de pixel no se ve.
        return (abs(self.value - self.target) < 0.25 * self.escala
                and abs(self.vel) < 0.5 * self.escala)

    def set(self, target):
        self.target = float(target)

    def snap(self, value):
        """Coloca el muelle sin animar (arranque, cambio de monitor)."""
        self.value = self.target = float(value)
        self.vel = 0.0

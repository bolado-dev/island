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
    def __init__(self, value=0.0, response=0.38, damping=0.82):
        self.value = float(value)
        self.target = float(value)
        self.vel = 0.0
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
        # Umbrales en px: por debajo de un cuarto de pixel no se ve.
        return abs(self.value - self.target) < 0.25 and abs(self.vel) < 0.5

    def set(self, target):
        self.target = float(target)

    def snap(self, value):
        """Coloca el muelle sin animar (arranque, cambio de monitor)."""
        self.value = self.target = float(value)
        self.vel = 0.0

"""Petición en curso, disponible sin pasarla por parámetro: permite que señales y servicios sepan quién actúa."""
import contextvars

_peticion = contextvars.ContextVar('auditoria_peticion', default=None)


def fijar(peticion):
    return _peticion.set(peticion)


def restablecer(token):
    _peticion.reset(token)


def actual():
    return _peticion.get()

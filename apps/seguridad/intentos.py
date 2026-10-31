"""Límite de intentos fallidos de inicio de sesión (fuerza bruta).

Se cuenta por cuenta (identificador ingresado) y por dirección IP. Las llaves de la caché son hashes: no guardan el
RUT ni el correo. Al superar el máximo, el acceso queda bloqueado durante `LOGIN_BLOQUEO_SEGUNDOS`.
"""
import hashlib

from django.conf import settings
from django.core.cache import cache


def _llaves(request, identificador):
    ip = request.META.get('REMOTE_ADDR', '')
    cuenta = hashlib.sha256((identificador or '').strip().casefold().encode('utf-8')).hexdigest()[:32]
    return (f'login:cuenta:{cuenta}', f'login:ip:{hashlib.sha256(ip.encode()).hexdigest()[:32]}')


def _maximo():
    return getattr(settings, 'LOGIN_MAX_INTENTOS', 5)


def _ventana():
    return getattr(settings, 'LOGIN_BLOQUEO_SEGUNDOS', 15 * 60)


def bloqueado(request, identificador):
    cuenta, ip = _llaves(request, identificador)
    return cache.get(cuenta, 0) >= _maximo() or cache.get(ip, 0) >= _maximo() * 4


def registrar_fallo(request, identificador):
    for llave in _llaves(request, identificador):
        cache.add(llave, 0, _ventana())
        try:
            cache.incr(llave)
        except ValueError:
            cache.set(llave, 1, _ventana())


def limpiar(request, identificador):
    cache.delete(_llaves(request, identificador)[0])

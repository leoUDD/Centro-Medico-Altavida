"""Llaves de cifrado separadas por propósito. Ninguna vive en la base de datos: todas vienen del entorno (.env).

- clinica:   protege diagnósticos, recetas, resultados, historial y demás datos de salud (CLAVE_CIFRADO).
- identidad: protege los datos que identifican a la persona: RUT, nombre, contacto (CLAVE_IDENTIDAD).
- indices:   firma los índices ciegos (HMAC) que permiten buscar sin descifrar (CLAVE_INDICES).

Quien obtenga la base de datos y una de las llaves no puede leer los datos protegidos por las otras.
Para rotar una llave de cifrado se define la nueva como actual y la vieja como *_ANTERIOR; los datos se
reescriben con `manage.py rotar_llaves`. Cada dato cifrado lleva el identificador de la llave con que se cifró.
"""
import base64
import hashlib

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

PROPOSITOS = ('clinica', 'identidad')


def decodificar(valor, nombre):
    try:
        llave = base64.urlsafe_b64decode(valor)
    except Exception as error:
        raise ImproperlyConfigured(f'{nombre} no es base64 válido.') from error
    if len(llave) != 32:
        raise ImproperlyConfigured(f'{nombre} debe ser una llave de 32 bytes en base64.')
    return llave


def identificador(llave):
    """Identificador corto y público de una llave (no revela la llave): se guarda junto al dato cifrado."""
    return hashlib.sha256(b'altavida:kid:' + llave).hexdigest()[:8]


def _configuradas(proposito):
    if proposito not in PROPOSITOS:
        raise ValueError(f'Propósito de cifrado desconocido: {proposito}')
    return settings.LLAVES_CIFRADO[proposito]


def llave_actual(proposito):
    llave = decodificar(_configuradas(proposito)['actual'], f'Llave {proposito}')
    return identificador(llave), llave


def llave_por_identificador(proposito, kid):
    """Busca entre la llave actual y la anterior (rotación en curso); None si ninguna corresponde."""
    for clave in ('actual', 'anterior'):
        valor = _configuradas(proposito).get(clave)
        if valor:
            llave = decodificar(valor, f'Llave {proposito} ({clave})')
            if identificador(llave) == kid:
                return llave
    return None


def llave_de_indices():
    return decodificar(settings.CLAVE_INDICES, 'CLAVE_INDICES')

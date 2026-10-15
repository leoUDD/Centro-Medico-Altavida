import base64
import hashlib
import hmac

from django.conf import settings

from .rut import normalizar_rut


def _clave_indice():
    # Llave derivada de CLAVE_CIFRADO con un contexto propio, para no reutilizar la llave de AES tal cual.
    clave = base64.urlsafe_b64decode(settings.CLAVE_CIFRADO)
    return hmac.new(clave, b'altavida:indice-ciego', hashlib.sha256).digest()


def indice_ciego(valor):
    """HMAC-SHA256 determinístico: permite buscar por igualdad sin guardar el dato en claro."""
    return hmac.new(_clave_indice(), valor.encode('utf-8'), hashlib.sha256).hexdigest()


def indice_rut(rut):
    return indice_ciego(normalizar_rut(rut))

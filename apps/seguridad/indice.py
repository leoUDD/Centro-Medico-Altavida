import hashlib
import hmac

from .llaves import llave_de_indices
from .rut import normalizar_rut


def indice_ciego(valor, dominio):
    """HMAC-SHA256 determinístico: permite buscar por igualdad sin guardar el dato en claro.

    Cada dominio ("rut", "correo") deriva su propia llave a partir de CLAVE_INDICES, de modo que un índice de
    RUT no puede compararse con uno de correo.
    """
    llave = hmac.new(llave_de_indices(), b'altavida:indice:' + dominio.encode('ascii'), hashlib.sha256).digest()
    return hmac.new(llave, valor.encode('utf-8'), hashlib.sha256).hexdigest()


def indice_rut(rut):
    return indice_ciego(normalizar_rut(rut), 'rut')


def indice_correo(correo):
    return indice_ciego((correo or '').strip().casefold(), 'correo')

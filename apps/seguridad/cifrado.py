import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings

TAMANO_NONCE = 12


def _aes():
    return AESGCM(base64.urlsafe_b64decode(settings.CLAVE_CIFRADO))


def cifrar(texto):
    nonce = os.urandom(TAMANO_NONCE)
    cifrado = _aes().encrypt(nonce, texto.encode('utf-8'), None)
    return base64.urlsafe_b64encode(nonce + cifrado).decode('ascii')


def descifrar(token):
    crudo = base64.urlsafe_b64decode(token.encode('ascii'))
    nonce, cifrado = crudo[:TAMANO_NONCE], crudo[TAMANO_NONCE:]
    return _aes().decrypt(nonce, cifrado, None).decode('utf-8')

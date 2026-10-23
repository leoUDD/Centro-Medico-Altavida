"""Cifrado AES-256-GCM con datos asociados (AAD).

Formato guardado:  <id de llave>.<base64( nonce de 12 bytes + texto cifrado + etiqueta de 16 bytes )>

El contexto (tabla.campo) se usa como dato asociado autenticado: si alguien copia un valor cifrado a otra columna
o tabla, la etiqueta no coincide y el descifrado falla, aunque use la misma llave.
"""
import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .llaves import llave_actual, llave_por_identificador

TAMANO_NONCE = 12


class LlaveDesconocida(Exception):
    """El dato fue cifrado con una llave que ya no está configurada."""


def cifrar(texto, contexto, proposito='clinica'):
    kid, llave = llave_actual(proposito)
    nonce = os.urandom(TAMANO_NONCE)
    cifrado = AESGCM(llave).encrypt(nonce, texto.encode('utf-8'), contexto.encode('utf-8'))
    return f'{kid}.' + base64.urlsafe_b64encode(nonce + cifrado).decode('ascii')


def descifrar(token, contexto, proposito='clinica'):
    kid, _, cuerpo = token.partition('.')
    llave = llave_por_identificador(proposito, kid)
    if llave is None:
        raise LlaveDesconocida(f'No hay una llave "{proposito}" con identificador {kid}.')
    crudo = base64.urlsafe_b64decode(cuerpo.encode('ascii'))
    nonce, cifrado = crudo[:TAMANO_NONCE], crudo[TAMANO_NONCE:]
    return AESGCM(llave).decrypt(nonce, cifrado, contexto.encode('utf-8')).decode('utf-8')


def identificador_de(token):
    return token.partition('.')[0]

"""Envío de SMS. Igual que el correo en desarrollo, el backend por defecto solo registra el mensaje."""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


class SMSError(Exception):
    """El proveedor rechazó el mensaje; el texto es un motivo corto, apto para mostrarse."""


def enviar_sms(telefono, mensaje):
    backend = getattr(settings, 'SMS_BACKEND', 'console')
    if backend == 'console':
        logger.info('SMS a %s: %s', telefono[-4:].rjust(len(telefono), '•'), mensaje)
        return
    raise SMSError('Proveedor de SMS no configurado')

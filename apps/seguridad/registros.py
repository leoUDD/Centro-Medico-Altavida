"""Filtro de registros (logs): enmascara datos personales antes de escribirlos.

Aunque el código evita registrar datos personales, un mensaje de excepción puede incluir un RUT, un correo o un
teléfono. Este filtro los reemplaza en el mensaje y en el traceback.
"""
import logging
import re
import traceback

PATRONES = (
    (re.compile(r'\b\d{1,2}\.?\d{3}\.?\d{3}-?[\dkK]\b'), '[RUT]'),
    (re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+'), '[CORREO]'),
    (re.compile(r'\+?\d[\d ()-]{7,}\d'), '[TELEFONO]'),
)


def redactar(texto):
    for patron, reemplazo in PATRONES:
        texto = patron.sub(reemplazo, texto)
    return texto


class RedactarDatosPersonales(logging.Filter):
    def filter(self, record):
        record.msg = redactar(record.getMessage())
        record.args = ()
        if record.exc_info:
            record.exc_text = redactar(''.join(traceback.format_exception(*record.exc_info)))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = redactar(record.exc_text)
        return True

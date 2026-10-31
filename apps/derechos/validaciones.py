"""Validación de los valores que una persona propone al pedir una rectificación.

Se aplican dos veces: al recibir la solicitud (para rechazar de inmediato un valor imposible) y al ejecutarla (por si la
solicitud se fabricó a mano). Cada función devuelve el valor normalizado o levanta `ValorInvalido` con un mensaje apto
para mostrar al usuario. El valor nunca se escribe en el mensaje ni en la auditoría.
"""
import re
from datetime import date, datetime

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils import timezone

MAX_NOMBRE = 100
MAX_CLINICO = 500
ANIO_MINIMO_NACIMIENTO = 1900

# Letras (con tildes y ñ), separadas por espacio, apóstrofe, guion o punto. Sin dígitos ni otros símbolos.
_NOMBRE = re.compile(r"[^\W\d_]+(?:[ '’.\-]+[^\W\d_]+)*\.?")
_TELEFONO = re.compile(r'\+?\d{8,15}')


class ValorInvalido(ValueError):
    """El valor propuesto no cumple las reglas del campo."""


def _nombre(valor):
    valor = re.sub(r'\s+', ' ', valor).strip()
    if not valor or len(valor) > MAX_NOMBRE or not _NOMBRE.fullmatch(valor):
        raise ValorInvalido(f'Usa solo letras, espacios, guiones o apóstrofes (máximo {MAX_NOMBRE} caracteres).')
    return valor


def _email(valor):
    valor = valor.strip().lower()
    try:
        if len(valor) > 254:
            raise ValidationError('largo')
        validate_email(valor)
    except ValidationError:
        raise ValorInvalido('El correo no tiene un formato válido.')
    return valor


def _telefono(valor):
    compacto = re.sub(r'[\s\-().]', '', valor)
    if not _TELEFONO.fullmatch(compacto):
        raise ValorInvalido('El teléfono debe tener entre 8 y 15 dígitos, con + opcional al inicio (ej. +56912345678).')
    return compacto


def _fecha_nacimiento(valor):
    valor = valor.strip()
    try:
        if re.fullmatch(r'\d{1,2}/\d{1,2}/\d{4}', valor):
            fecha = datetime.strptime(valor, '%d/%m/%Y').date()
        else:
            fecha = date.fromisoformat(valor)
    except ValueError:
        raise ValorInvalido('La fecha debe ser real y estar escrita como AAAA-MM-DD o DD/MM/AAAA.')
    if fecha.year < ANIO_MINIMO_NACIMIENTO or fecha > timezone.localdate():
        raise ValorInvalido(f'La fecha de nacimiento debe estar entre {ANIO_MINIMO_NACIMIENTO} y hoy.')
    return fecha.isoformat()


def _clinico(valor):
    valor = valor.strip()
    if not valor or len(valor) > MAX_CLINICO:
        raise ValorInvalido(f'Describe el dato en hasta {MAX_CLINICO} caracteres.')
    return valor


_REGLAS = {
    'nombres': _nombre, 'apellidos': _nombre, 'email': _email, 'telefono': _telefono,
    'fecha_nacimiento': _fecha_nacimiento, 'clinico': _clinico,
}


def normalizar(campo, valor):
    """Valida `valor` según el campo y lo devuelve en su forma de almacenamiento."""
    regla = _REGLAS.get(campo)
    if regla is None:
        raise ValorInvalido('Ese dato no se puede corregir por este medio.')
    return regla(valor or '')

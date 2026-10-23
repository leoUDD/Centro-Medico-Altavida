"""Anonimización para estadísticas: sale información agregada, nunca registros de personas.

Técnicas aplicadas:
- Supresión: no se incluye RUT, nombre, contacto, código de paciente ni identificadores de fila.
- Generalización: la edad se agrupa en tramos de 10 años, el diagnóstico en su categoría CIE-10 (letra y dos dígitos)
  y la fecha en año-mes.
- k-anonimato: se descartan los grupos con menos de k personas (por defecto 5), porque una combinación poco
  frecuente (p. ej. un niño con cierta categoría en un mes) podría señalar a una persona concreta.
Como el resultado no permite volver al paciente, deja de ser dato personal y puede compartirse con terceros.
"""
from collections import Counter
from datetime import date

from apps.fichas_clinicas.models import Diagnostico

K_MINIMO = 5
COLUMNAS = ['periodo', 'tramo_edad', 'sexo', 'categoria_cie10', 'casos']


def tramo_edad(edad):
    if edad is None:
        return 'Sin dato'
    if edad >= 80:
        return '80+'
    base = (edad // 10) * 10
    return f'{base}-{base + 9}'


def categoria_cie10(codigo):
    """'E11.9' -> 'E11'. Sin código no hay categoría."""
    return (codigo or '').strip().upper()[:3] or 'Sin código'


def _edad_en(fecha_nacimiento, referencia):
    try:
        nacimiento = date.fromisoformat(fecha_nacimiento)
    except (TypeError, ValueError):
        return None
    return referencia.year - nacimiento.year - ((referencia.month, referencia.day) < (nacimiento.month, nacimiento.day))


def reporte_diagnosticos(k=K_MINIMO):
    """Casos por período, tramo de edad, sexo y categoría de diagnóstico, sin grupos de menos de k personas distintas."""
    casos = Counter()
    personas = {}
    for d in Diagnostico.objects.select_related('paciente__identidad'):
        fecha = d.fecha.date()
        clave = (
            f'{fecha:%Y-%m}', tramo_edad(_edad_en(d.paciente.fecha_nacimiento, fecha)),
            d.paciente.sexo or 'Sin dato', categoria_cie10(d.codigo_cie10),
        )
        casos[clave] += 1
        personas.setdefault(clave, set()).add(d.paciente_id)
    return [list(clave) + [n] for clave, n in sorted(casos.items()) if len(personas[clave]) >= k]

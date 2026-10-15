"""Datos para dibujar el calendario mensual de la pantalla de agendamiento."""
import calendar
from datetime import date, timedelta

from django.utils import timezone

from .disponibilidad import HORIZONTE_DIAS

MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre',
         'noviembre', 'diciembre']
DIAS = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']


def parsear_mes(texto):
    """'2026-10' -> (2026, 10), acotado entre el mes actual y el último mes reservable."""
    hoy = timezone.localdate()
    ultimo = hoy + timedelta(days=HORIZONTE_DIAS)
    try:
        anio, mes = (int(x) for x in texto.split('-'))
        elegido = date(anio, mes, 1)
    except (ValueError, AttributeError):
        elegido = hoy.replace(day=1)
    elegido = max(hoy.replace(day=1), min(elegido, ultimo.replace(day=1)))
    return elegido.year, elegido.month


def parsear_dia(texto):
    try:
        return date.fromisoformat(texto)
    except (ValueError, TypeError):
        return None


def _mes_vecino(anio, mes, delta, minimo, maximo):
    total = anio * 12 + (mes - 1) + delta
    vecino = (total // 12, total % 12 + 1)
    return f'{vecino[0]}-{vecino[1]:02d}' if minimo <= vecino <= maximo else None


def construir(anio, mes, dias_ok, seleccionado):
    """Semanas del mes con el estado de cada día, más los meses anterior y siguiente (None si no se puede navegar)."""
    hoy = timezone.localdate()
    ultimo = hoy + timedelta(days=HORIZONTE_DIAS)
    celdas = [None] * date(anio, mes, 1).weekday()
    for numero in range(1, calendar.monthrange(anio, mes)[1] + 1):
        dia = date(anio, mes, numero)
        celdas.append({
            'numero': numero, 'iso': dia.isoformat(), 'disponible': dia in dias_ok, 'elegido': dia == seleccionado,
            'aria': f'{DIAS[dia.weekday()]} {numero} de {MESES[mes - 1]}' + ('' if dia in dias_ok else ', sin horas disponibles'),
        })
    minimo, maximo = (hoy.year, hoy.month), (ultimo.year, ultimo.month)
    return {
        'etiqueta': f'{MESES[mes - 1].capitalize()} {anio}',
        'celdas': celdas,
        'anterior': _mes_vecino(anio, mes, -1, minimo, maximo),
        'siguiente': _mes_vecino(anio, mes, 1, minimo, maximo),
    }


def cuando(inicio):
    """'martes 20 de octubre a las 10:30'."""
    local = timezone.localtime(inicio)
    return f'{DIAS[local.weekday()]} {local.day} de {MESES[local.month - 1]} a las {local:%H:%M}'


def resumen(inicio):
    """'Martes 20 de octubre, 10:30 h'."""
    local = timezone.localtime(inicio)
    texto = f'{DIAS[local.weekday()]} {local.day} de {MESES[local.month - 1]}, {local:%H:%M} h'
    return texto[0].upper() + texto[1:]

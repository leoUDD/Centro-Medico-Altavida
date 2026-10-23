"""Retención: los datos se conservan solo el tiempo que cumplen su función y luego se eliminan.

Plazos (configurables en settings.py):
- Avisos al paciente (Notificacion):                   90 días.
- Orden médica externa subida (archivo y metadatos):  30 días después de la toma de examen.
- Recordatorios enviados y su bitácora de ejecución:  90 y 180 días.
La ficha clínica, las recetas y los resultados NO se purgan aquí: su plazo de conservación es legal y clínico.
"""
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.agenda.models import Cita
from apps.notificaciones.models import EjecucionRecordatorios, Notificacion, Recordatorio


def _dias(nombre, defecto):
    return timedelta(days=getattr(settings, nombre, defecto))


def purgar(ahora=None):
    """Aplica los plazos de retención. Devuelve un diccionario con lo eliminado."""
    ahora = ahora or timezone.now()
    avisos = Notificacion.objects.filter(creada__lt=ahora - _dias('RETENCION_NOTIFICACIONES_DIAS', 90)).delete()[0]
    ordenes = Cita.objects.filter(
        tipo=Cita.Tipo.EXAMEN, inicio__lt=ahora - _dias('RETENCION_ORDEN_EXTERNA_DIAS', 30),
    ).exclude(orden_externa='').update(orden_externa='', orden_externa_nombre='', orden_externa_tipo='')
    recordatorios = Recordatorio.objects.filter(
        cita__inicio__lt=ahora - _dias('RETENCION_RECORDATORIOS_DIAS', 90),
    ).delete()[0]
    ejecuciones = EjecucionRecordatorios.objects.filter(
        fecha__lt=ahora - _dias('RETENCION_EJECUCIONES_DIAS', 180),
    ).delete()[0]
    return {
        'avisos': avisos, 'ordenes_externas': ordenes, 'recordatorios': recordatorios, 'ejecuciones': ejecuciones,
    }

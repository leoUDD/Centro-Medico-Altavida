"""Consulta de oposiciones vigentes. Es lo único que los procesos deben usar para saber si un tratamiento está bloqueado.

Vive aparte de `servicio.py` para que cualquier módulo (consentimientos, recordatorios, estadísticas) pueda importarlo
sin arrastrar el resto del ejercicio de derechos ni crear importaciones circulares.
"""
from .models import OposicionTratamiento


def hay_oposicion(paciente, tratamiento):
    """¿Esta persona tiene hoy bloqueado este tratamiento?"""
    return OposicionTratamiento.objects.filter(
        paciente=paciente, tratamiento=tratamiento, levantada_en__isnull=True,
    ).exists()


def pacientes_opuestos(tratamiento):
    """Ids de los pacientes con el tratamiento bloqueado, para excluirlos de procesos masivos."""
    return OposicionTratamiento.objects.filter(
        tratamiento=tratamiento, levantada_en__isnull=True,
    ).values_list('paciente_id', flat=True)

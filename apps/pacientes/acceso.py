"""Quién puede ver a qué paciente: relación terapéutica y acceso de emergencia."""
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from .models import AccesoEmergencia, AccesoIdentidad, Paciente

DURACION_EMERGENCIA = timedelta(hours=2)
MOTIVO_MINIMO = 15  # caracteres: evita justificaciones vacías como "urgente"


def pacientes_con_relacion(usuario):
    """Pacientes con quienes el médico tiene relación: los creó, o tiene/tuvo cita, diagnóstico o receta con ellos."""
    ahora = timezone.now()
    return Paciente.objects.filter(
        Q(creado_por=usuario)
        | Q(citas__profesional__usuario=usuario, citas__estado__in=['AGENDADA', 'CONFIRMADA'])
        | Q(diagnosticos__medico=usuario)
        | Q(recetas__medico=usuario)
        | Q(accesos_emergencia__medico=usuario, accesos_emergencia__vence__gt=ahora)
    ).distinct()


def tipo_de_acceso(usuario, paciente):
    """'relacion', 'emergencia' o None."""
    if Paciente.objects.filter(pk=paciente.pk).filter(
        Q(creado_por=usuario)
        | Q(citas__profesional__usuario=usuario, citas__estado__in=['AGENDADA', 'CONFIRMADA'])
        | Q(diagnosticos__medico=usuario)
        | Q(recetas__medico=usuario)
    ).exists():
        return 'relacion'
    if AccesoEmergencia.objects.filter(medico=usuario, paciente=paciente, vence__gt=timezone.now()).exists():
        return 'emergencia'
    return None


def abrir_emergencia(usuario, paciente, motivo):
    return AccesoEmergencia.objects.create(
        medico=usuario, paciente=paciente, motivo=motivo.strip(), vence=timezone.now() + DURACION_EMERGENCIA,
    )


def registrar_reidentificacion(usuario, finalidad, cantidad=1):
    """Deja constancia de que `usuario` vio datos identificadores de `cantidad` pacientes."""
    if cantidad:
        AccesoIdentidad.objects.create(usuario=usuario, finalidad=finalidad[:80], cantidad=cantidad)

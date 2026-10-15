"""Cálculo de horas disponibles para consultas y tomas de examen."""
import calendar
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from .models import Cita, HorarioAtencion, HorarioLaboratorio

ANTICIPACION_MINIMA = timedelta(hours=1)
HORIZONTE_DIAS = 60
HORA_LIMITE_AYUNO = time(10, 0)  # con ayuno solo se toman muestras temprano en la mañana


def _franjas(dia, hora_inicio, hora_fin, minutos):
    paso = timedelta(minutes=minutos)
    inicio = timezone.make_aware(datetime.combine(dia, hora_inicio))
    limite = timezone.make_aware(datetime.combine(dia, hora_fin))
    while inicio + paso <= limite:
        yield inicio, inicio + paso
        inicio += paso


def _ventana():
    ahora = timezone.now()
    return ahora + ANTICIPACION_MINIMA, ahora + timedelta(days=HORIZONTE_DIAS)


def horas_consulta(profesionales, dia):
    """{inicio: (profesional, sucursal)} con las horas libres del día; con varios profesionales toma el primero libre."""
    desde, hasta = _ventana()
    libres = {}
    for profesional in profesionales:
        ocupadas = set(
            Cita.objects.filter(profesional=profesional, tipo=Cita.Tipo.CONSULTA, inicio__date=dia)
            .exclude(estado=Cita.Estado.CANCELADA).values_list('inicio', flat=True)
        )
        horarios = HorarioAtencion.objects.filter(profesional=profesional, dia_semana=dia.weekday(), activo=True)
        for horario in horarios.select_related('sucursal'):
            for inicio, _fin in _franjas(dia, horario.hora_inicio, horario.hora_fin, profesional.duracion_minutos):
                if desde <= inicio <= hasta and inicio not in ocupadas:
                    libres.setdefault(inicio, (profesional, horario.sucursal))
    return dict(sorted(libres.items()))


def horas_examen(sucursal, tipo_examen, dia):
    """{inicio: duración en minutos} con las horas de toma de muestra que aún tienen cupo."""
    desde, hasta = _ventana()
    ocupacion = {}
    for inicio in (
        Cita.objects.filter(tipo=Cita.Tipo.EXAMEN, sucursal=sucursal, inicio__date=dia)
        .exclude(estado=Cita.Estado.CANCELADA).values_list('inicio', flat=True)
    ):
        ocupacion[inicio] = ocupacion.get(inicio, 0) + 1
    libres = {}
    for horario in HorarioLaboratorio.objects.filter(sucursal=sucursal, dia_semana=dia.weekday(), activo=True):
        for inicio, _fin in _franjas(dia, horario.hora_inicio, horario.hora_fin, horario.duracion_minutos):
            if tipo_examen.requiere_ayuno and timezone.localtime(inicio).time() >= HORA_LIMITE_AYUNO:
                continue
            if desde <= inicio <= hasta and ocupacion.get(inicio, 0) < horario.cupos:
                libres[inicio] = horario.duracion_minutos
    return dict(sorted(libres.items()))


def dias_con_horas(buscar, anio, mes):
    """Días del mes que tienen al menos una hora libre; `buscar(dia)` devuelve las horas de ese día."""
    hoy = timezone.localdate()
    limite = hoy + timedelta(days=HORIZONTE_DIAS)
    dias = set()
    for numero in range(1, calendar.monthrange(anio, mes)[1] + 1):
        dia = date(anio, mes, numero)
        if hoy <= dia <= limite and buscar(dia):
            dias.add(dia)
    return dias

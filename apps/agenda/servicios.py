"""Reglas de reserva: aquí se valida de nuevo todo lo que la pantalla muestra, dentro de una transacción."""
import base64
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.auditoria import servicio as auditoria
from apps.auditoria.models import Operacion
from apps.notificaciones.models import Notificacion

from .calendario import cuando
from .disponibilidad import horas_consulta, horas_examen
from .models import Cita


class ReservaError(Exception):
    """Mensaje pensado para mostrarse al paciente."""


def _validar_sin_choque(paciente, inicio, fin, excluir):
    choques = Cita.objects.filter(paciente=paciente, inicio__lt=fin, fin__gt=inicio).exclude(estado=Cita.Estado.CANCELADA)
    if excluir is not None:
        choques = choques.exclude(pk=excluir.pk)
    if choques.exists():
        raise ReservaError('Ya tienes otra cita a esa hora. Elige un horario distinto.')


def _cancelar_original(excluir):
    if excluir is not None:
        excluir.estado = Cita.Estado.CANCELADA
        excluir.save(update_fields=['estado'])


def _avisar(cita, titulo, detalle):
    auditoria.registrar(Operacion.CITA_RESERVA, 'cita', cita.pk, detalle={'tipo': cita.tipo})
    Notificacion.objects.create(
        paciente=cita.paciente, tipo=Notificacion.Tipo.CITA, titulo=titulo, detalle=detalle, cita=cita,
    )


def reservar_consulta(paciente, profesional, inicio, modalidad, motivo, reprogramar=None):
    if modalidad == Cita.Modalidad.TELEMEDICINA and not profesional.ofrece_telemedicina:
        raise ReservaError('Este profesional no atiende por telemedicina.')
    try:
        with transaction.atomic():
            libres = horas_consulta([profesional], timezone.localtime(inicio).date())
            if inicio not in libres:
                raise ReservaError('Esa hora ya no está disponible. Elige otra.')
            fin = inicio + timedelta(minutes=profesional.duracion_minutos)
            _validar_sin_choque(paciente, inicio, fin, reprogramar)
            sucursal = libres[inicio][1]
            cita = Cita.objects.create(
                paciente=paciente, tipo=Cita.Tipo.CONSULTA, inicio=inicio, fin=fin, profesional=profesional,
                modalidad=modalidad, sucursal=sucursal if modalidad == Cita.Modalidad.PRESENCIAL else None,
                motivo=motivo,
            )
            _cancelar_original(reprogramar)
            lugar = f'{sucursal}' if modalidad == Cita.Modalidad.PRESENCIAL else 'por videollamada'
            _avisar(
                cita, 'Tu hora quedó agendada',
                f'{profesional.especialidad} con {profesional.nombre}, {cuando(inicio)}, {lugar}.',
            )
    except IntegrityError:
        raise ReservaError('Esa hora ya fue tomada por otra persona. Elige otra.')
    return cita


def _leer_orden_externa(archivo):
    """Valida el archivo subido (PDF, JPG o PNG, hasta 5 MB) y lo devuelve listo para guardarse cifrado."""
    contenido = archivo.read()
    if len(contenido) > 5 * 1024 * 1024:
        raise ReservaError('La orden pesa más de 5 MB.')
    firmas = {b'%PDF': 'application/pdf', b'\xff\xd8\xff': 'image/jpeg', b'\x89PNG': 'image/png'}
    tipo = next((t for f, t in firmas.items() if contenido.startswith(f)), None)
    if tipo is None:
        raise ReservaError('La orden debe ser un PDF o una foto (JPG o PNG).')
    return base64.b64encode(contenido).decode('ascii'), tipo


def reservar_examen(paciente, tipo_examen, sucursal, inicio, orden=None, archivo=None, reprogramar=None):
    if orden is None and archivo is None:
        raise ReservaError('Adjunta una orden médica para agendar el examen.')
    externa, tipo_archivo = _leer_orden_externa(archivo) if orden is None else ('', '')
    with transaction.atomic():
        libres = horas_examen(sucursal, tipo_examen, timezone.localtime(inicio).date())
        if inicio not in libres:
            raise ReservaError('Esa hora ya no está disponible. Elige otra.')
        fin = inicio + timedelta(minutes=libres[inicio])
        _validar_sin_choque(paciente, inicio, fin, reprogramar)
        cita = Cita.objects.create(
            paciente=paciente, tipo=Cita.Tipo.EXAMEN, inicio=inicio, fin=fin, sucursal=sucursal,
            tipo_examen=tipo_examen, orden=orden, orden_externa=externa, orden_externa_tipo=tipo_archivo,
            orden_externa_nombre=(archivo.name[:150] if archivo is not None and orden is None else ''),
        )
        if orden is not None:
            orden.utilizada = True
            orden.save(update_fields=['utilizada'])
        _cancelar_original(reprogramar)
        ayuno = f' Ayuno de {tipo_examen.ayuno_horas} horas.' if tipo_examen.requiere_ayuno else ''
        _avisar(cita, 'Tu toma de examen quedó agendada', f'{tipo_examen}, {cuando(inicio)}, Laboratorio {sucursal}.{ayuno}')
    return cita


def _cita_modificable(cita):
    if not cita.vigente or cita.inicio <= timezone.now():
        raise ReservaError('Esta cita ya no se puede modificar.')


def confirmar_asistencia(cita):
    _cita_modificable(cita)
    cita.estado = Cita.Estado.CONFIRMADA
    cita.save(update_fields=['estado'])
    auditoria.registrar(Operacion.CITA_CAMBIO, 'cita', cita.pk, detalle={'accion': 'confirmar'})


def cancelar_cita(cita):
    _cita_modificable(cita)
    cita.estado = Cita.Estado.CANCELADA
    cita.save(update_fields=['estado'])
    auditoria.registrar(Operacion.CITA_CAMBIO, 'cita', cita.pk, detalle={'accion': 'cancelar'})
    if cita.orden_id:  # la orden de Altavida vuelve a quedar disponible para reagendar
        cita.orden.utilizada = False
        cita.orden.save(update_fields=['utilizada'])

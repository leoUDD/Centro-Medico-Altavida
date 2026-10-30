"""Generación y envío de recordatorios de citas. Pensado para correr por hora desde un programador de tareas."""
import re
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from apps.agenda import calendario
from apps.agenda.models import Cita
from apps.consentimientos import servicio as consentimientos

from .models import EjecucionRecordatorios, Notificacion, PreferenciasNotificacion, Recordatorio, ReglaRecordatorio
from .sms import SMSError, enviar_sms

MARCADORES = ('nombre', 'fecha', 'hora', 'profesional')
_MARCADOR = re.compile(r'\{(' + '|'.join(MARCADORES) + r')\}')


def plantilla_valida(texto):
    """Solo se permiten los cuatro marcadores conocidos; cualquier otra llave podría filtrar datos."""
    restante = _MARCADOR.sub('', texto)
    return '{' not in restante and '}' not in restante


def _valores(cita):
    local = timezone.localtime(cita.inicio)
    if cita.profesional:
        quien = cita.profesional.nombre
    else:
        quien = f'Laboratorio {cita.sucursal}'
    return {
        'nombre': (cita.paciente.nombres.split() or [''])[0],
        'fecha': f'{calendario.DIAS[local.weekday()]} {local.day} de {calendario.MESES[local.month - 1]}',
        'hora': f'{local:%H:%M}',
        'profesional': quien,
    }


def componer_mensaje(regla, cita):
    valores = _valores(cita)
    return _MARCADOR.sub(lambda m: valores[m.group(1)], regla.plantilla)


_FINALIDAD_POR_CANAL = {
    Recordatorio.Canal.CORREO: consentimientos.RECORDATORIOS_CORREO,
    Recordatorio.Canal.SMS: consentimientos.RECORDATORIOS_SMS,
}


def _canales_permitidos(regla, preferencias):
    """Un canal sale solo si la regla lo usa, el paciente lo prefiere y tiene consentimiento vigente para ese canal."""
    canales = []
    if regla.canal_correo and preferencias.canal_correo:
        canales.append(Recordatorio.Canal.CORREO)
    if regla.canal_sms and preferencias.canal_sms:
        canales.append(Recordatorio.Canal.SMS)
    return [c for c in canales if consentimientos.vigente(preferencias.paciente, _FINALIDAD_POR_CANAL[c])]


def generar(ahora=None):
    """Crea los recordatorios que ya corresponde enviar. Devuelve cuántos se crearon.

    Una regla de N horas se considera vigente entre N y N/2 horas antes de la cita, y solo si la cita se agendó
    antes de ese momento: así no se mandan avisos tardíos ni de una hora recién reservada.
    """
    ahora = ahora or timezone.now()
    reglas = list(ReglaRecordatorio.objects.filter(activa=True))
    citas = (
        Cita.objects.filter(inicio__gt=ahora).exclude(estado=Cita.Estado.CANCELADA)
        .select_related('paciente', 'profesional__usuario', 'sucursal')
    )
    creados = 0
    for cita in citas:
        preferencias = None
        for regla in reglas:
            momento = cita.inicio - timedelta(hours=regla.horas_antes)
            if not (momento <= ahora < cita.inicio - timedelta(hours=regla.horas_antes / 2)) or cita.creada > momento:
                continue
            preferencias = preferencias or PreferenciasNotificacion.para(cita.paciente)
            if not getattr(preferencias, f'recordar_{regla.horas_antes}h', True):
                continue
            for canal in _canales_permitidos(regla, preferencias):
                _, nuevo = Recordatorio.objects.get_or_create(
                    cita=cita, regla=regla, canal=canal, defaults={'programado_para': momento},
                )
                creados += nuevo
    return creados


def _enviar_uno(recordatorio):
    cita = recordatorio.cita
    paciente = cita.paciente
    mensaje = componer_mensaje(recordatorio.regla, cita)
    if recordatorio.canal == Recordatorio.Canal.CORREO:
        if not paciente.email:
            raise SMSError('Sin correo registrado')
        try:
            send_mail('Recordatorio de tu hora en Centro Médico Altavida', mensaje,
                      getattr(settings, 'DEFAULT_FROM_EMAIL', None), [paciente.email])
        except Exception as error:  # el servidor de correo rechazó o no respondió
            raise SMSError('Correo rebotado') from error
    else:
        telefono = re.sub(r'[^0-9+]', '', paciente.telefono or '')
        if len(re.sub(r'\D', '', telefono)) < 9:
            raise SMSError('Número inválido')
        enviar_sms(telefono, mensaje)


def _avisar_en_la_cuenta(recordatorio):
    cita = recordatorio.cita
    if Notificacion.objects.filter(cita=cita, titulo__startswith='Recordatorio').exists():
        return
    local = timezone.localtime(cita.inicio)
    if cita.profesional:
        detalle = f'{cita.profesional.especialidad} con {cita.profesional.nombre}, {calendario.cuando(cita.inicio)}, {cita.sucursal or "por videollamada"}. Llega 10 minutos antes.'
    else:
        detalle = f'{cita.tipo_examen}, {calendario.cuando(cita.inicio)}, Laboratorio {cita.sucursal}.'
    Notificacion.objects.create(
        paciente=cita.paciente, tipo=Notificacion.Tipo.CITA, cita=cita, detalle=detalle,
        titulo=f'Recordatorio: tienes hora el {calendario.DIAS[local.weekday()]}',
    )


def enviar_pendientes(recordatorios=None):
    """Intenta enviar cada recordatorio pendiente. Devuelve (enviados, fallidos)."""
    if recordatorios is None:
        recordatorios = Recordatorio.objects.filter(estado=Recordatorio.Estado.PENDIENTE)
    recordatorios = recordatorios.select_related('cita__paciente', 'cita__profesional__usuario', 'cita__sucursal', 'regla')
    enviados = fallidos = 0
    for recordatorio in recordatorios:
        # Se revisa otra vez al enviar: si el paciente revocó después de generarse, el aviso no sale.
        if not consentimientos.vigente(recordatorio.cita.paciente, _FINALIDAD_POR_CANAL[recordatorio.canal]):
            recordatorio.estado, recordatorio.error = Recordatorio.Estado.CANCELADO, 'Sin consentimiento vigente'
            recordatorio.save(update_fields=['estado', 'error'])
            continue
        try:
            _enviar_uno(recordatorio)
        except SMSError as error:
            recordatorio.estado, recordatorio.error = Recordatorio.Estado.FALLIDO, str(error)[:100]
            fallidos += 1
        else:
            recordatorio.estado, recordatorio.error = Recordatorio.Estado.ENVIADO, ''
            recordatorio.enviado_en = timezone.now()
            enviados += 1
            _avisar_en_la_cuenta(recordatorio)
        recordatorio.save(update_fields=['estado', 'error', 'enviado_en'])
    return enviados, fallidos


def ejecutar(ahora=None, usuario=None):
    """Una pasada completa: generar lo que corresponde y enviar lo pendiente."""
    creados = generar(ahora)
    enviados, fallidos = enviar_pendientes()
    return EjecucionRecordatorios.objects.create(
        manual=usuario is not None, usuario=usuario, creados=creados, enviados=enviados, fallidos=fallidos,
    )

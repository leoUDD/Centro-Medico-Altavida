"""Retención: los datos se conservan solo el tiempo que cumplen su función y luego se eliminan.

Plazos (configurables en settings.py):
- Avisos al paciente (Notificacion):                   90 días.
- Orden médica externa subida (archivo y metadatos):  30 días después de la toma de examen.
- Recordatorios enviados y su bitácora de ejecución:  90 y 180 días.
- Datos de gestión no clínicos (correo, teléfono, contacto de emergencia): 24 meses desde la última atención.
- Ficha clínica, citas, recetas y resultados: 15 años desde la última atención (DS 41/2012). Antes de ese plazo no se
  tocan; después se eliminan junto con el diccionario de identidad y queda solo el código seudónimo.
Una persona sin ninguna atención registrada no tiene fecha de referencia y no se purga por estas dos reglas.
"""
import calendar
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.agenda.models import Cita
from apps.auditoria import contencion
from apps.auditoria import servicio as auditoria
from apps.auditoria.models import Operacion
from apps.consentimientos import servicio as consentimientos
from apps.consentimientos.models import Consentimiento, RegistroConsentimiento
from apps.notificaciones.models import EjecucionRecordatorios, Notificacion, PreferenciasNotificacion, Recordatorio
from apps.pacientes.models import Paciente


def _dias(nombre, defecto):
    return timedelta(days=getattr(settings, nombre, defecto))


CAMPOS_CONTACTO = ('email', 'telefono', 'contacto_emergencia_nombre', 'contacto_emergencia_parentesco',
                   'contacto_emergencia_telefono')


def _meses_atras(ahora, meses):
    total = ahora.year * 12 + ahora.month - 1 - meses
    anio, mes = divmod(total, 12)
    mes += 1
    return ahora.replace(year=anio, month=mes, day=min(ahora.day, calendar.monthrange(anio, mes)[1]))


def _ultima_atencion(paciente):
    from apps.derechos import servicio as derechos  # import tardío: derechos usa módulos que importan este
    return derechos._fecha_ultima_atencion(paciente)


def _revocar_consentimientos(paciente):
    """Sin dato de contacto no hay recordatorios posibles: se deja constancia revocando cada consentimiento vigente."""
    codigos = Consentimiento.objects.filter(
        paciente=paciente, estado=Consentimiento.Estado.OTORGADO).values_list('finalidad__codigo', flat=True)
    for codigo in list(codigos):
        consentimientos.revocar(paciente, codigo, None, canal=RegistroConsentimiento.Canal.RETENCION)


def _auditar_paciente(paciente, regla):
    auditoria.registrar(Operacion.RETENCION_APLICADA, 'paciente', paciente.codigo, detalle={'regla': regla})


def purgar_contactos(ahora=None):
    """Elimina el contacto de quien no se atiende hace más de GESTION_RETENCION_MESES. Devuelve cuántas personas."""
    ahora = ahora or timezone.now()
    limite = _meses_atras(ahora, getattr(settings, 'GESTION_RETENCION_MESES', 24))
    personas = 0
    for paciente in Paciente.objects.select_related('identidad', 'usuario').filter(identidad__isnull=False):
        identidad = paciente.identidad
        if not any(getattr(identidad, campo) for campo in CAMPOS_CONTACTO):
            continue
        ultima = _ultima_atencion(paciente)
        if ultima is None or ultima >= limite:
            continue
        with transaction.atomic():
            if not paciente.datos_bloqueados_desde:
                _revocar_consentimientos(paciente)
            for campo in CAMPOS_CONTACTO:
                setattr(identidad, campo, '')
            identidad.save()
            if paciente.usuario_id:
                paciente.usuario.correo_indice = None  # el correo ya no existe: el inicio de sesión por correo tampoco
                paciente.usuario.save(update_fields=['correo_indice'])
            PreferenciasNotificacion.objects.filter(paciente=paciente).delete()
            _auditar_paciente(paciente, 'contacto_vencido')
        personas += 1
    return personas


def purgar_fichas_vencidas(ahora=None):
    """Elimina los datos clínicos y la identidad de quien superó FICHA_CONSERVACION_ANIOS desde su última atención.

    Se conserva solo la fila con el código seudónimo (para no romper el historial de solicitudes y consentimientos).
    Sin identidad ni ficha, esa fila deja de identificar a nadie.
    """
    ahora = ahora or timezone.now()
    hoy = timezone.localtime(ahora).date()
    from apps.derechos import servicio as derechos
    personas = 0
    for paciente in Paciente.objects.filter(identidad__isnull=False):
        hasta = derechos.conservar_hasta(paciente)
        if hasta is None or hasta >= hoy:
            continue
        with transaction.atomic():
            _borrar_datos_clinicos(paciente)
            paciente.identidad.delete()
            if not paciente.datos_bloqueados_desde:
                _revocar_consentimientos(paciente)
                paciente.datos_bloqueados_desde = ahora
                paciente.save(update_fields=['datos_bloqueados_desde'])
            cuenta = paciente.usuario
            if cuenta is not None:
                contencion.revocar_sesiones(cuenta, None, metodo='retencion')
                cuenta.is_active = False
                cuenta.set_unusable_password()
                cuenta.rut_indice = cuenta.correo_indice = None
                cuenta.save()
            _auditar_paciente(paciente, 'ficha_vencida')
        personas += 1
    return personas


MODELOS_CLINICOS = ('Cobertura', 'AccesoEmergencia', 'Cita', 'HistorialMedico', 'Diagnostico', 'AccesoFicha', 'Receta',
                    'ResultadoExamen', 'OrdenExamen')


def _borrar_datos_clinicos(paciente):
    """Borra todo lo que cuelga del paciente y es clínico. No toca consentimientos ni solicitudes de derechos."""
    for relacion in Paciente._meta.related_objects:
        if relacion.related_model.__name__ in MODELOS_CLINICOS:
            relacion.related_model.objects.filter(**{relacion.field.name: paciente}).delete()


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
    resultado = {
        'avisos': avisos, 'ordenes_externas': ordenes, 'recordatorios': recordatorios, 'ejecuciones': ejecuciones,
        'contactos_vencidos': purgar_contactos(ahora), 'fichas_vencidas': purgar_fichas_vencidas(ahora),
    }
    auditoria.registrar(Operacion.RETENCION_APLICADA, 'sistema', '', detalle={'cantidad': sum(resultado.values())})
    return resultado

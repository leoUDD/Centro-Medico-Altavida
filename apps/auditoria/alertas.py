"""Detección de comportamientos sospechosos sobre el registro de auditoría.

Cada regla busca un patrón en una ventana de tiempo y, si lo encuentra, crea una alerta (una sola por hecho: la
clave incluye la ventana). Una alerta no es todavía un incidente: una persona la revisa y la clasifica como evento
sospechoso, incidente confirmado o falsa alarma (ver plan de respuesta a incidentes).

Las alertas no contienen datos personales: solo ids de cuenta, códigos seudónimos y cantidades.
"""
from datetime import timedelta

from django.conf import settings
from django.db.models import Count
from django.utils import timezone

from . import servicio
from .models import AlertaSeguridad, EstadoAlerta, EventoAuditoria, Operacion, Resultado, Severidad

UMBRALES = {
    'fuerza_bruta_cuenta': {'eventos': 5, 'minutos': 15},
    'rociado_contrasenas': {'cuentas': 8, 'minutos': 15},
    'acceso_masivo_fichas': {'pacientes': 15, 'minutos': 10},
    'busquedas_excesivas': {'eventos': 30, 'minutos': 10},
    'emergencias_repetidas': {'eventos': 3, 'horas': 24},
    'denegaciones_repetidas': {'eventos': 5, 'minutos': 10},
    'exportacion_masiva': {'eventos': 3, 'minutos': 60},
    'acceso_nocturno': {'desde': 0, 'hasta': 5},
}
ROLES_SENSIBLES = ('MEDICO', 'PRIVACIDAD', 'ADMIN_SISTEMA')

TRANSICIONES = {
    EstadoAlerta.ABIERTA: {EstadoAlerta.EN_REVISION, EstadoAlerta.DESCARTADA},
    EstadoAlerta.EN_REVISION: {EstadoAlerta.SOSPECHOSO, EstadoAlerta.INCIDENTE, EstadoAlerta.DESCARTADA},
    EstadoAlerta.SOSPECHOSO: {EstadoAlerta.EN_REVISION, EstadoAlerta.INCIDENTE, EstadoAlerta.DESCARTADA},
    EstadoAlerta.INCIDENTE: {EstadoAlerta.CERRADA},
    EstadoAlerta.DESCARTADA: set(),
    EstadoAlerta.CERRADA: set(),
}
NOTA_MINIMA_CIERRE = 20  # caracteres: un incidente no se cierra sin dejar escrito qué pasó y cómo se resolvió


class TransicionInvalida(Exception):
    """Mensaje pensado para mostrarse a quien gestiona la alerta."""


def umbral(regla, clave):
    return getattr(settings, 'ALERTAS_UMBRALES', {}).get(regla, {}).get(clave, UMBRALES[regla][clave])


def _bucket(ahora, ventana):
    return int(ahora.timestamp() // ventana.total_seconds())


def _crear(regla, severidad, sujeto, ventana, ahora, resumen, actor_id=None, recurso_ref='', cantidad=0):
    clave = f'{regla}:{sujeto}:{_bucket(ahora, ventana)}'
    alerta, creada = AlertaSeguridad.objects.get_or_create(clave=clave, defaults={
        'regla': regla, 'severidad': severidad, 'actor_id': actor_id, 'recurso_ref': recurso_ref,
        'resumen': resumen[:200], 'cantidad': cantidad, 'fecha': ahora,
    })
    if creada:
        servicio.registrar(Operacion.ALERTA_GENERADA, 'alerta', alerta.pk, detalle={'regla': regla, 'cantidad': cantidad})
    return alerta if creada else None


def _ventana(regla, ahora, unidad='minutos'):
    valor = umbral(regla, unidad)
    return timedelta(minutes=valor) if unidad == 'minutos' else timedelta(hours=valor)


def _fuerza_bruta_cuenta(ahora):
    ventana = _ventana('fuerza_bruta_cuenta', ahora)
    filas = (EventoAuditoria.objects.filter(operacion=Operacion.SESION_FALLO, fecha__gte=ahora - ventana)
             .exclude(actor_ref='').values('actor_ref').annotate(n=Count('id')).filter(n__gte=umbral('fuerza_bruta_cuenta', 'eventos')))
    return [_crear('fuerza_bruta_cuenta', Severidad.MEDIA, f['actor_ref'], ventana, ahora,
                   f"{f['n']} intentos fallidos contra la misma cuenta", recurso_ref=f['actor_ref'], cantidad=f['n']) for f in filas]


def _rociado_contrasenas(ahora):
    ventana = _ventana('rociado_contrasenas', ahora)
    filas = (EventoAuditoria.objects.filter(operacion=Operacion.SESION_FALLO, fecha__gte=ahora - ventana)
             .exclude(ip_hash='').values('ip_hash').annotate(n=Count('actor_ref', distinct=True))
             .filter(n__gte=umbral('rociado_contrasenas', 'cuentas')))
    return [_crear('rociado_contrasenas', Severidad.ALTA, f['ip_hash'], ventana, ahora,
                   f"Intentos fallidos contra {f['n']} cuentas distintas desde un mismo origen", recurso_ref=f['ip_hash'], cantidad=f['n'])
            for f in filas]


def _acceso_masivo_fichas(ahora):
    ventana = _ventana('acceso_masivo_fichas', ahora)
    filas = (EventoAuditoria.objects.filter(operacion=Operacion.FICHA_CONSULTA, fecha__gte=ahora - ventana, actor_id__isnull=False)
             .values('actor_id').annotate(n=Count('recurso_ref', distinct=True)).filter(n__gte=umbral('acceso_masivo_fichas', 'pacientes')))
    return [_crear('acceso_masivo_fichas', Severidad.ALTA, f['actor_id'], ventana, ahora,
                   f"Consultó {f['n']} fichas distintas en pocos minutos", actor_id=f['actor_id'], cantidad=f['n']) for f in filas]


def _conteo_por_actor(regla, operacion, severidad, resumen, ahora, unidad='minutos'):
    ventana = _ventana(regla, ahora, unidad)
    filas = (EventoAuditoria.objects.filter(operacion=operacion, fecha__gte=ahora - ventana, actor_id__isnull=False)
             .values('actor_id').annotate(n=Count('id')).filter(n__gte=umbral(regla, 'eventos')))
    return [_crear(regla, severidad, f['actor_id'], ventana, ahora, resumen.format(n=f['n']), actor_id=f['actor_id'], cantidad=f['n'])
            for f in filas]


def _busquedas_excesivas(ahora):
    return _conteo_por_actor('busquedas_excesivas', Operacion.BUSQUEDA_PACIENTES, Severidad.MEDIA,
                             '{n} búsquedas de pacientes en pocos minutos', ahora)


def _emergencias_repetidas(ahora):
    return _conteo_por_actor('emergencias_repetidas', Operacion.EMERGENCIA_ACCESO, Severidad.ALTA,
                             '{n} accesos de emergencia en 24 horas', ahora, unidad='horas')


def _denegaciones_repetidas(ahora):
    return _conteo_por_actor('denegaciones_repetidas', Operacion.ACCESO_DENEGADO, Severidad.MEDIA,
                             '{n} accesos denegados seguidos (posible exploración de permisos)', ahora)


def _exportacion_masiva(ahora):
    return _conteo_por_actor('exportacion_masiva', Operacion.EXPORTACION_DATOS, Severidad.ALTA,
                             '{n} exportaciones de datos en una hora', ahora)


def _cambio_rol_sensible(ahora):
    creadas = []
    for evento in EventoAuditoria.objects.filter(operacion=Operacion.CUENTA_ROL_CAMBIO, fecha__gte=ahora - timedelta(hours=25)):
        if evento.detalle.get('rol_nuevo') in ROLES_SENSIBLES:
            creadas.append(_crear('cambio_rol_sensible', Severidad.MEDIA, f'evento{evento.id}', timedelta(days=3650), ahora,
                                  f"La cuenta {evento.recurso_ref} pasó a un rol con acceso sensible", actor_id=evento.actor_id,
                                  recurso_ref=evento.recurso_ref, cantidad=1))
    return creadas


def _acceso_nocturno(ahora):
    desde, hasta = umbral('acceso_nocturno', 'desde'), umbral('acceso_nocturno', 'hasta')
    creadas = []
    recientes = (EventoAuditoria.objects.filter(operacion=Operacion.FICHA_CONSULTA, actor_rol='MEDICO', fecha__gte=ahora - timedelta(hours=1))
                 .values('actor_id', 'fecha'))
    vistos = set()
    for fila in recientes:
        local = timezone.localtime(fila['fecha'])
        if desde <= local.hour < hasta and fila['actor_id'] not in vistos:
            vistos.add(fila['actor_id'])
            creadas.append(_crear('acceso_nocturno', Severidad.BAJA, f"{fila['actor_id']}:{local.date()}", timedelta(days=1), ahora,
                                  'Consulta de fichas en horario nocturno', actor_id=fila['actor_id'], cantidad=1))
    return creadas


def _cadena_rota(ahora):
    integra, primer_problema, _total = servicio.verificar()
    if integra:
        return []
    return [_crear('cadena_rota', Severidad.CRITICA, f'evento{primer_problema}', timedelta(days=3650), ahora,
                   f'La cadena del registro de auditoría no coincide en el evento #{primer_problema}', recurso_ref=str(primer_problema), cantidad=1)]


REGLAS = (_fuerza_bruta_cuenta, _rociado_contrasenas, _acceso_masivo_fichas, _busquedas_excesivas, _emergencias_repetidas,
          _denegaciones_repetidas, _exportacion_masiva, _cambio_rol_sensible, _acceso_nocturno, _cadena_rota)


def detectar(ahora=None):
    """Ejecuta todas las reglas. Devuelve las alertas nuevas (las ya existentes para el mismo hecho no se repiten)."""
    ahora = ahora or timezone.now()
    nuevas = []
    for regla in REGLAS:
        nuevas.extend(a for a in regla(ahora) if a is not None)
    return nuevas


def cambiar_estado(alerta, nuevo, usuario, nota=''):
    """Mueve la alerta por su ciclo de vida respetando las transiciones permitidas y las condiciones de cierre."""
    nuevo = EstadoAlerta(nuevo)
    if nuevo not in TRANSICIONES[EstadoAlerta(alerta.estado)]:
        raise TransicionInvalida(f'No se puede pasar de "{alerta.get_estado_display()}" a "{nuevo.label}".')
    nota = (nota or '').strip()
    if nuevo == EstadoAlerta.CERRADA and (len(nota) < NOTA_MINIMA_CIERRE or not alerta.evidencia_sha256):
        raise TransicionInvalida(
            'Para cerrar un incidente se necesita preservar la evidencia y describir en la nota qué ocurrió y cómo se resolvió '
            f'(al menos {NOTA_MINIMA_CIERRE} caracteres).'
        )
    anterior = alerta.estado
    alerta.estado = nuevo
    alerta.atendida_por = alerta.atendida_por or usuario.pk
    alerta.atendida_en = alerta.atendida_en or timezone.now()
    if nota:
        alerta.nota = servicio.redactar(nota)[:300]
    if nuevo in (EstadoAlerta.DESCARTADA, EstadoAlerta.CERRADA):
        alerta.cerrada_en = timezone.now()
    alerta.save()
    servicio.registrar(Operacion.ALERTA_REVISADA, 'alerta', alerta.pk, Resultado.OK, actor=usuario,
                       detalle={'estado_anterior': anterior, 'estado_nuevo': nuevo.value})
    return alerta

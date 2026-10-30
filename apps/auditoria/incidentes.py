"""Respuesta a incidentes: fases, plazos de notificación y condiciones de cierre.

Las vistas solo llaman a estas funciones; ninguna fase se salta ni se cierra un caso sin cumplir lo que el plan exige.
"""
import secrets

from django.db import transaction
from django.utils import timezone

from . import servicio
from .models import AlertaSeguridad, EstadoAlerta, IncidenteSeguridad, Operacion, Resultado

Clasificacion = IncidenteSeguridad.Clasificacion
Fase = IncidenteSeguridad.Fase

ORDEN_FASES = [Fase.ANALISIS, Fase.CONTENCION, Fase.ERRADICACION, Fase.RECUPERACION, Fase.CERRADO]
MARCAS = {  # notificación -> campo
    'csirt_alerta': 'csirt_alerta_en', 'csirt_actualizacion': 'csirt_actualizacion_en',
    'csirt_informe': 'csirt_informe_final_en', 'agencia': 'agencia_en', 'titulares': 'titulares_en',
}
MIN_LECCIONES = 40  # caracteres: evita cerrar con "ok"


class IncidenteError(Exception):
    """Operación no permitida por el plan; el mensaje es apto para mostrar."""


def _auditar(incidente, actor, accion, resultado=Resultado.OK, **extra):
    servicio.registrar(
        Operacion.INCIDENTE_CAMBIO, 'incidente', incidente.codigo, resultado=resultado, actor=actor,
        detalle={'incidente': incidente.codigo, 'accion': accion, 'estado_nuevo': incidente.fase, **extra},
    )


@transaction.atomic
def abrir(resumen, severidad, actor, alertas=(), conocido_en=None):
    incidente = IncidenteSeguridad.objects.create(
        codigo='IN-' + secrets.token_hex(3).upper(), resumen=resumen[:200], severidad=severidad,
        conocido_en=conocido_en or timezone.now(), responsable_id=actor.pk, creado_por=actor.pk,
    )
    for alerta in alertas:
        incidente.alertas.add(alerta)
        if alerta.estado == EstadoAlerta.ABIERTA:
            alerta.estado, alerta.atendida_por, alerta.atendida_en = EstadoAlerta.EN_REVISION, actor.pk, timezone.now()
            alerta.save()
    _auditar(incidente, actor, 'abierto')
    return incidente


def clasificar(incidente, clasificacion, actor, **criterios):
    """Pasa de evento sospechoso a incidente confirmado (o lo descarta) y registra los criterios de gravedad."""
    if incidente.fase == Fase.CERRADO:
        raise IncidenteError('El caso ya está cerrado.')
    if clasificacion not in Clasificacion.values:
        raise IncidenteError('Clasificación desconocida.')
    campos = ('afecta_datos_personales', 'afecta_continuidad', 'afecta_salud_personas', 'hay_datos_sensibles',
              'hay_menores_14', 'riesgo_razonable')
    for campo in campos:
        if campo in criterios:
            setattr(incidente, campo, bool(criterios[campo]))
    if 'titulares_aprox' in criterios:
        incidente.titulares_aprox = max(0, int(criterios['titulares_aprox'] or 0))
    if 'categorias_datos' in criterios:
        incidente.categorias_datos = str(criterios['categorias_datos'])[:120]
    incidente.clasificacion = clasificacion
    incidente.save()
    _auditar(incidente, actor, 'clasificado', motivo_codigo=clasificacion)
    return incidente


def avanzar(incidente, actor, evidencia_sha256=''):
    """Pasa a la siguiente fase (contención → erradicación → recuperación). El cierre tiene su propio control."""
    if incidente.clasificacion == Clasificacion.SOSPECHOSO and incidente.fase == Fase.ANALISIS:
        raise IncidenteError('Antes de contener hay que clasificar el caso: incidente confirmado o falso positivo.')
    if incidente.clasificacion == Clasificacion.FALSO_POSITIVO:
        raise IncidenteError('Un falso positivo no avanza por las fases: se cierra directamente.')
    posicion = ORDEN_FASES.index(incidente.fase)
    if incidente.fase == Fase.RECUPERACION or incidente.fase == Fase.CERRADO:
        raise IncidenteError('No hay una fase siguiente: corresponde cerrar el caso.')
    siguiente = ORDEN_FASES[posicion + 1]
    ahora = timezone.now()
    if siguiente == Fase.CONTENCION:
        incidente.contenido_en = ahora
        if evidencia_sha256:
            incidente.evidencia_sha256 = evidencia_sha256
        elif not incidente.evidencia_sha256 and not incidente.alertas.exclude(evidencia_sha256='').exists():
            raise IncidenteError('Antes de dar por contenido el caso hay que preservar la evidencia (huella SHA-256).')
        else:
            incidente.evidencia_sha256 = incidente.evidencia_sha256 or incidente.alertas.exclude(evidencia_sha256='').values_list('evidencia_sha256', flat=True).first()
    elif siguiente == Fase.ERRADICACION:
        incidente.erradicado_en = ahora
    else:
        incidente.recuperado_en = ahora
    incidente.fase = siguiente
    incidente.save()
    _auditar(incidente, actor, 'fase')
    return incidente


def proponer_notificacion(incidente, actor):
    """Quien analiza propone notificar; otra persona con permiso de contención debe autorizar."""
    incidente.notificacion_propuesta_por = actor.pk
    incidente.notificacion_autorizada_por = incidente.notificacion_autorizada_en = None
    incidente.save()
    _auditar(incidente, actor, 'notificacion_propuesta')


def autorizar_notificacion(incidente, actor):
    if incidente.notificacion_propuesta_por is None:
        raise IncidenteError('Nadie ha propuesto la notificación todavía.')
    if incidente.notificacion_propuesta_por == actor.pk:
        raise IncidenteError('Quien propone la notificación no puede autorizarla: debe hacerlo otra persona.')
    incidente.notificacion_autorizada_por, incidente.notificacion_autorizada_en = actor.pk, timezone.now()
    incidente.save()
    _auditar(incidente, actor, 'notificacion_autorizada')


def registrar_notificacion(incidente, actor, cual, enviada_en=None):
    """Deja constancia de que se envió una notificación obligatoria. Exige autorización previa y que corresponda."""
    if cual not in MARCAS:
        raise IncidenteError('Notificación desconocida.')
    if cual not in incidente.plazos:
        raise IncidenteError('Según los criterios registrados, esta notificación no corresponde. Revisa la clasificación.')
    if incidente.notificacion_autorizada_por is None:
        raise IncidenteError('La notificación debe estar autorizada por una persona distinta de quien la propuso.')
    campo = MARCAS[cual]
    if getattr(incidente, campo):
        raise IncidenteError('Esa notificación ya fue registrada.')
    setattr(incidente, campo, enviada_en or timezone.now())
    incidente.save()
    _auditar(incidente, actor, 'notificacion_enviada', tipo=cual)


def vencidos(incidente, ahora=None):
    """Plazos de notificación cumplidos sin envío."""
    ahora = ahora or timezone.now()
    return [(clave, texto, limite) for clave, (texto, limite, hecho) in incidente.plazos.items() if hecho is None and limite < ahora]


def pendientes_de_cierre(incidente):
    """Lista de condiciones que aún impiden cerrar. Vacía = se puede cerrar."""
    faltan = []
    if incidente.clasificacion == Clasificacion.SOSPECHOSO:
        return ['Clasificar el caso (incidente confirmado o falso positivo)']
    if incidente.clasificacion == Clasificacion.FALSO_POSITIVO:
        if len(incidente.lecciones.strip()) < MIN_LECCIONES:
            faltan.append('Registrar por qué fue un falso positivo y qué regla ajustar')
        return faltan
    if incidente.fase != Fase.RECUPERACION:
        faltan.append('Completar contención, erradicación y recuperación')
    for clave, (texto, _limite, hecho) in incidente.plazos.items():
        if hecho is None and not incidente.sin_notificar_motivo:
            faltan.append(f'Notificación pendiente: {texto}')
    if len(incidente.lecciones.strip()) < MIN_LECCIONES:
        faltan.append('Registrar las lecciones aprendidas (causa, qué falló, mejoras con responsable)')
    return faltan


def justificar_sin_notificar(incidente, actor, motivo):
    if len(motivo.strip()) < 20:
        raise IncidenteError('Explica con claridad por qué no corresponde notificar.')
    incidente.sin_notificar_motivo = motivo.strip()[:200]
    incidente.save()
    _auditar(incidente, actor, 'sin_notificar')


def registrar_lecciones(incidente, actor, texto):
    incidente.lecciones = texto.strip()
    incidente.save()
    _auditar(incidente, actor, 'lecciones')


@transaction.atomic
def cerrar(incidente, actor):
    faltan = pendientes_de_cierre(incidente)
    if faltan:
        raise IncidenteError('No se puede cerrar: ' + '; '.join(faltan) + '.')
    incidente.fase, incidente.cerrado_en = Fase.CERRADO, timezone.now()
    incidente.save()
    for alerta in incidente.alertas.exclude(estado__in=[EstadoAlerta.CERRADA, EstadoAlerta.DESCARTADA]):
        alerta.estado = EstadoAlerta.DESCARTADA if incidente.clasificacion == Clasificacion.FALSO_POSITIVO else EstadoAlerta.CERRADA
        alerta.cerrada_en = timezone.now()
        alerta.save()
    _auditar(incidente, actor, 'cerrado')

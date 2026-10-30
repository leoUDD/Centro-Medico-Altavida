"""Reglas del consentimiento. Todo cambio pasa por aquí para que el estado, el historial y la auditoría queden juntos."""
from django.db import transaction
from django.utils import timezone

from apps.auditoria import servicio as auditoria
from apps.auditoria.models import Operacion

from .models import Consentimiento, Finalidad, Otorgante, RegistroConsentimiento, Representacion

# Conservador: hasta los 18 años el consentimiento lo da el representante legal, que recepción verificó en persona.
EDAD_CONSENTIMIENTO_PROPIO = 18

RECORDATORIOS_CORREO = 'RECORDATORIOS_CORREO'
RECORDATORIOS_SMS = 'RECORDATORIOS_SMS'
FINALIDAD_POR_CANAL = {'CORREO': RECORDATORIOS_CORREO, 'SMS': RECORDATORIOS_SMS}


class ConsentimientoError(Exception):
    """Operación de consentimiento no permitida; el mensaje es apto para mostrar."""


def texto_vigente(finalidad):
    return finalidad.textos.order_by('-version').first()


def es_menor(paciente):
    edad = paciente.edad
    return edad is not None and edad < EDAD_CONSENTIMIENTO_PROPIO


def vigente(paciente, codigo):
    """¿Hay hoy un consentimiento válido para esta finalidad? Es la única consulta que deben usar los procesos."""
    consentimiento = (
        Consentimiento.objects.filter(paciente=paciente, finalidad__codigo=codigo, finalidad__activa=True,
                                      estado=Consentimiento.Estado.OTORGADO)
        .select_related('texto', 'finalidad', 'representacion').first()
    )
    if consentimiento is None:
        return False
    if consentimiento.texto.version < consentimiento.finalidad.version_minima_valida:
        return False
    if consentimiento.otorgante == Otorgante.REPRESENTANTE:
        # La representación puede terminar (el menor crece) o ser retirada: el consentimiento deja de valer con ella.
        return consentimiento.representacion is not None and consentimiento.representacion.vigente
    return not es_menor(paciente)


def estado_por_finalidad(paciente):
    """Lista para las pantallas: cada finalidad con su consentimiento actual y si hoy está vigente."""
    actuales = {c.finalidad_id: c for c in Consentimiento.objects.filter(paciente=paciente).select_related('texto')}
    filas = []
    for finalidad in Finalidad.objects.filter(activa=True):
        actual = actuales.get(finalidad.pk)
        filas.append({
            'finalidad': finalidad, 'consentimiento': actual, 'vigente': vigente(paciente, finalidad.codigo),
            'texto': texto_vigente(finalidad),
            'requiere_reconfirmar': bool(actual and actual.estado == Consentimiento.Estado.OTORGADO
                                         and actual.texto.version < finalidad.version_minima_valida),
        })
    return filas


def _quien_decide(paciente, actor_paciente):
    """Devuelve (otorgante, representacion) o levanta ConsentimientoError si quien actúa no puede decidir."""
    if actor_paciente is None or actor_paciente.pk == paciente.pk:
        if es_menor(paciente):
            raise ConsentimientoError('Por ser menor de edad, el consentimiento lo debe dar su representante legal.')
        return Otorgante.TITULAR, None
    representacion = Representacion.objects.filter(menor=paciente, representante=actor_paciente).first()
    if representacion is None or not representacion.vigente:
        raise ConsentimientoError('No tienes una representación legal verificada para esta persona.')
    return Otorgante.REPRESENTANTE, representacion


@transaction.atomic
def cambiar(paciente, codigo, otorgar, usuario, actor_paciente=None, canal=RegistroConsentimiento.Canal.PORTAL):
    """Otorga o revoca el consentimiento de `paciente` para `codigo`.

    `actor_paciente` es quien actúa: el titular o, si es menor, su representante.
    """
    try:
        finalidad = Finalidad.objects.get(codigo=codigo, activa=True)
    except Finalidad.DoesNotExist:
        raise ConsentimientoError('Esa finalidad no existe.')
    if paciente.datos_bloqueados_desde:
        raise ConsentimientoError('Los datos de esta persona están bloqueados por una solicitud de supresión.')
    otorgante, representacion = _quien_decide(paciente, actor_paciente)
    texto = texto_vigente(finalidad)
    actual = Consentimiento.objects.filter(paciente=paciente, finalidad=finalidad).first()
    ahora = timezone.now()
    estado_anterior = actual.estado if actual else 'NINGUNO'
    if otorgar:
        if actual and actual.estado == Consentimiento.Estado.OTORGADO and actual.texto_id == texto.pk and vigente(paciente, codigo):
            return actual  # nada cambia: no se ensucia el historial
        valores = dict(texto=texto, estado=Consentimiento.Estado.OTORGADO, otorgado_en=ahora, revocado_en=None,
                       otorgante=otorgante, representacion=representacion)
    else:
        if actual is None or actual.estado == Consentimiento.Estado.REVOCADO:
            return actual
        valores = dict(estado=Consentimiento.Estado.REVOCADO, revocado_en=ahora)
    if actual is None:
        actual = Consentimiento.objects.create(paciente=paciente, finalidad=finalidad, **valores)
    else:
        for campo, valor in valores.items():
            setattr(actual, campo, valor)
        actual.save()
    RegistroConsentimiento.objects.create(
        paciente=paciente, finalidad=finalidad, texto=actual.texto,
        accion=RegistroConsentimiento.Accion.OTORGADO if otorgar else RegistroConsentimiento.Accion.REVOCADO,
        fecha=ahora, otorgante=actual.otorgante if not otorgar else otorgante,
        representacion=actual.representacion if not otorgar else representacion,
        canal=canal, registrado_por=getattr(usuario, 'pk', None),
    )
    auditoria.registrar(
        Operacion.CONSENTIMIENTO_CAMBIO, 'consentimiento', paciente.codigo, actor=usuario,
        detalle={'finalidad': codigo, 'estado_anterior': estado_anterior, 'estado_nuevo': actual.estado,
                 'version': actual.texto.version, 'canal': canal},
    )
    return actual


def otorgar(paciente, codigo, usuario, actor_paciente=None, **kw):
    return cambiar(paciente, codigo, True, usuario, actor_paciente, **kw)


def revocar(paciente, codigo, usuario, actor_paciente=None, **kw):
    return cambiar(paciente, codigo, False, usuario, actor_paciente, **kw)


def acusar_aviso(paciente, version):
    """Deja constancia de que la persona tomó conocimiento del aviso de privacidad. No es un consentimiento."""
    paciente.aviso_privacidad_version = version
    paciente.aviso_privacidad_en = timezone.now()
    paciente.save(update_fields=['aviso_privacidad_version', 'aviso_privacidad_en'])


def cerrar_vencidos(paciente, usuario):
    """Si una representación terminó, los consentimientos que dio el representante se registran como revocados."""
    cambiados = 0
    abiertos = Consentimiento.objects.filter(paciente=paciente, estado=Consentimiento.Estado.OTORGADO,
                                             otorgante=Otorgante.REPRESENTANTE).select_related('finalidad')
    for c in abiertos:
        if vigente(paciente, c.finalidad.codigo):
            continue
        c.estado, c.revocado_en = Consentimiento.Estado.REVOCADO, timezone.now()
        c.save()
        RegistroConsentimiento.objects.create(
            paciente=paciente, finalidad=c.finalidad, texto=c.texto, accion=RegistroConsentimiento.Accion.REVOCADO,
            otorgante=c.otorgante, representacion=c.representacion, registrado_por=getattr(usuario, 'pk', None),
        )
        auditoria.registrar(Operacion.CONSENTIMIENTO_CAMBIO, 'consentimiento', paciente.codigo, actor=usuario,
                            detalle={'finalidad': c.finalidad.codigo, 'estado_nuevo': 'REVOCADO',
                                     'motivo_codigo': 'representacion_terminada'})
        cambiados += 1
    return cambiados

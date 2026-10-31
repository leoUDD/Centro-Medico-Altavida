"""Registro, verificación y depuración del registro de auditoría."""
import hashlib
import hmac
import json
import logging
from datetime import timedelta
from datetime import timezone as dt_timezone

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from apps.seguridad.indice import indice_ciego
from apps.seguridad.llaves import llave_de_auditoria
from apps.seguridad.registros import redactar

from . import contexto
from .models import EventoAuditoria, Operacion, PuntoControlAuditoria, Resultado

logger = logging.getLogger('apps.auditoria')

GENESIS = '0' * 64
RETENCION_MESES_POR_DEFECTO = 24

# Lista cerrada de claves admitidas en `detalle`: todo lo demás se descarta. Son cantidades, estados o códigos cortos.
CLAVES_DETALLE = frozenset({
    'cantidad', 'finalidad', 'campo', 'estado_anterior', 'estado_nuevo', 'regla', 'motivo_codigo', 'vista',
    'tipo', 'version', 'canal', 'formato', 'codigo_solicitud', 'umbral', 'periodo', 'rol_anterior', 'rol_nuevo',
    'accion', 'metodo', 'cuenta', 'eventos', 'alerta', 'incidente',
})
# Nombres que nunca se aceptan aunque alguien los agregue a la lista: credenciales y secretos.
CLAVES_PROHIBIDAS = ('clave', 'contrasena', 'password', 'token', 'llave', 'secret', 'sesion', 'cookie')
LARGO_MAXIMO = 80


def _limpiar_detalle(detalle):
    limpio = {}
    for clave, valor in (detalle or {}).items():
        if clave not in CLAVES_DETALLE or any(p in clave.lower() for p in CLAVES_PROHIBIDAS):
            continue
        if isinstance(valor, bool) or isinstance(valor, int):
            limpio[clave] = valor
        elif isinstance(valor, str):
            limpio[clave] = redactar(valor)[:LARGO_MAXIMO]  # enmascara RUT, correo o teléfono que se cuele en un texto
    return limpio


def _huella_ip(peticion):
    ip = peticion.META.get('REMOTE_ADDR', '') if peticion is not None else ''
    return indice_ciego(ip, 'ip')[:16] if ip else ''


def huella_identificador(identificador):
    """Huella corta y con llave de lo que escribió alguien sin sesión (correo o RUT): permite correlacionar intentos."""
    return indice_ciego((identificador or '').strip().casefold(), 'login')[:16]


def _payload(evento):
    # La fecha va siempre en UTC, como la devuelve la base de datos.
    return json.dumps({
        'uid': str(evento.uid), 'fecha': evento.fecha.astimezone(dt_timezone.utc).isoformat(), 'actor_id': evento.actor_id,
        'actor_rol': evento.actor_rol, 'actor_ref': evento.actor_ref, 'operacion': evento.operacion,
        'recurso_tipo': evento.recurso_tipo, 'recurso_ref': evento.recurso_ref, 'resultado': evento.resultado,
        'ip_hash': evento.ip_hash, 'detalle': evento.detalle,
    }, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def calcular_hash(evento):
    mensaje = (evento.hash_anterior + _payload(evento)).encode('utf-8')
    return hmac.new(llave_de_auditoria(), mensaje, hashlib.sha256).hexdigest()


def _ultimo_hash():
    ultimo = EventoAuditoria.objects.order_by('-id').values_list('hash', flat=True).first()
    if ultimo:
        return ultimo
    punto = PuntoControlAuditoria.objects.order_by('-id').first()
    return punto.hash_ultimo if punto else GENESIS


def registrar(operacion, recurso_tipo='', recurso_ref='', resultado=Resultado.OK, detalle=None, actor=None,
              actor_ref='', peticion=None):
    """Agrega un evento a la cadena. Nunca interrumpe la operación que se está auditando.

    Si el registro falla (base de datos caída, por ejemplo) se anota el fallo en el log —sin datos personales— y la
    operación continúa: bloquear la atención clínica por un fallo de auditoría sería peor que perder un evento, y la
    ausencia se detecta porque la cadena queda con un salto de fecha/id que `verificar_auditoria` y las alertas muestran.
    """
    try:
        peticion = peticion if peticion is not None else contexto.actual()
        if actor is None and peticion is not None:
            usuario = getattr(peticion, 'user', None)
            actor = usuario if usuario is not None and usuario.is_authenticated else None
        evento = EventoAuditoria(
            actor_id=actor.pk if actor is not None else None, actor_rol=getattr(actor, 'rol', '') or '',
            actor_ref=actor_ref, operacion=operacion, recurso_tipo=recurso_tipo, recurso_ref=str(recurso_ref)[:60],
            resultado=resultado, ip_hash=_huella_ip(peticion), detalle=_limpiar_detalle(detalle),
        )
        with transaction.atomic():
            evento.hash_anterior = _ultimo_hash()
            evento.hash = calcular_hash(evento)
            evento.save(force_insert=True)
        return evento
    except Exception:  # noqa: BLE001 - la auditoría no debe tumbar la operación auditada
        logger.exception('No se pudo registrar el evento de auditoría %s', operacion)
        return None


def verificar():
    """Recorre la cadena y comprueba cada hash. Devuelve (íntegra, primer_id_con_problema, total_verificado)."""
    esperado = GENESIS
    primero = EventoAuditoria.objects.order_by('id').first()
    if primero is not None:
        punto = PuntoControlAuditoria.objects.filter(eliminado_hasta_id__lt=primero.id).order_by('-id').first()
        if punto is not None:
            esperado = punto.hash_ultimo
    total = 0
    for evento in EventoAuditoria.objects.order_by('id').iterator():
        if evento.hash_anterior != esperado or evento.hash != calcular_hash(evento):
            return False, evento.id, total
        esperado = evento.hash
        total += 1
    return True, None, total


def meses_de_retencion():
    return getattr(settings, 'AUDITORIA_RETENCION_MESES', RETENCION_MESES_POR_DEFECTO)


def purgar(ahora=None):
    """Elimina los eventos que superaron la retención, siempre desde el más antiguo, y deja un punto de control.

    Es la única forma de eliminar eventos. La base de datos además rechaza (trigger) borrar cualquier evento con menos
    de 24 meses, aunque se intente con SQL directo.
    """
    ahora = ahora or timezone.now()
    limite = ahora - timedelta(days=30 * meses_de_retencion())
    vencidos = EventoAuditoria.objects.filter(fecha__lt=limite)
    ultimo = vencidos.order_by('-id').first()
    if ultimo is None:
        return 0
    # Solo se eliminan eventos contiguos desde el inicio de la cadena (id menor o igual al último vencido continuo).
    primer_vigente = EventoAuditoria.objects.filter(fecha__gte=limite).order_by('id').first()
    tope = (primer_vigente.id - 1) if primer_vigente is not None else ultimo.id
    cantidad = EventoAuditoria.objects.filter(id__lte=tope).count()
    if cantidad == 0:
        return 0
    hash_tope = EventoAuditoria.objects.filter(id__lte=tope).order_by('-id').values_list('hash', flat=True).first()
    with transaction.atomic():
        PuntoControlAuditoria.objects.create(eliminado_hasta_id=tope, hash_ultimo=hash_tope, cantidad=cantidad)
        with connection.cursor() as cursor:  # SQL directo: el ORM bloquea los borrados; el trigger vigila el plazo
            cursor.execute('DELETE FROM auditoria_eventoauditoria WHERE id <= %s', [tope])
    registrar(Operacion.AUDITORIA_PURGA, 'auditoria', '', detalle={'cantidad': cantidad})
    return cantidad

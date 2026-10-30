"""Acciones de contención y recuperación ante un incidente.

Todas dejan un evento CONTENCION en el registro de auditoría (quién, a quién y por qué medio) y ninguna borra datos
ni evidencia: contener es cortar el acceso, no destruir rastros. Pueden ejecutarse desde la interfaz (personal con el
permiso `ejecutar_contencion`) o desde la línea de comandos del servidor, que es el último recurso si la interfaz no
está disponible.
"""
import json
import hashlib
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.utils import timezone

from apps.pacientes.models import AccesoEmergencia

from . import servicio
from .models import AlertaSeguridad, EstadoSistema, EventoAuditoria, ModoSistema, Operacion, Resultado

CLAVE_CACHE_MODO = 'auditoria:modo_sistema'
ROLES_DE_SEGURIDAD = ('ADMIN_SISTEMA', 'PRIVACIDAD')


class ContencionError(Exception):
    """Mensaje pensado para mostrarse a quien ejecuta la acción."""


def _auditar(accion, objetivo, ejecutor, metodo, extra=None):
    detalle = {'accion': accion, 'metodo': metodo}
    detalle.update(extra or {})
    servicio.registrar(Operacion.CONTENCION, 'cuenta', getattr(objetivo, 'pk', ''), actor=ejecutor, detalle=detalle)


def _validar_objetivo(objetivo, ejecutor, forzar):
    if ejecutor is not None and objetivo.pk == ejecutor.pk:
        raise ContencionError('No puedes aplicarte esta acción a ti mismo: pídesela a otra persona.')
    if not forzar and objetivo.rol == 'ADMIN_SISTEMA':
        otros = type(objetivo).objects.filter(rol='ADMIN_SISTEMA', is_active=True, acceso_restringido=False).exclude(pk=objetivo.pk)
        if not otros.exists():
            raise ContencionError('Es el único administrador del sistema activo: contenerlo dejaría el sistema sin administración.')


def _sesiones_de(usuario):
    return [s for s in Session.objects.filter(expire_date__gt=timezone.now()) if s.get_decoded().get('_auth_user_id') == str(usuario.pk)]


def revocar_sesiones(objetivo, ejecutor=None, metodo='interfaz'):
    """Cierra todas las sesiones abiertas de la cuenta. Devuelve cuántas cerró."""
    sesiones = _sesiones_de(objetivo)
    for sesion in sesiones:
        sesion.delete()
    _auditar('revocar_sesiones', objetivo, ejecutor, metodo, {'cantidad': len(sesiones)})
    return len(sesiones)


def desactivar_cuenta(objetivo, ejecutor=None, metodo='interfaz', forzar=False):
    _validar_objetivo(objetivo, ejecutor, forzar)
    objetivo.is_active = False
    objetivo.save(update_fields=['is_active'])
    revocar_sesiones(objetivo, ejecutor, metodo)
    _auditar('desactivar_cuenta', objetivo, ejecutor, metodo)


def restringir_cuenta(objetivo, ejecutor=None, metodo='interfaz', forzar=False):
    """La cuenta sigue existiendo pero pierde todos sus permisos (y sus sesiones abiertas) hasta que se restaure."""
    _validar_objetivo(objetivo, ejecutor, forzar)
    objetivo.acceso_restringido = True
    objetivo.save(update_fields=['acceso_restringido'])
    revocar_sesiones(objetivo, ejecutor, metodo)
    _auditar('restringir_cuenta', objetivo, ejecutor, metodo)


def invalidar_credenciales(objetivo, ejecutor=None, metodo='interfaz', forzar=False):
    """Deja la contraseña inutilizable (por sospecha de que se filtró). Hay que asignar una nueva para recuperar la cuenta."""
    _validar_objetivo(objetivo, ejecutor, forzar)
    objetivo.set_unusable_password()
    objetivo.save(update_fields=['password'])
    revocar_sesiones(objetivo, ejecutor, metodo)
    _auditar('invalidar_credenciales', objetivo, ejecutor, metodo)


def cerrar_emergencias(medico, ejecutor=None, metodo='interfaz'):
    """Vence ahora todos los accesos de emergencia vigentes de un médico. Los registros se conservan."""
    cantidad = AccesoEmergencia.objects.filter(medico=medico, vence__gt=timezone.now()).update(vence=timezone.now())
    _auditar('cerrar_emergencias', medico, ejecutor, metodo, {'cantidad': cantidad})
    return cantidad


def restaurar_cuenta(objetivo, ejecutor=None, metodo='interfaz'):
    """Recuperación: reactiva la cuenta y le devuelve sus permisos. No restablece la contraseña (se asigna aparte)."""
    objetivo.is_active = True
    objetivo.acceso_restringido = False
    objetivo.save(update_fields=['is_active', 'acceso_restringido'])
    _auditar('restaurar_cuenta', objetivo, ejecutor, metodo)


def modo_actual():
    return cache.get_or_set(CLAVE_CACHE_MODO, lambda: EstadoSistema.actual().modo, 3)


def cambiar_modo(modo, ejecutor=None, metodo='interfaz', motivo_codigo=''):
    """Aísla el sistema (solo lectura o bloqueado) o lo devuelve a la normalidad. Lo aplica ModoSistemaMiddleware."""
    modo = ModoSistema(modo)
    estado = EstadoSistema.actual()
    anterior = estado.modo
    estado.modo, estado.cambiado_en, estado.motivo_codigo = modo.value, timezone.now(), motivo_codigo[:40]
    estado.cambiado_por = ejecutor.pk if ejecutor is not None else None
    estado.save()
    cache.delete(CLAVE_CACHE_MODO)
    servicio.registrar(Operacion.CONTENCION, 'sistema', '', actor=ejecutor,
                       detalle={'accion': 'cambiar_modo', 'estado_anterior': anterior, 'estado_nuevo': modo.value, 'metodo': metodo})


def preservar_evidencia(alerta, ejecutor=None, metodo='interfaz', horas_antes=24):
    """Congela los eventos de auditoría relacionados con la alerta en un archivo con huella SHA-256.

    La huella queda en la alerta: si alguien cambia el archivo después, ya no coincide. Los eventos conservan su
    cadena de hashes, así que el paquete puede revisarse contra el registro original.
    """
    desde = alerta.fecha - timedelta(hours=horas_antes)
    eventos = EventoAuditoria.objects.filter(fecha__gte=desde)
    if alerta.actor_id is not None:
        eventos = eventos.filter(actor_id=alerta.actor_id)
    elif alerta.recurso_ref:
        eventos = eventos.filter(actor_ref=alerta.recurso_ref) | eventos.filter(ip_hash=alerta.recurso_ref)
    integra, primer_problema, total = servicio.verificar()
    paquete = {
        'alerta': {'id': alerta.pk, 'regla': alerta.regla, 'severidad': alerta.severidad, 'fecha': alerta.fecha.isoformat(),
                   'actor_id': alerta.actor_id, 'recurso_ref': alerta.recurso_ref},
        'generado_en': timezone.now().isoformat(),
        'cadena': {'integra': integra, 'primer_problema': primer_problema, 'eventos_verificados': total},
        'eventos': [
            {'id': e.id, 'uid': str(e.uid), 'fecha': e.fecha.isoformat(), 'actor_id': e.actor_id, 'actor_rol': e.actor_rol,
             'actor_ref': e.actor_ref, 'operacion': e.operacion, 'recurso_tipo': e.recurso_tipo, 'recurso_ref': e.recurso_ref,
             'resultado': e.resultado, 'ip_hash': e.ip_hash, 'detalle': e.detalle, 'hash_anterior': e.hash_anterior, 'hash': e.hash}
            for e in eventos.order_by('id')[:2000]
        ],
    }
    contenido = json.dumps(paquete, sort_keys=True, ensure_ascii=False, indent=2).encode('utf-8')
    huella = hashlib.sha256(contenido).hexdigest()
    carpeta = Path(getattr(settings, 'EVIDENCIAS_DIR', settings.BASE_DIR / 'evidencias'))
    carpeta.mkdir(parents=True, exist_ok=True)
    archivo = carpeta / f'alerta-{alerta.pk}-{huella[:12]}.json'
    archivo.write_bytes(contenido)
    alerta.evidencia_sha256 = huella
    alerta.save(update_fields=['evidencia_sha256'])
    servicio.registrar(Operacion.CONTENCION, 'alerta', alerta.pk, Resultado.OK, actor=ejecutor,
                       detalle={'accion': 'preservar_evidencia', 'metodo': metodo, 'eventos': len(paquete['eventos'])})
    return contenido, huella, archivo

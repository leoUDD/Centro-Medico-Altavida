"""Registro de auditoría: eventos que permiten reconstruir qué se hizo con los datos personales.

Principios de diseño:
- Solo se agregan eventos; nunca se modifican ni se borran (ver `servicio.py` y la migración 0002, que lo exige
  también dentro de la base de datos mediante triggers).
- Cada evento se encadena con el anterior mediante un HMAC-SHA256 con una llave propia (CLAVE_AUDITORIA): alterar,
  quitar o reordenar un evento rompe la cadena y `verificar_auditoria` lo detecta.
- No guarda datos personales: el paciente se referencia por su código seudónimo, las personas por su id interno y las
  direcciones IP solo como huella con llave. El campo `detalle` solo admite una lista cerrada de claves cortas.
"""
import uuid

from django.db import models
from django.utils import timezone


class Operacion(models.TextChoices):
    # Sesión y cuentas
    SESION_INICIO = 'SESION_INICIO', 'Inicio de sesión'
    SESION_FALLO = 'SESION_FALLO', 'Intento de inicio de sesión fallido'
    SESION_BLOQUEO = 'SESION_BLOQUEO', 'Inicio de sesión bloqueado por intentos'
    SESION_CIERRE = 'SESION_CIERRE', 'Cierre de sesión'
    CUENTA_CREADA = 'CUENTA_CREADA', 'Cuenta creada'
    CUENTA_ROL_CAMBIO = 'CUENTA_ROL_CAMBIO', 'Cambio de rol de una cuenta'
    CUENTA_ESTADO_CAMBIO = 'CUENTA_ESTADO_CAMBIO', 'Cuenta activada o desactivada'
    # Acceso y cambios sobre datos clínicos
    FICHA_CONSULTA = 'FICHA_CONSULTA', 'Consulta de ficha clínica'
    FICHA_CREACION = 'FICHA_CREACION', 'Creación de ficha clínica'
    DIAGNOSTICO_REGISTRO = 'DIAGNOSTICO_REGISTRO', 'Registro de diagnóstico'
    OBSERVACION_EXAMEN = 'OBSERVACION_EXAMEN', 'Observación sobre un examen'
    RECETA_EMISION = 'RECETA_EMISION', 'Emisión de receta'
    EMERGENCIA_ACCESO = 'EMERGENCIA_ACCESO', 'Acceso de emergencia a un paciente'
    # Identidad y agenda
    BUSQUEDA_PACIENTES = 'BUSQUEDA_PACIENTES', 'Búsqueda de pacientes (re-identificación)'
    AGENDA_CONSULTA = 'AGENDA_CONSULTA', 'Consulta de la agenda del día'
    CONTACTO_CORRECCION = 'CONTACTO_CORRECCION', 'Corrección de datos de contacto'
    CITA_RESERVA = 'CITA_RESERVA', 'Reserva de cita'
    CITA_CAMBIO = 'CITA_CAMBIO', 'Confirmación o cancelación de cita'
    # Consentimiento y derechos del titular
    CONSENTIMIENTO_CAMBIO = 'CONSENTIMIENTO_CAMBIO', 'Cambio de consentimiento'
    DERECHO_SOLICITUD = 'DERECHO_SOLICITUD', 'Solicitud de ejercicio de derechos'
    DERECHO_VERIFICACION = 'DERECHO_VERIFICACION', 'Verificación de identidad del solicitante'
    DERECHO_RESOLUCION = 'DERECHO_RESOLUCION', 'Resolución de una solicitud de derechos'
    EXPORTACION_DATOS = 'EXPORTACION_DATOS', 'Exportación de datos personales'
    RECTIFICACION = 'RECTIFICACION', 'Rectificación de datos'
    SUPRESION = 'SUPRESION', 'Supresión o bloqueo de datos'
    # Controles y administración del sistema
    ACCESO_DENEGADO = 'ACCESO_DENEGADO', 'Acceso denegado por falta de permisos'
    ALERTA_GENERADA = 'ALERTA_GENERADA', 'Alerta de seguridad generada'
    ALERTA_REVISADA = 'ALERTA_REVISADA', 'Alerta de seguridad revisada'
    CONTENCION = 'CONTENCION', 'Acción de contención ejecutada'
    AUDITORIA_CONSULTA = 'AUDITORIA_CONSULTA', 'Consulta del registro de auditoría'
    AUDITORIA_VERIFICACION = 'AUDITORIA_VERIFICACION', 'Verificación de integridad del registro'
    AUDITORIA_PURGA = 'AUDITORIA_PURGA', 'Eliminación de eventos vencidos'
    RETENCION_APLICADA = 'RETENCION_APLICADA', 'Retención de datos aplicada'
    LLAVES_ROTADAS = 'LLAVES_ROTADAS', 'Rotación de llaves de cifrado'


class Resultado(models.TextChoices):
    OK = 'OK', 'Exitoso'
    DENEGADO = 'DENEGADO', 'Denegado'
    FALLIDO = 'FALLIDO', 'Fallido'


class SoloAgregarQuerySet(models.QuerySet):
    """Bloquea las operaciones masivas que saltarían la cadena de hashes. La única vía de escritura es servicio.registrar()."""

    def update(self, **kwargs):
        raise PermissionError('Los eventos de auditoría no se pueden modificar.')

    def bulk_update(self, *args, **kwargs):
        raise PermissionError('Los eventos de auditoría no se pueden modificar.')

    def bulk_create(self, *args, **kwargs):
        raise PermissionError('Los eventos de auditoría solo se agregan con servicio.registrar().')

    def delete(self):
        raise PermissionError('Los eventos de auditoría no se pueden eliminar.')


class EventoAuditoria(models.Model):
    id = models.BigAutoField(primary_key=True)  # el orden de los ids es el orden de la cadena
    uid = models.UUIDField('identificador del evento', default=uuid.uuid4, unique=True, editable=False)
    fecha = models.DateTimeField(default=timezone.now, db_index=True)
    # Actor: id interno de la cuenta (no es una clave foránea: el evento sobrevive a la cuenta) y su rol de ese momento.
    actor_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    actor_rol = models.CharField(max_length=15, blank=True)
    # Para actores sin sesión (intentos de inicio de sesión): huella con llave del identificador ingresado.
    actor_ref = models.CharField(max_length=16, blank=True)
    operacion = models.CharField(max_length=30, choices=Operacion.choices, db_index=True)
    recurso_tipo = models.CharField(max_length=30, blank=True)
    # Referencia al recurso afectado: código seudónimo del paciente, id interno o nombre de vista. Nunca datos personales.
    recurso_ref = models.CharField(max_length=60, blank=True, db_index=True)
    resultado = models.CharField(max_length=10, choices=Resultado.choices, default=Resultado.OK)
    ip_hash = models.CharField(max_length=16, blank=True)
    detalle = models.JSONField(default=dict, blank=True)
    hash_anterior = models.CharField(max_length=64, editable=False)
    hash = models.CharField(max_length=64, editable=False, unique=True)

    class Meta:
        ordering = ['id']
        verbose_name = 'evento de auditoría'
        verbose_name_plural = 'eventos de auditoría'

    def __str__(self):
        return f'#{self.id} {self.operacion} {self.resultado}'

    objects = SoloAgregarQuerySet.as_manager()

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError('Los eventos de auditoría no se pueden modificar.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError('Los eventos de auditoría no se pueden eliminar.')


class PuntoControlAuditoria(models.Model):
    """Se crea al eliminar eventos vencidos: conserva el último hash eliminado para que la cadena restante siga verificándose."""

    fecha = models.DateTimeField(default=timezone.now)
    eliminado_hasta_id = models.BigIntegerField()
    hash_ultimo = models.CharField(max_length=64)
    cantidad = models.PositiveIntegerField()

    class Meta:
        ordering = ['id']
        verbose_name = 'punto de control de auditoría'
        verbose_name_plural = 'puntos de control de auditoría'

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError('Los puntos de control no se pueden modificar.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError('Los puntos de control no se pueden eliminar.')


class Severidad(models.TextChoices):
    BAJA = 'BAJA', 'Baja'
    MEDIA = 'MEDIA', 'Media'
    ALTA = 'ALTA', 'Alta'
    CRITICA = 'CRITICA', 'Crítica'


class EstadoAlerta(models.TextChoices):
    """Ciclo de vida alineado con el plan de respuesta: alerta → evento sospechoso → incidente confirmado."""

    ABIERTA = 'ABIERTA', 'Alerta abierta'
    EN_REVISION = 'EN_REVISION', 'En revisión'
    SOSPECHOSO = 'SOSPECHOSO', 'Evento sospechoso'
    INCIDENTE = 'INCIDENTE', 'Incidente confirmado'
    DESCARTADA = 'DESCARTADA', 'Descartada (falsa alarma)'
    CERRADA = 'CERRADA', 'Cerrada'


class AlertaSeguridad(models.Model):
    """Resultado de una regla de detección sobre el registro de auditoría. Sin datos personales: solo ids y códigos."""

    fecha = models.DateTimeField(default=timezone.now, db_index=True)
    regla = models.CharField(max_length=40, db_index=True)
    severidad = models.CharField(max_length=10, choices=Severidad.choices)
    estado = models.CharField(max_length=12, choices=EstadoAlerta.choices, default=EstadoAlerta.ABIERTA, db_index=True)
    actor_id = models.PositiveIntegerField(null=True, blank=True)
    recurso_ref = models.CharField(max_length=60, blank=True)
    resumen = models.CharField(max_length=200)
    cantidad = models.PositiveIntegerField(default=0)
    # Evita repetir la misma alerta por el mismo hecho: regla + sujeto + ventana de tiempo.
    clave = models.CharField(max_length=120, unique=True)
    atendida_por = models.PositiveIntegerField(null=True, blank=True)
    atendida_en = models.DateTimeField(null=True, blank=True)
    cerrada_en = models.DateTimeField(null=True, blank=True)
    nota = models.CharField(max_length=300, blank=True)
    evidencia_sha256 = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ['-fecha']
        verbose_name = 'alerta de seguridad'
        verbose_name_plural = 'alertas de seguridad'

    def __str__(self):
        return f'{self.regla} ({self.get_severidad_display()})'

    @property
    def abierta(self):
        return self.estado not in (EstadoAlerta.DESCARTADA, EstadoAlerta.CERRADA)


class ModoSistema(models.TextChoices):
    NORMAL = 'NORMAL', 'Normal'
    SOLO_LECTURA = 'SOLO_LECTURA', 'Solo lectura (se bloquean los cambios)'
    BLOQUEADO = 'BLOQUEADO', 'Bloqueado (solo personal de seguridad)'


class EstadoSistema(models.Model):
    """Interruptor de contención global (una sola fila): permite aislar el sistema mientras se investiga."""

    modo = models.CharField(max_length=15, choices=ModoSistema.choices, default=ModoSistema.NORMAL)
    cambiado_en = models.DateTimeField(default=timezone.now)
    cambiado_por = models.PositiveIntegerField(null=True, blank=True)
    motivo_codigo = models.CharField(max_length=40, blank=True)

    class Meta:
        verbose_name = 'estado del sistema'
        verbose_name_plural = 'estado del sistema'

    @classmethod
    def actual(cls):
        return cls.objects.order_by('pk').first() or cls.objects.create()

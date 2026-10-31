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
    INCIDENTE_CAMBIO = 'INCIDENTE_CAMBIO', 'Gestión de un incidente de seguridad'
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


class IncidenteSeguridad(models.Model):
    """Caso de respuesta a incidentes. Une alertas, contención, notificaciones obligatorias y lecciones aprendidas.

    Distingue tres niveles: alerta (la dispara una regla), evento sospechoso (alguien lo está analizando) e incidente
    confirmado (hay compromiso real de datos, de cuentas o del servicio). Sin datos personales: solo códigos y cifras.
    """

    class Clasificacion(models.TextChoices):
        SOSPECHOSO = 'SOSPECHOSO', 'Evento sospechoso (en análisis)'
        CONFIRMADO = 'CONFIRMADO', 'Incidente confirmado'
        FALSO_POSITIVO = 'FALSO_POSITIVO', 'Falso positivo'

    class Fase(models.TextChoices):
        ANALISIS = 'ANALISIS', 'Detección y análisis'
        CONTENCION = 'CONTENCION', 'Contenido'
        ERRADICACION = 'ERRADICACION', 'Erradicado'
        RECUPERACION = 'RECUPERACION', 'Recuperado'
        CERRADO = 'CERRADO', 'Cerrado'

    codigo = models.CharField(max_length=12, unique=True)
    alertas = models.ManyToManyField(AlertaSeguridad, blank=True, related_name='incidentes')
    clasificacion = models.CharField(max_length=15, choices=Clasificacion.choices, default=Clasificacion.SOSPECHOSO)
    fase = models.CharField(max_length=15, choices=Fase.choices, default=Fase.ANALISIS)
    severidad = models.CharField(max_length=10, choices=Severidad.choices)
    resumen = models.CharField(max_length=200)
    # T0: el momento en que la institución toma conocimiento. Desde él corren todos los plazos.
    conocido_en = models.DateTimeField(default=timezone.now)
    responsable_id = models.PositiveIntegerField(null=True, blank=True)

    # Criterios de la Ley 21.663 (art. 27) para decidir si tiene efectos significativos.
    afecta_datos_personales = models.BooleanField(default=False)
    afecta_continuidad = models.BooleanField(default=False)
    afecta_salud_personas = models.BooleanField(default=False)
    titulares_aprox = models.PositiveIntegerField(default=0)
    categorias_datos = models.CharField(max_length=120, blank=True)  # p. ej. "clínicos, contacto"
    hay_datos_sensibles = models.BooleanField(default=False)
    hay_menores_14 = models.BooleanField(default=False)
    riesgo_razonable = models.BooleanField(default=False)  # riesgo para derechos y libertades de los titulares

    contenido_en = models.DateTimeField(null=True, blank=True)
    erradicado_en = models.DateTimeField(null=True, blank=True)
    recuperado_en = models.DateTimeField(null=True, blank=True)
    evidencia_sha256 = models.CharField(max_length=64, blank=True)

    # Notificaciones: decisión autorizada por una persona distinta de quien la propone.
    notificacion_propuesta_por = models.PositiveIntegerField(null=True, blank=True)
    notificacion_autorizada_por = models.PositiveIntegerField(null=True, blank=True)
    notificacion_autorizada_en = models.DateTimeField(null=True, blank=True)
    csirt_alerta_en = models.DateTimeField(null=True, blank=True)
    csirt_actualizacion_en = models.DateTimeField(null=True, blank=True)
    csirt_informe_final_en = models.DateTimeField(null=True, blank=True)
    agencia_en = models.DateTimeField(null=True, blank=True)
    titulares_en = models.DateTimeField(null=True, blank=True)
    sin_notificar_motivo = models.CharField(max_length=200, blank=True)  # por qué no corresponde notificar

    lecciones = models.TextField(blank=True)
    creado_por = models.PositiveIntegerField(null=True, blank=True)
    cerrado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-conocido_en']
        verbose_name = 'incidente de seguridad'
        verbose_name_plural = 'incidentes de seguridad'

    def __str__(self):
        return f'{self.codigo} ({self.get_clasificacion_display()})'

    @property
    def efectos_significativos(self):
        """Ley 21.663 art. 27: puede interrumpir un servicio esencial, afectar la salud de personas o sistemas con datos personales."""
        return self.afecta_continuidad or self.afecta_salud_personas or self.afecta_datos_personales

    @property
    def debe_notificar_titulares(self):
        """Ley 21.719 art. 14 sexies: datos sensibles, de menores de 14 años o económicos, con riesgo razonable."""
        return self.afecta_datos_personales and self.riesgo_razonable and (self.hay_datos_sensibles or self.hay_menores_14)

    @property
    def plazos(self):
        """Fechas límite según la ley o la política interna. Las que no aplican quedan fuera."""
        from datetime import timedelta
        t0 = self.conocido_en
        plazos = {}
        if self.clasificacion == self.Clasificacion.FALSO_POSITIVO:
            return plazos
        if self.efectos_significativos:
            plazos['csirt_alerta'] = ('Alerta temprana al CSIRT Nacional (Ley 21.663 art. 9: 3 horas)', t0 + timedelta(hours=3), self.csirt_alerta_en)
            plazos['csirt_actualizacion'] = ('Actualización al CSIRT (72 horas)', t0 + timedelta(hours=72), self.csirt_actualizacion_en)
            if self.csirt_alerta_en:
                plazos['csirt_informe'] = ('Informe final (15 días desde la alerta temprana)', self.csirt_alerta_en + timedelta(days=15), self.csirt_informe_final_en)
        if self.afecta_datos_personales and self.riesgo_razonable:
            plazos['agencia'] = ('Aviso a la Agencia de Protección de Datos (Ley 21.719 art. 14 sexies: sin dilaciones indebidas; meta interna 72 horas)', t0 + timedelta(hours=72), self.agencia_en)
        if self.debe_notificar_titulares:
            plazos['titulares'] = ('Aviso a los titulares afectados (sin dilaciones indebidas; meta interna 72 horas)', t0 + timedelta(hours=72), self.titulares_en)
        return plazos

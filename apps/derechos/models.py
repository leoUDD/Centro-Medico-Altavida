"""Ejercicio de derechos de los titulares: acceso, portabilidad, rectificación y supresión.

Una solicitud es un trámite con estados y plazo, no un botón: recepción → verificación de identidad → evaluación →
resolución (ejecución o respuesta fundamentada) → cierre. Cada paso queda en `HistorialSolicitud` y en la auditoría.
La evaluación y la resolución las hace el Encargado de privacidad, que ve solo códigos seudónimos.
"""
import secrets

from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.seguridad.campos import CampoCifrado


def generar_codigo():
    return 'SD-' + secrets.token_hex(4).upper()


class SolicitudDerecho(models.Model):
    class Tipo(models.TextChoices):
        ACCESO = 'ACCESO', 'Acceso a mis datos'
        PORTABILIDAD = 'PORTABILIDAD', 'Portabilidad (copia en formato estructurado)'
        RECTIFICACION = 'RECTIFICACION', 'Rectificación de un dato'
        SUPRESION = 'SUPRESION', 'Supresión de mis datos'

    class Estado(models.TextChoices):
        RECIBIDA = 'RECIBIDA', 'Recibida'
        EN_VERIFICACION = 'EN_VERIFICACION', 'En verificación de identidad'
        EN_EVALUACION = 'EN_EVALUACION', 'En evaluación'
        RESUELTA = 'RESUELTA', 'Resuelta'
        CERRADA = 'CERRADA', 'Cerrada'

    class Resolucion(models.TextChoices):
        EJECUTADA = 'EJECUTADA', 'Acogida y ejecutada'
        PARCIAL = 'PARCIAL', 'Acogida parcialmente'
        RECHAZADA = 'RECHAZADA', 'Rechazada'

    class Fundamento(models.TextChoices):
        NINGUNO = '', 'Sin observaciones'
        CONSERVACION_LEGAL = 'CONSERVACION_LEGAL', 'Conservación obligatoria de la ficha clínica (DS 41/2012)'
        DATO_CLINICO = 'DATO_CLINICO', 'Los datos clínicos no se modifican: se agrega una anotación aclaratoria'
        IDENTIDAD_NO_VERIFICADA = 'IDENTIDAD_NO_VERIFICADA', 'No fue posible verificar la identidad'
        DATOS_DE_TERCEROS = 'DATOS_DE_TERCEROS', 'Afecta datos de otras personas'
        SIN_REPRESENTACION = 'SIN_REPRESENTACION', 'Falta acreditar la representación legal'
        SOLICITUD_INFUNDADA = 'SOLICITUD_INFUNDADA', 'Solicitud sin fundamento o reiterada'
        DOCUMENTO_REQUERIDO = 'DOCUMENTO_REQUERIDO', 'Debes presentar un documento en recepción'

    class Campo(models.TextChoices):
        NOMBRES = 'nombres', 'Nombres'
        APELLIDOS = 'apellidos', 'Apellidos'
        EMAIL = 'email', 'Correo electrónico'
        TELEFONO = 'telefono', 'Teléfono'
        FECHA_NACIMIENTO = 'fecha_nacimiento', 'Fecha de nacimiento'
        CLINICO = 'clinico', 'Un dato de mi ficha clínica'

    # Campos que cambian la identidad de la persona: exigen verificación reforzada.
    CAMPOS_SENSIBLES = ('nombres', 'apellidos', 'fecha_nacimiento')

    codigo = models.CharField(max_length=12, unique=True, default=generar_codigo, editable=False)
    paciente = models.ForeignKey('pacientes.Paciente', on_delete=models.PROTECT, related_name='solicitudes_derechos')
    solicitante = models.ForeignKey('pacientes.Paciente', on_delete=models.PROTECT, related_name='+')
    tipo = models.CharField(max_length=15, choices=Tipo.choices)
    estado = models.CharField(max_length=16, choices=Estado.choices, default=Estado.RECIBIDA)
    recibida_en = models.DateTimeField(default=timezone.now)
    plazo_hasta = models.DateField()
    nivel_requerido = models.PositiveSmallIntegerField(default=1)  # 1 = contraseña; 2 = contraseña + código al correo
    verificada_en = models.DateTimeField(null=True, blank=True)
    campo = models.CharField(max_length=20, choices=Campo.choices, blank=True)
    valor_propuesto = CampoCifrado(blank=True)
    # Código de un solo uso: solo se guarda su huella, vence rápido y tiene intentos limitados.
    codigo_huella = models.CharField(max_length=64, blank=True, editable=False)
    codigo_expira = models.DateTimeField(null=True, blank=True)
    codigo_intentos = models.PositiveSmallIntegerField(default=0)
    codigos_enviados = models.PositiveSmallIntegerField(default=0)
    resolucion = models.CharField(max_length=10, choices=Resolucion.choices, blank=True)
    fundamento = models.CharField(max_length=30, choices=Fundamento.choices, blank=True)
    respuesta = CampoCifrado(blank=True)  # explicación para el titular
    resuelta_en = models.DateTimeField(null=True, blank=True)
    resuelta_por = models.PositiveIntegerField(null=True, blank=True)
    cerrada_en = models.DateTimeField(null=True, blank=True)
    descarga_hasta = models.DateTimeField(null=True, blank=True)
    descargas = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['-recibida_en']
        constraints = [
            # Una sola solicitud abierta por persona y tipo: evita inundar el trámite y duplicar ejecuciones.
            models.UniqueConstraint(
                fields=['paciente', 'tipo'], condition=~Q(estado='CERRADA'), name='una_solicitud_abierta_por_tipo',
            ),
        ]
        verbose_name = 'solicitud de derechos'
        verbose_name_plural = 'solicitudes de derechos'

    def __str__(self):
        return f'{self.codigo} ({self.get_tipo_display()})'

    @property
    def vencida(self):
        return self.estado != self.Estado.CERRADA and self.resuelta_en is None and self.plazo_hasta < timezone.localdate()


class HistorialSolicitud(models.Model):
    """Cada cambio de estado, inalterable."""

    solicitud = models.ForeignKey(SolicitudDerecho, on_delete=models.PROTECT, related_name='historial')
    fecha = models.DateTimeField(default=timezone.now)
    estado_anterior = models.CharField(max_length=16, blank=True)
    estado_nuevo = models.CharField(max_length=16)
    actor_id = models.PositiveIntegerField(null=True, blank=True)  # None = el sistema
    detalle = models.CharField(max_length=40, blank=True)  # código corto, nunca datos personales

    class Meta:
        ordering = ['id']

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError('El historial de una solicitud no se modifica.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError('El historial de una solicitud no se elimina.')

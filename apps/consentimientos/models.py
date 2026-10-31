"""Gestión del consentimiento.

Alcance (según el análisis de bases de licitud del Hito 1): la atención clínica, la ficha, las recetas, los resultados y el
agendamiento NO se basan en consentimiento (obligación legal, contrato y excepción para salud), por eso no están aquí.
Dependen de consentimiento los usos que el paciente puede rechazar sin perder su atención: hoy, los recordatorios de
citas por correo y por SMS.

Diseño:
- Un consentimiento por finalidad: otorgar uno nunca habilita otra finalidad ni otro canal.
- Los textos que se muestran al paciente tienen versión y no cambian: el consentimiento apunta a la versión exacta
  que aceptó.
- `Consentimiento` guarda el estado actual (otorgado o revocado, con sus fechas); `RegistroConsentimiento` es el
  historial inalterable de cada cambio. Ambos se escriben juntos en servicio.py.
- Minimización: no se guardan direcciones IP, agentes de navegador ni copias del correo o teléfono; solo quién, qué,
  cuándo, con qué versión y por qué canal.
"""
import hashlib

from django.db import models
from django.utils import timezone


class Finalidad(models.Model):
    class Canal(models.TextChoices):
        CORREO = 'CORREO', 'Correo electrónico'
        SMS = 'SMS', 'SMS'

    codigo = models.CharField(max_length=40, unique=True)
    nombre = models.CharField(max_length=120)
    descripcion = models.TextField(help_text='Qué se hará con el dato, en lenguaje simple.')
    dato_usado = models.CharField(max_length=120)
    base_licitud = models.CharField(max_length=60, default='Consentimiento (Ley 21.719, art. 12)')
    canal = models.CharField(max_length=10, choices=Canal.choices, blank=True)
    # Los consentimientos otorgados con una versión de texto anterior a esta ya no valen y hay que volver a pedirlos.
    version_minima_valida = models.PositiveSmallIntegerField(default=1)
    activa = models.BooleanField(default=True)

    class Meta:
        ordering = ['codigo']
        verbose_name_plural = 'finalidades'

    def __str__(self):
        return self.nombre


class TextoConsentimiento(models.Model):
    """Texto exacto que vio el paciente. Inalterable: un cambio es una versión nueva."""

    finalidad = models.ForeignKey(Finalidad, on_delete=models.PROTECT, related_name='textos')
    version = models.PositiveSmallIntegerField()
    texto = models.TextField()
    huella = models.CharField(max_length=64, editable=False)
    publicado_en = models.DateTimeField(default=timezone.now)
    cambia_alcance = models.BooleanField(
        default=False, help_text='Si es verdadero, los consentimientos anteriores dejan de valer hasta que se reconfirmen.',
    )

    class Meta:
        ordering = ['finalidad', 'version']
        constraints = [models.UniqueConstraint(fields=['finalidad', 'version'], name='texto_unico_por_version')]
        verbose_name = 'texto de consentimiento'
        verbose_name_plural = 'textos de consentimiento'

    def __str__(self):
        return f'{self.finalidad.codigo} v{self.version}'

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError('Un texto de consentimiento no se modifica: publica una versión nueva.')
        self.huella = hashlib.sha256(self.texto.encode('utf-8')).hexdigest()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError('Un texto de consentimiento no se elimina: es la prueba de lo que se informó.')


class Otorgante(models.TextChoices):
    TITULAR = 'TITULAR', 'La propia persona'
    REPRESENTANTE = 'REPRESENTANTE', 'Su representante legal'


class Representacion(models.Model):
    """Vínculo entre un menor de edad y su representante legal, verificado en persona por recepción."""

    class Parentesco(models.TextChoices):
        MADRE = 'MADRE', 'Madre'
        PADRE = 'PADRE', 'Padre'
        TUTOR = 'TUTOR', 'Tutor o curador legal'
        OTRO = 'OTRO', 'Otro representante legal'

    class Estado(models.TextChoices):
        PENDIENTE = 'PENDIENTE', 'Pendiente de verificación'
        VERIFICADA = 'VERIFICADA', 'Verificada'
        RECHAZADA = 'RECHAZADA', 'Rechazada'
        TERMINADA = 'TERMINADA', 'Terminada'

    class Acreditacion(models.TextChoices):
        CERTIFICADO_NACIMIENTO = 'CERTIFICADO_NACIMIENTO', 'Certificado de nacimiento'
        RESOLUCION_JUDICIAL = 'RESOLUCION_JUDICIAL', 'Resolución judicial'
        OTRO = 'OTRO', 'Otro documento legal'

    menor = models.ForeignKey('pacientes.Paciente', on_delete=models.CASCADE, related_name='representaciones')
    representante = models.ForeignKey('pacientes.Paciente', on_delete=models.CASCADE, related_name='representados')
    parentesco = models.CharField(max_length=10, choices=Parentesco.choices)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PENDIENTE)
    creada_en = models.DateTimeField(default=timezone.now)
    verificada_en = models.DateTimeField(null=True, blank=True)
    verificada_por = models.PositiveIntegerField(null=True, blank=True)
    # Solo se anota qué documento se revisó en persona; no se guardan copias de cédulas ni certificados.
    acreditacion = models.CharField(max_length=25, choices=Acreditacion.choices, blank=True)
    # Fecha en que el menor cumple la edad de consentimiento propio: desde ahí la representación deja de valer.
    vigente_hasta = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ['-creada_en']
        constraints = [models.UniqueConstraint(fields=['menor', 'representante'], name='representacion_unica')]
        verbose_name = 'representación legal'
        verbose_name_plural = 'representaciones legales'

    def __str__(self):
        return f'Representación {self.pk}: {self.get_estado_display()}'

    @property
    def vigente(self):
        if self.estado != self.Estado.VERIFICADA:
            return False
        return self.vigente_hasta is None or self.vigente_hasta > timezone.localdate()


class Consentimiento(models.Model):
    """Estado actual del consentimiento de un paciente para una finalidad."""

    class Estado(models.TextChoices):
        OTORGADO = 'OTORGADO', 'Otorgado'
        REVOCADO = 'REVOCADO', 'Revocado'

    paciente = models.ForeignKey('pacientes.Paciente', on_delete=models.CASCADE, related_name='consentimientos')
    finalidad = models.ForeignKey(Finalidad, on_delete=models.PROTECT, related_name='consentimientos')
    texto = models.ForeignKey(TextoConsentimiento, on_delete=models.PROTECT, related_name='consentimientos')
    estado = models.CharField(max_length=10, choices=Estado.choices)
    otorgado_en = models.DateTimeField()
    revocado_en = models.DateTimeField(null=True, blank=True)
    otorgante = models.CharField(max_length=15, choices=Otorgante.choices, default=Otorgante.TITULAR)
    representacion = models.ForeignKey(Representacion, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['paciente', 'finalidad'], name='consentimiento_unico_por_finalidad')]
        verbose_name = 'consentimiento'
        verbose_name_plural = 'consentimientos'

    def __str__(self):
        return f'{self.finalidad.codigo}: {self.get_estado_display()}'


class RegistroConsentimiento(models.Model):
    """Historial inalterable: una fila por cada vez que se otorga o se revoca."""

    class Accion(models.TextChoices):
        OTORGADO = 'OTORGADO', 'Otorgado'
        REVOCADO = 'REVOCADO', 'Revocado'

    class Canal(models.TextChoices):
        PORTAL = 'PORTAL', 'Portal del paciente'
        MIGRACION = 'MIGRACION', 'Migración de datos anteriores'
        DERECHOS = 'DERECHOS', 'Supresión por ejercicio de derechos'

    paciente = models.ForeignKey('pacientes.Paciente', on_delete=models.CASCADE, related_name='registros_consentimiento')
    finalidad = models.ForeignKey(Finalidad, on_delete=models.PROTECT, related_name='+')
    texto = models.ForeignKey(TextoConsentimiento, on_delete=models.PROTECT, related_name='+')
    accion = models.CharField(max_length=10, choices=Accion.choices)
    fecha = models.DateTimeField(default=timezone.now, db_index=True)
    otorgante = models.CharField(max_length=15, choices=Otorgante.choices)
    representacion = models.ForeignKey(Representacion, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    canal = models.CharField(max_length=10, choices=Canal.choices, default=Canal.PORTAL)
    registrado_por = models.PositiveIntegerField(null=True, blank=True)  # id interno de la cuenta que hizo el cambio

    class Meta:
        ordering = ['id']
        verbose_name = 'registro de consentimiento'
        verbose_name_plural = 'historial de consentimientos'

    def __str__(self):
        return f'{self.finalidad.codigo} {self.accion} {self.fecha:%d-%m-%Y %H:%M}'

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError('El historial de consentimientos no se modifica.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError('El historial de consentimientos no se elimina.')

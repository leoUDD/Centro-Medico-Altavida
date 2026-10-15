from django.db import models
from django.utils import timezone

from apps.seguridad.campos import CampoCifrado


class Notificacion(models.Model):
    class Tipo(models.TextChoices):
        CITA = 'CITA', 'Cita'
        RESULTADO = 'RESULTADO', 'Resultado'

    paciente = models.ForeignKey('pacientes.Paciente', on_delete=models.CASCADE, related_name='notificaciones')
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    cita = models.ForeignKey('agenda.Cita', on_delete=models.CASCADE, null=True, blank=True, related_name='notificaciones')
    # El título es genérico y no lleva datos clínicos; el detalle (p. ej. fecha y profesional de una cita) va cifrado.
    titulo = models.CharField(max_length=200)
    detalle = CampoCifrado(blank=True)
    leida = models.BooleanField(default=False)
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-creada']
        verbose_name_plural = 'notificaciones'

    @property
    def cuando(self):
        momento = timezone.localtime(self.creada)
        dias = (timezone.localdate() - momento.date()).days
        if dias == 0:
            return f'hoy {momento:%H:%M}'
        if dias == 1:
            return f'ayer {momento:%H:%M}'
        return f'{momento:%d-%m-%Y %H:%M}'

    def __str__(self):
        return f'{self.titulo} (paciente {self.paciente_id})'


class PreferenciasNotificacion(models.Model):
    paciente = models.OneToOneField('pacientes.Paciente', on_delete=models.CASCADE, related_name='preferencias_notificacion')
    canal_correo = models.BooleanField('correo electrónico', default=True)
    canal_sms = models.BooleanField('SMS', default=True)
    canal_navegador = models.BooleanField('notificaciones en el navegador', default=False)
    recordar_48h = models.BooleanField('48 horas antes', default=True)
    recordar_24h = models.BooleanField('24 horas antes', default=True)
    recordar_2h = models.BooleanField('2 horas antes', default=False)

    class Meta:
        verbose_name = 'preferencias de notificación'
        verbose_name_plural = 'preferencias de notificación'

    def __str__(self):
        return f'Preferencias de paciente {self.paciente_id}'

    @classmethod
    def para(cls, paciente):
        """Preferencias del paciente; al crearlas respeta lo elegido en el registro (recordatorios por correo y SMS)."""
        preferencias, _ = cls.objects.get_or_create(
            paciente=paciente,
            defaults={'canal_correo': paciente.recordatorios_activos, 'canal_sms': paciente.recordatorios_activos},
        )
        return preferencias


PLANTILLA_POR_DEFECTO = (
    'Hola {nombre}, te recordamos tu hora en Centro Médico Altavida el {fecha} a las {hora} con {profesional}. '
    'Puedes confirmarla o cambiarla ingresando a tu cuenta.'
)


class ReglaRecordatorio(models.Model):
    """Cuántas horas antes de una cita se avisa al paciente, por qué canales y con qué mensaje."""

    horas_antes = models.PositiveSmallIntegerField(unique=True)
    activa = models.BooleanField(default=True)
    canal_correo = models.BooleanField('correo', default=True)
    canal_sms = models.BooleanField('SMS', default=False)
    con_confirmacion = models.BooleanField('con opción de confirmar', default=False)
    # Solo admite {nombre}, {fecha}, {hora} y {profesional}: nunca datos clínicos.
    plantilla = models.TextField(default=PLANTILLA_POR_DEFECTO)

    class Meta:
        ordering = ['-horas_antes']
        verbose_name = 'regla de recordatorio'
        verbose_name_plural = 'reglas de recordatorio'

    def __str__(self):
        return f'{self.horas_antes} horas antes'

    @property
    def canales_texto(self):
        canales = [n for n, activo in (('Correo', self.canal_correo), ('SMS', self.canal_sms)) if activo]
        return ' y '.join(canales) or 'Sin canales'


class Recordatorio(models.Model):
    class Canal(models.TextChoices):
        CORREO = 'CORREO', 'Correo'
        SMS = 'SMS', 'SMS'

    class Estado(models.TextChoices):
        PENDIENTE = 'PENDIENTE', 'Pendiente'
        ENVIADO = 'ENVIADO', 'Enviado'
        FALLIDO = 'FALLIDO', 'Fallido'

    cita = models.ForeignKey('agenda.Cita', on_delete=models.CASCADE, related_name='recordatorios')
    regla = models.ForeignKey(ReglaRecordatorio, on_delete=models.CASCADE, related_name='recordatorios')
    canal = models.CharField(max_length=10, choices=Canal.choices)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PENDIENTE)
    programado_para = models.DateTimeField()
    enviado_en = models.DateTimeField(null=True, blank=True)
    # Motivo corto del fallo ("Número inválido", "Correo rebotado"…); nunca contiene el dato de contacto.
    error = models.CharField(max_length=100, blank=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-programado_para']
        constraints = [
            models.UniqueConstraint(fields=['cita', 'regla', 'canal'], name='recordatorio_unico_por_regla_y_canal'),
        ]

    def __str__(self):
        return f'{self.get_canal_display()} {self.regla} · cita {self.cita_id} · {self.get_estado_display()}'


class EjecucionRecordatorios(models.Model):
    """Bitácora de cada pasada del generador y enviador de recordatorios."""

    fecha = models.DateTimeField(auto_now_add=True)
    manual = models.BooleanField(default=False)
    usuario = models.ForeignKey('usuarios.Usuario', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    creados = models.PositiveIntegerField(default=0)
    enviados = models.PositiveIntegerField(default=0)
    fallidos = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-fecha']
        verbose_name = 'ejecución de recordatorios'
        verbose_name_plural = 'ejecuciones de recordatorios'

    def __str__(self):
        return f'{self.fecha:%d-%m-%Y %H:%M}: {self.enviados} enviados, {self.fallidos} fallidos'

from django.db import models
from django.db.models import Q

from apps.seguridad.campos import CampoCifrado

DIAS_SEMANA = [(0, 'Lunes'), (1, 'Martes'), (2, 'Miércoles'), (3, 'Jueves'), (4, 'Viernes'), (5, 'Sábado'), (6, 'Domingo')]


class HorarioAtencion(models.Model):
    """Bloque semanal en que un profesional atiende consultas en una sucursal."""

    profesional = models.ForeignKey('profesionales.Profesional', on_delete=models.CASCADE, related_name='horarios')
    sucursal = models.ForeignKey('sucursales.Sucursal', on_delete=models.PROTECT, related_name='horarios_atencion')
    dia_semana = models.PositiveSmallIntegerField(choices=DIAS_SEMANA)
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'horario de atención'
        verbose_name_plural = 'horarios de atención'
        ordering = ['profesional', 'dia_semana', 'hora_inicio']

    def __str__(self):
        return f'{self.profesional} · {self.get_dia_semana_display()} {self.hora_inicio:%H:%M}-{self.hora_fin:%H:%M}'


class HorarioLaboratorio(models.Model):
    """Bloque semanal de toma de muestras de una sucursal, con cupos simultáneos por hora."""

    sucursal = models.ForeignKey('sucursales.Sucursal', on_delete=models.CASCADE, related_name='horarios_laboratorio')
    dia_semana = models.PositiveSmallIntegerField(choices=DIAS_SEMANA)
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()
    duracion_minutos = models.PositiveSmallIntegerField(default=15)
    cupos = models.PositiveSmallIntegerField('cupos por hora', default=2)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'horario de laboratorio'
        verbose_name_plural = 'horarios de laboratorio'
        ordering = ['sucursal', 'dia_semana', 'hora_inicio']

    def __str__(self):
        return f'{self.sucursal} · {self.get_dia_semana_display()} {self.hora_inicio:%H:%M}-{self.hora_fin:%H:%M}'


class Cita(models.Model):
    class Tipo(models.TextChoices):
        CONSULTA = 'CONSULTA', 'Consulta'
        EXAMEN = 'EXAMEN', 'Toma de examen'

    class Estado(models.TextChoices):
        AGENDADA = 'AGENDADA', 'Agendada'
        CONFIRMADA = 'CONFIRMADA', 'Confirmada'
        CANCELADA = 'CANCELADA', 'Cancelada'

    class Modalidad(models.TextChoices):
        PRESENCIAL = 'PRESENCIAL', 'Presencial'
        TELEMEDICINA = 'TELEMEDICINA', 'Telemedicina'

    paciente = models.ForeignKey('pacientes.Paciente', on_delete=models.CASCADE, related_name='citas')
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.AGENDADA)
    inicio = models.DateTimeField()
    fin = models.DateTimeField()
    sucursal = models.ForeignKey('sucursales.Sucursal', on_delete=models.PROTECT, null=True, blank=True, related_name='citas')
    profesional = models.ForeignKey('profesionales.Profesional', on_delete=models.PROTECT, null=True, blank=True, related_name='citas')
    modalidad = models.CharField(max_length=12, choices=Modalidad.choices, blank=True)
    tipo_examen = models.ForeignKey('laboratorio.TipoExamen', on_delete=models.PROTECT, null=True, blank=True, related_name='citas')
    orden = models.ForeignKey('laboratorio.OrdenExamen', on_delete=models.SET_NULL, null=True, blank=True, related_name='citas')

    # Cifrados (AES): motivo de consulta y orden externa subida por el paciente (archivo en base64).
    motivo = CampoCifrado(blank=True)
    orden_externa = CampoCifrado(blank=True)
    orden_externa_nombre = models.CharField(max_length=150, blank=True)
    orden_externa_tipo = models.CharField(max_length=50, blank=True)

    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['inicio']
        constraints = [
            # Un profesional no puede tener dos consultas vigentes a la misma hora (protege contra reservas simultáneas).
            models.UniqueConstraint(
                fields=['profesional', 'inicio'], name='consulta_unica_por_hora',
                condition=Q(tipo='CONSULTA') & ~Q(estado='CANCELADA'),
            ),
        ]

    def __str__(self):
        return f'{self.get_tipo_display()} {self.inicio:%d-%m-%Y %H:%M} (paciente {self.paciente_id})'

    @property
    def vigente(self):
        return self.estado != self.Estado.CANCELADA

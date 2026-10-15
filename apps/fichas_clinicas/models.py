from django.conf import settings
from django.db import models

from apps.seguridad.campos import CampoCifrado


class HistorialMedico(models.Model):
    paciente = models.OneToOneField('pacientes.Paciente', on_delete=models.CASCADE, related_name='historial')
    enfermedades = CampoCifrado(blank=True)
    medicamentos_activos = CampoCifrado(blank=True)
    operaciones = CampoCifrado(blank=True)
    alergias = CampoCifrado(blank=True)

    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'historiales médicos'

    def __str__(self):
        return f'Historial de paciente {self.paciente_id}'


class Diagnostico(models.Model):
    class Estado(models.TextChoices):
        EN_TRATAMIENTO = 'EN_TRATAMIENTO', 'En tratamiento'
        RESUELTO = 'RESUELTO', 'Resuelto'

    paciente = models.ForeignKey('pacientes.Paciente', on_delete=models.CASCADE, related_name='diagnosticos')
    medico = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='diagnosticos')
    codigo_cie10 = CampoCifrado(blank=True)
    diagnostico = CampoCifrado()
    tratamiento = CampoCifrado(blank=True)
    medicamentos = CampoCifrado(blank=True)
    estado = models.CharField(max_length=15, choices=Estado.choices, default=Estado.EN_TRATAMIENTO)

    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'diagnósticos'
        ordering = ['-fecha']

    def __str__(self):
        return f'Diagnóstico {self.pk} - paciente {self.paciente_id}'


class AccesoFicha(models.Model):
    """Bitácora: quién consultó o modificó la ficha de un paciente."""

    class Accion(models.TextChoices):
        CONSULTA = 'CONSULTA', 'Consulta'
        CREACION = 'CREACION', 'Creación'
        DIAGNOSTICO = 'REGISTRO', 'Registro de diagnóstico'
        OBSERVACION = 'OBSERVACION', 'Observación de examen'
        RECETA = 'RECETA', 'Emisión de receta'

    paciente = models.ForeignKey('pacientes.Paciente', on_delete=models.CASCADE, related_name='accesos')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='accesos_fichas')
    accion = models.CharField(max_length=15, choices=Accion.choices)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'accesos a fichas'
        ordering = ['-fecha']

    def __str__(self):
        return f'{self.get_accion_display()} paciente {self.paciente_id} por {self.usuario_id}'

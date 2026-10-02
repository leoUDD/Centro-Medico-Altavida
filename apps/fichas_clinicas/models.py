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
    paciente = models.ForeignKey('pacientes.Paciente', on_delete=models.CASCADE, related_name='diagnosticos')
    medico = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='diagnosticos')
    diagnostico = CampoCifrado()
    tratamiento = CampoCifrado(blank=True)
    medicamentos = CampoCifrado(blank=True)

    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'diagnósticos'
        ordering = ['-fecha']

    def __str__(self):
        return f'Diagnóstico {self.pk} - paciente {self.paciente_id}'

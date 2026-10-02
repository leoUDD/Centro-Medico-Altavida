from django.db import models

from apps.seguridad.campos import CampoCifrado


class ResultadoExamen(models.Model):
    paciente = models.ForeignKey('pacientes.Paciente', on_delete=models.CASCADE, related_name='resultados')
    tipo_examen = models.CharField(max_length=150)
    laboratorio = models.CharField(max_length=150)

    # Cifrado (AES): resultado enviado por el laboratorio externo
    resultado = CampoCifrado()

    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'resultados de exámenes'
        ordering = ['-fecha']

    def __str__(self):
        return f'{self.tipo_examen} - paciente {self.paciente_id}'

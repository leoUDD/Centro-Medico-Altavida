from django.db import models

from apps.seguridad.campos import CampoCifrado


class Prevision(models.Model):
    class Tipo(models.TextChoices):
        FONASA = 'FONASA', 'Fonasa'
        ISAPRE = 'ISAPRE', 'Isapre'

    nombre = models.CharField(max_length=100, unique=True)
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'previsión'
        verbose_name_plural = 'previsiones'

    def __str__(self):
        return self.nombre


class Cobertura(models.Model):
    paciente = models.ForeignKey('pacientes.Paciente', on_delete=models.CASCADE, related_name='coberturas')
    prevision = models.ForeignKey(Prevision, on_delete=models.PROTECT, related_name='coberturas')
    datos_cobertura = CampoCifrado()
    fecha_validacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'coberturas'

    def __str__(self):
        return f'{self.prevision} - paciente {self.paciente_id}'

from django.contrib.auth.models import AbstractUser
from django.db import models


class Usuario(AbstractUser):
    class Rol(models.TextChoices):
        PACIENTE = 'PACIENTE', 'Paciente'
        MEDICO = 'MEDICO', 'Médico'
        ADMINISTRATIVO = 'ADMINISTRATIVO', 'Personal administrativo'

    email = models.EmailField('correo electrónico', unique=True)
    rol = models.CharField(max_length=15, choices=Rol.choices, default=Rol.PACIENTE)
    # Índice ciego del RUT: permite iniciar sesión con RUT sin guardarlo en claro (ver apps.seguridad.indice).
    rut_indice = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)

    @property
    def especialidad(self):
        profesional = getattr(self, 'profesional', None)
        return profesional.especialidad.nombre if profesional else ''

    @property
    def es_paciente(self):
        return self.rol == self.Rol.PACIENTE

    @property
    def es_medico(self):
        return self.rol == self.Rol.MEDICO

    @property
    def es_administrativo(self):
        return self.rol == self.Rol.ADMINISTRATIVO

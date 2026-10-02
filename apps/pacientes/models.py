from django.conf import settings
from django.db import models

from apps.seguridad.campos import CampoCifrado


class Paciente(models.Model):
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='paciente',
    )
    rut = CampoCifrado()
    nombre = CampoCifrado()
    fecha_nacimiento = CampoCifrado()
    sexo = CampoCifrado()
    direccion = CampoCifrado(blank=True)
    peso = CampoCifrado(blank=True)
    estatura = CampoCifrado(blank=True)
    email = CampoCifrado(blank=True)
    telefono = CampoCifrado(blank=True)
    creado = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Paciente {self.pk}'

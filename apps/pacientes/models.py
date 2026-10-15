from datetime import date

from django.conf import settings
from django.db import models

from apps.seguridad.campos import CampoCifrado
from apps.seguridad.indice import indice_rut
from apps.seguridad.rut import formatear_rut


class Paciente(models.Model):
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='paciente',
    )
    rut = CampoCifrado()
    # Índice ciego del RUT (HMAC): búsqueda exacta sin descifrar toda la tabla.
    rut_indice = models.CharField(max_length=64, unique=True, editable=False)
    nombres = CampoCifrado()
    apellidos = CampoCifrado()
    fecha_nacimiento = CampoCifrado()
    sexo = CampoCifrado(blank=True)
    grupo_sanguineo = CampoCifrado(blank=True)
    direccion = CampoCifrado(blank=True)
    comuna = CampoCifrado(blank=True)
    peso = CampoCifrado(blank=True)
    estatura = CampoCifrado(blank=True)
    email = CampoCifrado(blank=True)
    telefono = CampoCifrado(blank=True)

    contacto_emergencia_nombre = CampoCifrado(blank=True)
    contacto_emergencia_parentesco = CampoCifrado(blank=True)
    contacto_emergencia_telefono = CampoCifrado(blank=True)

    consentimiento_datos = models.BooleanField(default=False)
    consentimiento_fecha = models.DateTimeField(null=True, blank=True)
    recordatorios_activos = models.BooleanField(default=False)

    creado = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        self.rut_indice = indice_rut(self.rut)
        super().save(*args, **kwargs)

    def __str__(self):
        return f'Paciente {self.pk}'

    @property
    def nombre_completo(self):
        return f'{self.nombres} {self.apellidos}'.strip()

    @property
    def rut_formateado(self):
        return formatear_rut(self.rut)

    @property
    def rut_oculto(self):
        formateado = self.rut_formateado
        return f'••.•••.{formateado[-5:]}' if len(formateado) > 5 else formateado

    @property
    def telefono_oculto(self):
        return f'+56 9 •••• {self.telefono[-4:]}' if len(self.telefono or '') >= 4 else ''

    @property
    def edad(self):
        try:
            nacimiento = date.fromisoformat(self.fecha_nacimiento)
        except (TypeError, ValueError):
            return None
        hoy = date.today()
        return hoy.year - nacimiento.year - ((hoy.month, hoy.day) < (nacimiento.month, nacimiento.day))

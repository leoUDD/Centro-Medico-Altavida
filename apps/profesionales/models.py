from django.conf import settings
from django.db import models


class Especialidad(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = 'especialidades'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class Profesional(models.Model):
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profesional',
        limit_choices_to={'rol': 'MEDICO'},
    )
    especialidad = models.ForeignKey(Especialidad, on_delete=models.PROTECT, related_name='profesionales')
    titulo = models.CharField(max_length=5, blank=True, help_text='Por ejemplo Dr. o Dra.')
    duracion_minutos = models.PositiveSmallIntegerField('duración de la consulta (min)', default=30)
    ofrece_telemedicina = models.BooleanField(default=True)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = 'profesionales'
        ordering = ['usuario__last_name', 'usuario__first_name']

    @property
    def nombre(self):
        completo = self.usuario.get_full_name() or self.usuario.get_username()
        return f'{self.titulo} {completo}'.strip()

    def __str__(self):
        return f'{self.nombre} ({self.especialidad})'

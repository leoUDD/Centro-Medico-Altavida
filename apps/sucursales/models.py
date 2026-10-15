from django.db import models


class Sucursal(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    direccion = models.CharField(max_length=200, blank=True)
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = 'sucursales'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre

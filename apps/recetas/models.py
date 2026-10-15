import hashlib
import json

from django.conf import settings
from django.db import models

from apps.seguridad.campos import CampoCifrado


class Receta(models.Model):
    class Estado(models.TextChoices):
        BORRADOR = 'BORRADOR', 'Borrador'
        EMITIDA = 'EMITIDA', 'Emitida'

    paciente = models.ForeignKey('pacientes.Paciente', on_delete=models.CASCADE, related_name='recetas')
    medico = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='recetas')
    diagnostico = models.ForeignKey(
        'fichas_clinicas.Diagnostico', on_delete=models.SET_NULL, null=True, blank=True, related_name='recetas',
    )
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.BORRADOR)
    indicaciones = CampoCifrado(blank=True)
    creada = models.DateTimeField(auto_now_add=True)
    emitida_en = models.DateTimeField(null=True, blank=True)
    # Firma electrónica simple: huella SHA-256 del contenido al emitir, para detectar alteraciones.
    firma = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ['-creada']

    def __str__(self):
        return f'Receta {self.folio}'

    @property
    def folio(self):
        return f'R-{self.pk:06d}'

    @property
    def emitida(self):
        return self.estado == self.Estado.EMITIDA

    def contenido_firmable(self):
        return json.dumps({
            'folio': self.folio, 'paciente': self.paciente.rut_indice, 'medico': self.medico_id,
            'diagnostico': self.diagnostico.codigo_cie10 if self.diagnostico else '',
            'emitida_en': self.emitida_en.isoformat() if self.emitida_en else '',
            'indicaciones': self.indicaciones,
            'items': [i.como_dict() for i in self.items.all()],
        }, sort_keys=True, ensure_ascii=False)

    def calcular_firma(self):
        return hashlib.sha256(self.contenido_firmable().encode('utf-8')).hexdigest()

    @property
    def firma_valida(self):
        return self.emitida and self.firma == self.calcular_firma()


class ItemReceta(models.Model):
    class Via(models.TextChoices):
        ORAL = 'Oral', 'Oral'
        TOPICA = 'Tópica', 'Tópica'
        INTRAMUSCULAR = 'Intramuscular', 'Intramuscular'
        INHALATORIA = 'Inhalatoria', 'Inhalatoria'

    receta = models.ForeignKey(Receta, on_delete=models.CASCADE, related_name='items')
    orden = models.PositiveSmallIntegerField(default=1)
    medicamento = CampoCifrado()
    dosis = CampoCifrado()
    frecuencia = CampoCifrado()
    duracion = CampoCifrado()
    via = models.CharField(max_length=15, choices=Via.choices, default=Via.ORAL)

    class Meta:
        ordering = ['orden', 'pk']

    def __str__(self):
        return f'{self.orden}. {self.medicamento}'

    def como_dict(self):
        return {
            'orden': self.orden, 'medicamento': self.medicamento, 'dosis': self.dosis,
            'frecuencia': self.frecuencia, 'duracion': self.duracion, 'via': self.via,
        }

import json
from decimal import Decimal, InvalidOperation

from django.db import models

from apps.seguridad.campos import CampoCifrado


class ResultadoExamen(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = 'PENDIENTE', 'Pendiente'
        DISPONIBLE = 'DISPONIBLE', 'Disponible'

    paciente = models.ForeignKey('pacientes.Paciente', on_delete=models.CASCADE, related_name='resultados')
    tipo_examen = models.CharField(max_length=150)
    laboratorio = models.CharField(max_length=150)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PENDIENTE)
    fecha_toma = models.DateTimeField(null=True, blank=True)
    validado_por = models.CharField(max_length=150, blank=True)
    solicitado_por = models.ForeignKey(
        'usuarios.Usuario', on_delete=models.SET_NULL, null=True, blank=True, related_name='examenes_solicitados',
    )
    fecha_estimada = models.DateField('entrega estimada', null=True, blank=True)

    # Cifrado (AES): resultado enviado por el laboratorio externo. Es una lista JSON de parámetros:
    # [{"nombre": "Colesterol total", "valor": 238, "unidad": "mg/dL", "min": null, "max": 200}, ...]
    resultado = CampoCifrado(blank=True)
    # Cifrado (AES): interpretación del médico, visible en la ficha.
    observacion_medico = CampoCifrado(blank=True)

    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'resultados de exámenes'
        ordering = ['-fecha_toma', '-fecha']

    def __str__(self):
        return f'{self.tipo_examen} - paciente {self.paciente_id}'

    @property
    def parametros(self):
        return parsear_parametros(self.resultado)

    @property
    def fuera_de_rango(self):
        return sum(1 for p in self.parametros if p['estado'] != 'Normal')


def _numero(valor):
    try:
        return Decimal(str(valor))
    except (InvalidOperation, TypeError):
        return None


def _referencia(minimo, maximo):
    if minimo is not None and maximo is not None:
        return f'{minimo:g} – {maximo:g}'
    if maximo is not None:
        return f'< {maximo:g}'
    if minimo is not None:
        return f'> {minimo:g}'
    return '—'


def _esperado(minimo, maximo):
    """Referencia en lenguaje simple para el paciente."""
    if minimo is not None and maximo is not None:
        return f'{minimo:g} a {maximo:g}'
    if maximo is not None:
        return f'menos de {maximo:g}'
    if minimo is not None:
        return f'más de {minimo:g}'
    return '—'


def parsear_parametros(texto):
    """Convierte el JSON del laboratorio en filas listas para mostrar, con estado Alto/Bajo/Normal."""
    try:
        datos = json.loads(texto) if texto else []
    except ValueError:
        return []
    if not isinstance(datos, list):
        return []
    filas = []
    for d in datos:
        if not isinstance(d, dict):
            continue
        valor, minimo, maximo = _numero(d.get('valor')), _numero(d.get('min')), _numero(d.get('max'))
        estado = 'Normal'
        if valor is not None and maximo is not None and valor > maximo:
            estado = 'Alto'
        elif valor is not None and minimo is not None and valor < minimo:
            estado = 'Bajo'
        filas.append({
            'nombre': d.get('nombre', ''), 'valor': d.get('valor', ''), 'unidad': d.get('unidad', ''),
            'referencia': _referencia(minimo, maximo), 'esperado': _esperado(minimo, maximo), 'estado': estado,
        })
    return filas


class TipoExamen(models.Model):
    """Catálogo de exámenes que el paciente puede agendar."""

    nombre = models.CharField(max_length=150, unique=True)
    preparacion = models.CharField(max_length=300, blank=True, help_text='Indicaciones previas para el paciente.')
    ayuno_horas = models.CharField(
        max_length=20, blank=True, help_text='Por ejemplo "8 a 12". Vacío si no requiere ayuno.',
    )
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'tipo de examen'
        verbose_name_plural = 'tipos de examen'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre

    @property
    def requiere_ayuno(self):
        return bool(self.ayuno_horas)


class OrdenExamen(models.Model):
    """Orden médica emitida en Altavida; el paciente la usa al agendar su toma de muestra."""

    paciente = models.ForeignKey('pacientes.Paciente', on_delete=models.CASCADE, related_name='ordenes_examen')
    tipo_examen = models.ForeignKey(TipoExamen, on_delete=models.PROTECT, related_name='ordenes')
    medico = models.ForeignKey('usuarios.Usuario', on_delete=models.PROTECT, related_name='ordenes_examen')
    fecha = models.DateTimeField(auto_now_add=True)
    utilizada = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'orden de examen'
        verbose_name_plural = 'órdenes de examen'
        ordering = ['-fecha']

    def __str__(self):
        return f'Orden {self.pk}: {self.tipo_examen} (paciente {self.paciente_id})'

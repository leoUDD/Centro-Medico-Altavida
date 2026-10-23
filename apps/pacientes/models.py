"""Paciente seudonimizado.

- `Paciente` guarda solo el código (seudónimo) y los datos clínicos de contexto. No contiene nada que identifique.
- `IdentidadPaciente` es el diccionario de equivalencias: une el código con la persona real. Sus datos se cifran con
  la llave de *identidad*, distinta de la llave clínica, y solo se leen desde las vistas con el permiso `ver_identidad`.
Las tablas clínicas (diagnósticos, recetas, resultados, citas…) apuntan al paciente por su clave, nunca a la identidad.
"""
import secrets
from datetime import date

from django.conf import settings
from django.db import models, transaction

from apps.seguridad.campos import CampoCifrado
from apps.seguridad.indice import indice_rut
from apps.seguridad.rut import formatear_rut

CAMPOS_IDENTIDAD = (
    'rut', 'nombres', 'apellidos', 'fecha_nacimiento', 'email', 'telefono',
    'contacto_emergencia_nombre', 'contacto_emergencia_parentesco', 'contacto_emergencia_telefono',
)


def generar_codigo():
    """Seudónimo aleatorio, sin relación con ningún dato de la persona."""
    return 'P' + secrets.token_urlsafe(9)


class PacienteManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().select_related('identidad')

    def create(self, **kwargs):
        """Crea el paciente y su identidad; acepta los datos identificadores como argumentos para mayor comodidad."""
        datos = {campo: kwargs.pop(campo) for campo in CAMPOS_IDENTIDAD if campo in kwargs}
        with transaction.atomic():
            paciente = super().create(**kwargs)
            IdentidadPaciente.objects.create(paciente=paciente, **datos)
        return paciente


class Paciente(models.Model):
    codigo = models.CharField(max_length=24, unique=True, default=generar_codigo, editable=False)
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='paciente',
    )
    # Médico que abrió la ficha: da relación terapéutica y permite ver al paciente (ver apps/pacientes/acceso.py).
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='pacientes_creados',
    )

    # Datos clínicos de contexto, todos opcionales (minimización). Llave clínica.
    sexo = CampoCifrado(blank=True)
    grupo_sanguineo = CampoCifrado(blank=True)
    peso = CampoCifrado(blank=True)
    estatura = CampoCifrado(blank=True)

    consentimiento_datos = models.BooleanField(default=False)
    consentimiento_fecha = models.DateTimeField(null=True, blank=True)
    recordatorios_activos = models.BooleanField(default=False)

    creado = models.DateTimeField(auto_now_add=True)

    objects = PacienteManager()

    def __str__(self):
        return f'Paciente {self.codigo}'

    def _identidad(self):
        try:
            return self.identidad
        except IdentidadPaciente.DoesNotExist:
            return None

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

    def actualizar_identidad(self, **campos):
        identidad = self.identidad
        for campo, valor in campos.items():
            if campo not in CAMPOS_IDENTIDAD:
                raise AttributeError(campo)
            setattr(identidad, campo, valor)
        identidad.save()


def _propiedad_identidad(campo):
    def leer(self):
        identidad = self._identidad()
        return getattr(identidad, campo) if identidad else ''
    return property(leer)


for _campo in CAMPOS_IDENTIDAD:
    setattr(Paciente, _campo, _propiedad_identidad(_campo))


class IdentidadPaciente(models.Model):
    """Diccionario de equivalencias: código del paciente ↔ persona real. Cifrado con la llave de identidad."""

    paciente = models.OneToOneField(Paciente, on_delete=models.CASCADE, related_name='identidad')
    rut = CampoCifrado(proposito='identidad')
    # Índice ciego (HMAC) del RUT: búsqueda exacta sin descifrar toda la tabla.
    rut_indice = models.CharField(max_length=64, unique=True, editable=False)
    nombres = CampoCifrado(proposito='identidad')
    apellidos = CampoCifrado(proposito='identidad')
    fecha_nacimiento = CampoCifrado(proposito='identidad', blank=True)
    email = CampoCifrado(proposito='identidad', blank=True)
    telefono = CampoCifrado(proposito='identidad', blank=True)
    contacto_emergencia_nombre = CampoCifrado(proposito='identidad', blank=True)
    contacto_emergencia_parentesco = CampoCifrado(proposito='identidad', blank=True)
    contacto_emergencia_telefono = CampoCifrado(proposito='identidad', blank=True)

    class Meta:
        verbose_name = 'identidad de paciente'
        verbose_name_plural = 'identidades de pacientes'

    def save(self, *args, **kwargs):
        self.rut_indice = indice_rut(self.rut)
        super().save(*args, **kwargs)

    def __str__(self):
        return f'Identidad de {self.paciente.codigo}'


class AccesoIdentidad(models.Model):
    """Bitácora de re-identificación: quién vio datos identificadores y con qué finalidad."""

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='accesos_identidad')
    finalidad = models.CharField(max_length=80)
    cantidad = models.PositiveIntegerField(default=1)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha']
        verbose_name = 'acceso a identidad'
        verbose_name_plural = 'accesos a identidad'

    def __str__(self):
        return f'{self.finalidad} ({self.cantidad}) por {self.usuario_id}'


class AccesoEmergencia(models.Model):
    """Acceso excepcional de un médico a un paciente sin relación terapéutica: exige motivo y vence solo."""

    medico = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='accesos_emergencia')
    paciente = models.ForeignKey(Paciente, on_delete=models.CASCADE, related_name='accesos_emergencia')
    motivo = CampoCifrado()
    inicio = models.DateTimeField(auto_now_add=True)
    vence = models.DateTimeField()

    class Meta:
        ordering = ['-inicio']
        verbose_name = 'acceso de emergencia'
        verbose_name_plural = 'accesos de emergencia'

    def __str__(self):
        return f'Emergencia: médico {self.medico_id} → {self.paciente.codigo}'

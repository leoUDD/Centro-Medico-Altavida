from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models

from . import roles


class UsuarioManager(UserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        # Quien se crea con createsuperuser es administrador del sistema: gestiona cuentas y catálogos, no ve datos clínicos.
        extra_fields.setdefault('rol', Usuario.Rol.ADMIN_SISTEMA)
        return super().create_superuser(username, email, password, **extra_fields)


class Usuario(AbstractUser):
    class Rol(models.TextChoices):
        PACIENTE = 'PACIENTE', 'Paciente'
        MEDICO = 'MEDICO', 'Médico'
        ADMINISTRATIVO = 'ADMINISTRATIVO', 'Personal administrativo'
        ADMIN_SISTEMA = 'ADMIN_SISTEMA', 'Administrador del sistema'

    # Del personal (médicos, administrativos, administradores) el correo es dato laboral y va en claro.
    # De los pacientes no se guarda: su correo vive cifrado en IdentidadPaciente y aquí solo queda `correo_indice`.
    email = models.EmailField('correo electrónico', unique=True, null=True, blank=True)
    rol = models.CharField(max_length=15, choices=Rol.choices, default=Rol.PACIENTE)
    # Índices ciegos (HMAC): permiten iniciar sesión con RUT o correo sin guardarlos en claro.
    rut_indice = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)
    correo_indice = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)

    objects = UsuarioManager()

    def save(self, *args, **kwargs):
        if not self.email:
            self.email = None  # evita que varias cuentas sin correo choquen en la restricción de unicidad
        super().save(*args, **kwargs)
        roles.sincronizar_grupo(self)

    @property
    def nombre_visible(self):
        """Nombre para mostrar en pantalla. En pacientes sale de su identidad cifrada, no de la cuenta."""
        if self.rol == self.Rol.PACIENTE:
            paciente = getattr(self, 'paciente', None)
            return paciente.nombres.split()[0] if paciente and paciente.nombres else 'Paciente'
        return self.get_full_name() or self.get_username()

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

    @property
    def es_admin_sistema(self):
        return self.rol == self.Rol.ADMIN_SISTEMA

    def has_perm(self, perm, obj=None):
        # El administrador del sistema es superusuario de Django, pero no debe leer datos clínicos ni de identidad.
        if self.rol == self.Rol.ADMIN_SISTEMA and roles.reservado_para_clinica(perm):
            return False
        return super().has_perm(perm, obj)

    def has_module_perms(self, app_label):
        if self.rol == self.Rol.ADMIN_SISTEMA and app_label in roles.APPS_CLINICAS:
            return False
        return super().has_module_perms(app_label)


class Permisos(models.Model):
    """Ancla de los permisos propios del sistema (no crea tabla): ver apps/usuarios/roles.py."""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = roles.PERMISOS

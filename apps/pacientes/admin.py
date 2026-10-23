from django.contrib import admin

from .models import AccesoEmergencia, AccesoIdentidad, Paciente


@admin.register(Paciente)
class PacienteAdmin(admin.ModelAdmin):
    """Solo el código y datos de contexto: la identidad no se edita aquí (se corrige por las pantallas con permiso)."""

    list_display = ('codigo', 'creado')
    readonly_fields = ('codigo',)


class SoloLecturaAdmin(admin.ModelAdmin):
    """Bitácoras: se consultan, nunca se editan ni se borran desde el sitio de administración."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AccesoIdentidad)
class AccesoIdentidadAdmin(SoloLecturaAdmin):
    list_display = ('fecha', 'usuario', 'finalidad', 'cantidad')


@admin.register(AccesoEmergencia)
class AccesoEmergenciaAdmin(SoloLecturaAdmin):
    list_display = ('inicio', 'medico', 'paciente', 'vence')
    exclude = ('motivo',)

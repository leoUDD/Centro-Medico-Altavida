from django.contrib import admin

from .models import AccesoFicha, Diagnostico, HistorialMedico

admin.site.register(HistorialMedico)
admin.site.register(Diagnostico)


class SoloLecturaAdmin(admin.ModelAdmin):
    """Bitácoras: se consultan, nunca se editan ni se borran desde el sitio de administración."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AccesoFicha)
class AccesoFichaAdmin(SoloLecturaAdmin):
    list_display = ('fecha', 'usuario', 'accion', 'paciente')
    list_filter = ('accion',)

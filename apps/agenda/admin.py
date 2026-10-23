from django.contrib import admin

from .models import Cita, HorarioAtencion, HorarioLaboratorio

admin.site.register(HorarioAtencion)
admin.site.register(HorarioLaboratorio)


@admin.register(Cita)
class CitaAdmin(admin.ModelAdmin):
    list_display = ('inicio', 'tipo', 'estado', 'profesional', 'sucursal')
    list_filter = ('tipo', 'estado', 'sucursal')
    exclude = ('orden_externa', 'motivo')  # el motivo de consulta solo lo ve el profesional

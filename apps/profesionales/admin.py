from django.contrib import admin

from .models import Especialidad, Profesional

admin.site.register(Especialidad)


@admin.register(Profesional)
class ProfesionalAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'especialidad', 'duracion_minutos', 'ofrece_telemedicina', 'activo')
    list_filter = ('especialidad', 'activo')

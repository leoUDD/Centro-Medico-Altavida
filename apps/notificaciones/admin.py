from django.contrib import admin

from .models import EjecucionRecordatorios, Notificacion, PreferenciasNotificacion, Recordatorio, ReglaRecordatorio


@admin.register(Notificacion)
class NotificacionAdmin(admin.ModelAdmin):
    list_display = ('creada', 'tipo', 'titulo', 'leida')
    exclude = ('detalle',)  # el detalle (fecha, profesional, lugar) está cifrado y no se muestra aquí


admin.site.register(PreferenciasNotificacion)
admin.site.register(ReglaRecordatorio)
admin.site.register(Recordatorio)
admin.site.register(EjecucionRecordatorios)

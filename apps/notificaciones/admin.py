from django.contrib import admin

from .models import EjecucionRecordatorios, Notificacion, PreferenciasNotificacion, Recordatorio, ReglaRecordatorio

admin.site.register(Notificacion)
admin.site.register(PreferenciasNotificacion)
admin.site.register(ReglaRecordatorio)
admin.site.register(Recordatorio)
admin.site.register(EjecucionRecordatorios)

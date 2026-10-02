from django.contrib import admin

from .models import Diagnostico, HistorialMedico

admin.site.register(HistorialMedico)
admin.site.register(Diagnostico)

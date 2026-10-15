from django.contrib import admin

from .models import ResultadoExamen

admin.site.register(ResultadoExamen)
from .models import OrdenExamen, TipoExamen

admin.site.register(TipoExamen)
admin.site.register(OrdenExamen)

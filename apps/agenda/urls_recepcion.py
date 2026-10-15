from django.urls import path

from . import recepcion

app_name = 'recepcion'

urlpatterns = [
    path('', recepcion.dashboard, name='dashboard'),
    path('citas/<int:pk>/confirmar/', recepcion.confirmar_cita, name='confirmar'),
    path('citas/<int:pk>/cancelar/', recepcion.cancelar_cita, name='cancelar'),
    path('recordatorios/generar/', recepcion.generar_ahora, name='generar'),
    path('recordatorios/reglas/', recepcion.guardar_reglas, name='reglas'),
    path('recordatorios/<int:pk>/reintentar/', recepcion.reintentar, name='reintentar'),
    path('pacientes/<int:pk>/contacto/', recepcion.editar_contacto, name='contacto'),
]

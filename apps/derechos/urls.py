from django.urls import path

from . import views

app_name = 'derechos'

urlpatterns = [
    # Titular (portal del paciente)
    path('paciente/derechos/', views.mis_solicitudes, name='mis'),
    path('paciente/derechos/nueva/', views.nueva, name='nueva'),
    path('paciente/derechos/<str:codigo>/', views.detalle, name='detalle'),
    path('paciente/derechos/<str:codigo>/verificar/', views.verificar, name='verificar'),
    path('paciente/derechos/<str:codigo>/reenviar-codigo/', views.reenviar_codigo, name='reenviar'),
    path('paciente/derechos/<str:codigo>/descargar/', views.descargar, name='descargar'),
    # Encargado de privacidad
    path('privacidad/derechos/', views.bandeja, name='bandeja'),
    path('privacidad/derechos/<str:codigo>/', views.gestionar, name='gestionar'),
    path('privacidad/derechos/<str:codigo>/resolver/', views.resolver, name='resolver'),
    path('privacidad/derechos/<str:codigo>/cerrar/', views.cerrar, name='cerrar'),
]

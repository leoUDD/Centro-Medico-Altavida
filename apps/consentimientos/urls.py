from django.urls import path

from . import views

app_name = 'consentimientos'

urlpatterns = [
    path('aviso-de-privacidad/', views.aviso, name='aviso'),
    path('paciente/consentimientos/', views.mis_consentimientos, name='mis'),
    path('paciente/consentimientos/<str:codigo>/<str:accion>/', views.cambiar, name='cambiar'),
    path('administracion/representantes/', views.representaciones, name='representaciones'),
    path('administracion/representantes/registrar/', views.registrar_representacion, name='registrar_representacion'),
    path('administracion/representantes/<int:pk>/terminar/', views.terminar_representacion, name='terminar_representacion'),
    path('privacidad/consentimientos/', views.panel, name='panel'),
]

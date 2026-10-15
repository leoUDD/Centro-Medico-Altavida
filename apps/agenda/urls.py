from django.urls import path

from . import views

app_name = 'agenda'

urlpatterns = [
    path('consulta/', views.consulta, name='consulta'),
    path('examen/', views.examen, name='examen'),
    path('citas/<int:pk>/confirmar/', views.confirmar, name='confirmar'),
    path('citas/<int:pk>/cancelar/', views.cancelar, name='cancelar'),
]

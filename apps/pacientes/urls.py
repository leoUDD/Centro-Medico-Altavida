from django.urls import path

from . import views

app_name = 'pacientes'

urlpatterns = [
    path('resultados/', views.resultados, name='resultados'),
]

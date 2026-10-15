from django.urls import path

from . import views

app_name = 'recetas'

urlpatterns = [
    path('paciente/<int:paciente_pk>/nueva/', views.nueva, name='nueva'),
    path('<int:pk>/editar/', views.editar, name='editar'),
    path('<int:pk>/', views.detalle, name='detalle'),
]

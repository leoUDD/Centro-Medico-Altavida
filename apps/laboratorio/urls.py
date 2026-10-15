from django.urls import path

from . import views

app_name = 'laboratorio'

urlpatterns = [
    path('<int:pk>/', views.examenes, name='examenes'),
    path('resultado/<int:pk>/observacion/', views.guardar_observacion, name='observacion'),
]

from django.urls import path

from . import views

app_name = 'fichas'

urlpatterns = [
    path('', views.buscar, name='buscar'),
    path('nueva/', views.nueva, name='nueva'),
    path('<int:pk>/', views.detalle, name='detalle'),
    path('<int:pk>/diagnosticos/', views.historial, name='historial'),
    path('<int:pk>/diagnosticos/nuevo/', views.nuevo_diagnostico, name='nuevo_diagnostico'),
]

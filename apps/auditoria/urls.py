from django.urls import path

from . import views

app_name = 'auditoria'

urlpatterns = [
    path('', views.eventos, name='eventos'),
    path('verificar/', views.verificar, name='verificar'),
]

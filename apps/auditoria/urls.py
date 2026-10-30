from django.urls import path

from . import views, views_alertas

app_name = 'auditoria'

urlpatterns = [
    path('', views.eventos, name='eventos'),
    path('verificar/', views.verificar, name='verificar'),
    path('alertas/', views_alertas.lista, name='alertas'),
    path('alertas/detectar/', views_alertas.detectar, name='detectar'),
    path('alertas/<int:pk>/', views_alertas.detalle, name='alerta'),
    path('alertas/<int:pk>/estado/', views_alertas.cambiar_estado, name='alerta_estado'),
    path('alertas/<int:pk>/evidencia/', views_alertas.evidencia, name='alerta_evidencia'),
    path('alertas/<int:pk>/contener/', views_alertas.contener, name='alerta_contener'),
    path('contencion/', views_alertas.modo, name='modo'),
]

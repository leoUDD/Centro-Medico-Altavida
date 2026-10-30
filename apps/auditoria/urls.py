from django.urls import path

from . import views, views_alertas, views_incidentes

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
    path('incidentes/', views_incidentes.lista, name='incidentes'),
    path('incidentes/abrir/', views_incidentes.abrir, name='incidente_abrir'),
    path('incidentes/<str:codigo>/', views_incidentes.detalle, name='incidente'),
    path('incidentes/<str:codigo>/clasificar/', views_incidentes.clasificar, name='incidente_clasificar'),
    path('incidentes/<str:codigo>/avanzar/', views_incidentes.avanzar, name='incidente_avanzar'),
    path('incidentes/<str:codigo>/proponer/', views_incidentes.proponer, name='incidente_proponer'),
    path('incidentes/<str:codigo>/autorizar/', views_incidentes.autorizar_notificacion, name='incidente_autorizar'),
    path('incidentes/<str:codigo>/notificada/', views_incidentes.notificada, name='incidente_notificada'),
    path('incidentes/<str:codigo>/sin-notificar/', views_incidentes.sin_notificar, name='incidente_sin_notificar'),
    path('incidentes/<str:codigo>/lecciones/', views_incidentes.lecciones, name='incidente_lecciones'),
    path('incidentes/<str:codigo>/cerrar/', views_incidentes.cerrar, name='incidente_cerrar'),
]

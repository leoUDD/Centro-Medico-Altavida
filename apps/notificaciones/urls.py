from django.urls import path

from . import views

app_name = 'notificaciones'

urlpatterns = [
    path('', views.lista, name='lista'),
    path('marcar-todas/', views.marcar_todas, name='marcar_todas'),
    path('preferencias/', views.guardar_preferencias, name='preferencias'),
]

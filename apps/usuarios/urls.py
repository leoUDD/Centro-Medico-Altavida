from django.urls import path

from . import views

urlpatterns = [
    path('', views.inicio, name='inicio'),
    path('ingresar/', views.login_vista, name='login'),
    path('salir/', views.logout_vista, name='logout'),
    path('registro/', views.registro_vista, name='registro'),
]

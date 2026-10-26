"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('medico/fichas/', include('apps.fichas_clinicas.urls')),
    path('medico/examenes/', include('apps.laboratorio.urls')),
    path('medico/recetas/', include('apps.recetas.urls')),
    path('paciente/agendar/', include('apps.agenda.urls')),
    path('paciente/', include('apps.pacientes.urls')),
    path('paciente/notificaciones/', include('apps.notificaciones.urls')),
    path('administracion/', include('apps.agenda.urls_recepcion')),
    path('', include('apps.usuarios.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler403 = 'apps.seguridad.errores.error_403'
handler404 = 'apps.seguridad.errores.error_404'
handler500 = 'apps.seguridad.errores.error_500'

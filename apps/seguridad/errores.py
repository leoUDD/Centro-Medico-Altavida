"""Páginas de error genéricas: nunca muestran datos, rutas ni detalles de la excepción."""
from django.shortcuts import render

from apps.auditoria import servicio as auditoria
from apps.auditoria.models import Operacion, Resultado

MENSAJES = {
    403: ('Acceso denegado', 'No tienes permiso para ver esta página.'),
    404: ('Página no encontrada', 'La página que buscas no existe.'),
    500: ('Error del servidor', 'Ocurrió un problema. Inténtalo de nuevo más tarde.'),
}


def _error(request, codigo):
    titulo, mensaje = MENSAJES[codigo]
    return render(request, 'errores/error.html', {'codigo': codigo, 'titulo': titulo, 'mensaje': mensaje}, status=codigo)


def error_403(request, exception=None):
    # Se registra el nombre de la vista (nunca la ruta con ids) y quién intentó entrar.
    vista = request.resolver_match.view_name if getattr(request, 'resolver_match', None) else ''
    auditoria.registrar(Operacion.ACCESO_DENEGADO, 'vista', vista, Resultado.DENEGADO, peticion=request)
    return _error(request, 403)


def error_404(request, exception=None):
    return _error(request, 404)


def error_500(request):
    return _error(request, 500)

"""Páginas de error genéricas: nunca muestran datos, rutas ni detalles de la excepción."""
from django.shortcuts import render

MENSAJES = {
    403: ('Acceso denegado', 'No tienes permiso para ver esta página.'),
    404: ('Página no encontrada', 'La página que buscas no existe.'),
    500: ('Error del servidor', 'Ocurrió un problema. Inténtalo de nuevo más tarde.'),
}


def _error(request, codigo):
    titulo, mensaje = MENSAJES[codigo]
    return render(request, 'errores/error.html', {'codigo': codigo, 'titulo': titulo, 'mensaje': mensaje}, status=codigo)


def error_403(request, exception=None):
    return _error(request, 403)


def error_404(request, exception=None):
    return _error(request, 404)


def error_500(request):
    return _error(request, 500)

from . import contexto


class ContextoAuditoriaMiddleware:
    """Deja la petición accesible para el registro de auditoría mientras se atiende (ver contexto.py)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = contexto.fijar(request)
        try:
            return self.get_response(request)
        finally:
            contexto.restablecer(token)


class ModoSistemaMiddleware:
    """Aplica el modo de contención: en SOLO_LECTURA bloquea los cambios y en BLOQUEADO deja entrar solo a seguridad.

    El inicio y cierre de sesión siempre están permitidos para que el personal de seguridad pueda entrar a revertirlo.
    """

    METODOS_SEGUROS = ('GET', 'HEAD', 'OPTIONS')
    RUTAS_LIBRES = ('/ingresar/', '/salir/', '/static/')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from .contencion import ROLES_DE_SEGURIDAD, modo_actual
        from .models import ModoSistema
        modo = modo_actual()
        if modo != ModoSistema.NORMAL and not request.path.startswith(self.RUTAS_LIBRES):
            usuario = getattr(request, 'user', None)
            personal_de_seguridad = usuario is not None and usuario.is_authenticated and usuario.rol in ROLES_DE_SEGURIDAD
            bloqueada = modo == ModoSistema.BLOQUEADO or request.method not in self.METODOS_SEGUROS
            if bloqueada and not personal_de_seguridad:
                from django.shortcuts import render
                return render(request, 'errores/contencion.html', {'modo': modo}, status=503)
        return self.get_response(request)

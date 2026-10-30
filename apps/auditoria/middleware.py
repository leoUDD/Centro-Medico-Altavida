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

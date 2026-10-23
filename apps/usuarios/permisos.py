from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def permiso_requerido(*permisos):
    """Exige sesión iniciada y todos los permisos indicados (códigos de la app "usuarios", ver roles.py)."""
    completos = [f'usuarios.{p}' for p in permisos]

    def decorador(vista):
        @wraps(vista)
        @login_required
        def envoltura(request, *args, **kwargs):
            if not request.user.has_perms(completos):
                raise PermissionDenied
            return vista(request, *args, **kwargs)
        return envoltura
    return decorador

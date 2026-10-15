from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

from apps.seguridad.indice import indice_rut
from apps.seguridad.rut import rut_valido


class CorreoORutBackend(ModelBackend):
    """Inicia sesión con correo electrónico o con RUT (búsqueda por índice ciego)."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        Usuario = get_user_model()
        if not username or password is None:
            return None
        username = username.strip()
        if '@' in username:
            filtro = {'email__iexact': username}
        elif rut_valido(username):
            filtro = {'rut_indice': indice_rut(username)}
        else:
            # Cuentas internas (p. ej. creadas por la administración) pueden entrar con su nombre de usuario.
            filtro = {'username': username}
        try:
            usuario = Usuario.objects.get(**filtro)
        except Usuario.DoesNotExist:
            Usuario().set_password(password)  # iguala el tiempo de respuesta
            return None
        if usuario.check_password(password) and self.user_can_authenticate(usuario):
            return usuario
        return None

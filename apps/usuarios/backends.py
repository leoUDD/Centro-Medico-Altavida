from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q

from apps.seguridad.indice import indice_correo, indice_rut
from apps.seguridad.rut import rut_valido


class CorreoORutBackend(ModelBackend):
    """Inicia sesión con correo o RUT.

    Los pacientes no guardan correo ni RUT en claro en su cuenta: se buscan por índice ciego (HMAC). El personal
    (médicos, administrativos, administradores) entra con su correo laboral o su nombre de usuario.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        Usuario = get_user_model()
        if not username or password is None:
            return None
        username = username.strip()
        if '@' in username:
            filtro = Q(email__iexact=username) | Q(correo_indice=indice_correo(username))
        elif rut_valido(username):
            filtro = Q(rut_indice=indice_rut(username))
        else:
            filtro = Q(username=username)
        usuario = Usuario.objects.filter(filtro).first()
        if usuario is None:
            Usuario().set_password(password)  # iguala el tiempo de respuesta
            return None
        if usuario.check_password(password) and self.user_can_authenticate(usuario):
            return usuario
        return None

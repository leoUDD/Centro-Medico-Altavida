from .models import Notificacion


def sin_leer(request):
    """Cantidad de avisos sin leer, para el distintivo del menú del paciente."""
    usuario = request.user
    if not usuario.is_authenticated or not usuario.es_paciente:
        return {}
    return {'notificaciones_sin_leer': Notificacion.objects.filter(paciente__usuario=usuario, leida=False).count()}

"""Control de acceso por paciente: relación terapéutica o acceso de emergencia (ver apps/pacientes/acceso.py)."""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect

from apps.pacientes import acceso
from apps.pacientes.models import Paciente


def autorizar_paciente(request, pk):
    """Devuelve (paciente, None) si el usuario puede ver al paciente; si no, (None, redirección al acceso de emergencia)."""
    paciente = get_object_or_404(Paciente, pk=pk)
    if acceso.tipo_de_acceso(request.user, paciente):
        return paciente, None
    messages.error(
        request,
        'No tienes relación con este paciente. Si es una urgencia, puedes abrir un acceso de emergencia: queda registrado.',
    )
    return None, redirect('fichas:emergencia', pk=pk)

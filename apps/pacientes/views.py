from django.shortcuts import get_object_or_404, render

from apps.laboratorio.models import ResultadoExamen
from apps.usuarios.permisos import permiso_requerido

from .models import Paciente

solo_pacientes = permiso_requerido('portal_paciente')


def paciente_de(request):
    return get_object_or_404(Paciente, usuario=request.user)


@solo_pacientes
def resultados(request):
    paciente = paciente_de(request)
    examenes = list(paciente.resultados.select_related('solicitado_por'))
    disponibles = [r for r in examenes if r.estado == ResultadoExamen.Estado.DISPONIBLE]
    seleccionado = next((r for r in disponibles if str(r.pk) == request.GET.get('e')), disponibles[0] if disponibles else None)
    return render(request, 'portal_paciente/resultados.html', {
        'seccion': 'resultados',
        'seleccionado': seleccionado,
        'parametros': seleccionado.parametros if seleccionado else [],
        'otros': [r for r in examenes if r != seleccionado],
        'hay_examenes': bool(examenes),
    })

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.fichas_clinicas.bitacora import registrar_acceso
from apps.fichas_clinicas.models import AccesoFicha
from apps.pacientes.models import Paciente
from apps.usuarios.models import Usuario
from apps.usuarios.permisos import rol_requerido

from .models import ResultadoExamen

solo_medicos = rol_requerido(Usuario.Rol.MEDICO)


@solo_medicos
def examenes(request, pk):
    paciente = get_object_or_404(Paciente, pk=pk)
    registrar_acceso(paciente, request.user, AccesoFicha.Accion.CONSULTA)
    todos = list(paciente.resultados.all())
    filtro = request.GET.get('estado', '')
    lista = [r for r in todos if not filtro or r.estado == filtro]
    seleccionado = next((r for r in lista if str(r.pk) == request.GET.get('e')), lista[0] if lista else None)
    return render(request, 'gestion_interna/examenes/resultados.html', {
        'seccion': 'examenes',
        'paciente': paciente,
        'historial': getattr(paciente, 'historial', None),
        'cobertura': paciente.coberturas.select_related('prevision').first(),
        'lista': lista,
        'seleccionado': seleccionado,
        'parametros': seleccionado.parametros if seleccionado else [],
        'filtro': filtro,
        'total': len(todos),
        'disponibles': sum(1 for r in todos if r.estado == ResultadoExamen.Estado.DISPONIBLE),
        'pendientes': sum(1 for r in todos if r.estado == ResultadoExamen.Estado.PENDIENTE),
    })


@solo_medicos
@require_POST
def guardar_observacion(request, pk):
    resultado = get_object_or_404(ResultadoExamen, pk=pk)
    resultado.observacion_medico = request.POST.get('observacion', '').strip()[:2000]
    resultado.save(update_fields=['observacion_medico'])
    registrar_acceso(resultado.paciente, request.user, AccesoFicha.Accion.OBSERVACION)
    messages.success(request, 'Observación guardada en la ficha.')
    return redirect(f"{reverse('laboratorio:examenes', args=[resultado.paciente_id])}?e={resultado.pk}")

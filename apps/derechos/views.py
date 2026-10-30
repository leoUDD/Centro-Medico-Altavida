import json

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST

from apps.pacientes.models import Paciente
from apps.pacientes.views import paciente_de, solo_pacientes
from apps.usuarios.permisos import permiso_requerido

from . import servicio
from .models import SolicitudDerecho

gestionar_derechos = permiso_requerido('gestionar_derechos')
Estado = SolicitudDerecho.Estado


def _propia(request, codigo):
    """Solo ve una solicitud quien la hizo; para cualquier otra persona es como si no existiera."""
    return get_object_or_404(SolicitudDerecho, codigo=codigo, solicitante=paciente_de(request))


@solo_pacientes
def mis_solicitudes(request):
    yo = paciente_de(request)
    return render(request, 'derechos/mis_solicitudes.html', {
        'seccion': 'derechos', 'solicitudes': SolicitudDerecho.objects.filter(solicitante=yo).select_related('paciente'),
        'bloqueado': yo.datos_bloqueados_desde,
    })


@solo_pacientes
def nueva(request):
    yo = paciente_de(request)
    contexto = {
        'seccion': 'derechos', 'tipos': SolicitudDerecho.Tipo.choices, 'campos': SolicitudDerecho.Campo.choices,
        'representados': [r.menor for r in yo.representados.select_related('menor') if r.vigente],
    }
    if request.method == 'POST':
        titular = yo
        if request.POST.get('paciente') and request.POST['paciente'] != yo.codigo:
            titular = get_object_or_404(Paciente, codigo=request.POST['paciente'])
        try:
            solicitud = servicio.crear(
                yo, titular, request.POST.get('tipo', ''), request.user,
                campo=request.POST.get('campo', ''), valor=request.POST.get('valor', ''),
            )
        except servicio.DerechosError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, 'Recibimos tu solicitud. Ahora debemos verificar que eres tú.')
            return redirect('derechos:detalle', codigo=solicitud.codigo)
    return render(request, 'derechos/nueva.html', contexto)


@solo_pacientes
def detalle(request, codigo):
    solicitud = _propia(request, codigo)
    return render(request, 'derechos/detalle.html', {
        'seccion': 'derechos', 's': solicitud, 'historial': solicitud.historial.all(),
        'puede_descargar': servicio.puede_descargar(solicitud), 'Estado': Estado,
    })


@solo_pacientes
@require_POST
@sensitive_post_parameters('clave', 'codigo')
def verificar(request, codigo):
    solicitud = _propia(request, codigo)
    try:
        servicio.verificar(
            solicitud, request.user, request.user.check_password(request.POST.get('clave', '')),
            request.POST.get('codigo', ''),
        )
    except servicio.DerechosError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, 'Identidad verificada. Tu solicitud pasó a evaluación.')
    return redirect('derechos:detalle', codigo=codigo)


@solo_pacientes
@require_POST
def reenviar_codigo(request, codigo):
    try:
        servicio.enviar_codigo(_propia(request, codigo), request.user)
        messages.success(request, 'Te enviamos un código nuevo a tu correo.')
    except servicio.DerechosError as error:
        messages.error(request, str(error))
    return redirect('derechos:detalle', codigo=codigo)


@solo_pacientes
@require_POST
def descargar(request, codigo):
    solicitud = _propia(request, codigo)
    try:
        datos = servicio.registrar_descarga(solicitud, request.user)
    except servicio.DerechosError as error:
        messages.error(request, str(error))
        return redirect('derechos:detalle', codigo=codigo)
    respuesta = HttpResponse(json.dumps(datos, ensure_ascii=False, indent=2), content_type='application/json; charset=utf-8')
    respuesta['Content-Disposition'] = f'attachment; filename="mis-datos-{solicitud.codigo}.json"'
    respuesta['Cache-Control'] = 'no-store'
    return respuesta


# ---------------------------------------------------------- Encargado de privacidad

@gestionar_derechos
def bandeja(request):
    abiertas = SolicitudDerecho.objects.exclude(estado=Estado.CERRADA).select_related('paciente').order_by('plazo_hasta')
    cerradas = SolicitudDerecho.objects.filter(estado=Estado.CERRADA).select_related('paciente')[:20]
    return render(request, 'derechos/bandeja.html', {'seccion': 'derechos', 'abiertas': abiertas, 'cerradas': cerradas})


@gestionar_derechos
def gestionar(request, codigo):
    solicitud = get_object_or_404(SolicitudDerecho.objects.select_related('paciente'), codigo=codigo)
    return render(request, 'derechos/gestionar.html', {
        'seccion': 'derechos', 's': solicitud, 'historial': solicitud.historial.all(), 'Estado': Estado,
        'resoluciones': SolicitudDerecho.Resolucion.choices, 'fundamentos': SolicitudDerecho.Fundamento.choices,
        'conserva': servicio.tiene_datos_clinicos(solicitud.paciente),
    })


@gestionar_derechos
@require_POST
def resolver(request, codigo):
    solicitud = get_object_or_404(SolicitudDerecho, codigo=codigo)
    try:
        servicio.resolver(solicitud, request.user, request.POST.get('resolucion', ''),
                          request.POST.get('fundamento', ''), request.POST.get('respuesta', ''))
        messages.success(request, 'Solicitud resuelta.')
    except servicio.DerechosError as error:
        messages.error(request, str(error))
    return redirect('derechos:gestionar', codigo=codigo)


@gestionar_derechos
@require_POST
def cerrar(request, codigo):
    solicitud = get_object_or_404(SolicitudDerecho, codigo=codigo)
    try:
        servicio.cerrar(solicitud, request.user)
        messages.success(request, 'Solicitud cerrada.')
    except servicio.DerechosError as error:
        messages.error(request, str(error))
    return redirect('derechos:bandeja')

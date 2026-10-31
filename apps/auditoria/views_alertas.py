"""Gestión de alertas y acciones de contención. Permisos separados: revisar alertas, ver evidencia y contener."""
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.usuarios.permisos import permiso_requerido

from . import alertas as motor
from . import contencion
from .models import AlertaSeguridad, EstadoAlerta, EventoAuditoria, ModoSistema, Severidad

gestionar_alertas = permiso_requerido('gestionar_alertas')
ver_evidencia = permiso_requerido('gestionar_alertas', 'ver_auditoria')
ejecutar_contencion = permiso_requerido('ejecutar_contencion')

ACCIONES_SOBRE_CUENTA = {
    'revocar_sesiones': ('Cerrar sus sesiones', contencion.revocar_sesiones),
    'restringir': ('Restringir permisos', contencion.restringir_cuenta),
    'desactivar': ('Desactivar la cuenta', contencion.desactivar_cuenta),
    'invalidar': ('Invalidar su contraseña', contencion.invalidar_credenciales),
    'cerrar_emergencias': ('Cerrar sus accesos de emergencia', contencion.cerrar_emergencias),
    'restaurar': ('Restaurar la cuenta', contencion.restaurar_cuenta),
}


@gestionar_alertas
def lista(request):
    estado, severidad = request.GET.get('estado', ''), request.GET.get('severidad', '')
    consulta = AlertaSeguridad.objects.all()
    if estado in EstadoAlerta.values:
        consulta = consulta.filter(estado=estado)
    elif estado == 'abiertas':
        consulta = consulta.exclude(estado__in=[EstadoAlerta.DESCARTADA, EstadoAlerta.CERRADA])
    if severidad in Severidad.values:
        consulta = consulta.filter(severidad=severidad)
    return render(request, 'gestion_interna/auditoria/alertas.html', {
        'seccion': 'alertas', 'alertas': consulta[:200], 'estado': estado, 'severidad': severidad,
        'estados': EstadoAlerta.choices, 'severidades': Severidad.choices,
        'abiertas': AlertaSeguridad.objects.exclude(estado__in=[EstadoAlerta.DESCARTADA, EstadoAlerta.CERRADA]).count(),
        'modo': contencion.modo_actual(),
    })


@gestionar_alertas
@require_POST
def detectar(request):
    nuevas = motor.detectar()
    messages.success(request, f'Detección ejecutada: {len(nuevas)} alerta{"s" if len(nuevas) != 1 else ""} nueva{"s" if len(nuevas) != 1 else ""}.')
    return redirect('auditoria:alertas')


@gestionar_alertas
def detalle(request, pk):
    alerta = get_object_or_404(AlertaSeguridad, pk=pk)
    objetivo = get_user_model().objects.filter(pk=alerta.actor_id).first() if alerta.actor_id else None
    puede_ver_eventos = request.user.has_perm('usuarios.ver_auditoria')
    eventos = []
    if puede_ver_eventos and alerta.actor_id:
        eventos = EventoAuditoria.objects.filter(actor_id=alerta.actor_id).order_by('-id')[:25]
    return render(request, 'gestion_interna/auditoria/alerta.html', {
        'seccion': 'alertas', 'alerta': alerta, 'objetivo': objetivo, 'eventos': eventos, 'puede_ver_eventos': puede_ver_eventos,
        'siguientes': [(e.value, e.label) for e in motor.TRANSICIONES[EstadoAlerta(alerta.estado)]],
        'acciones': [(k, v[0]) for k, v in ACCIONES_SOBRE_CUENTA.items()] if objetivo else [],
        'puede_contener': request.user.has_perm('usuarios.ejecutar_contencion'),
        'nota_minima': motor.NOTA_MINIMA_CIERRE,
    })


@gestionar_alertas
@require_POST
def cambiar_estado(request, pk):
    alerta = get_object_or_404(AlertaSeguridad, pk=pk)
    try:
        motor.cambiar_estado(alerta, request.POST.get('estado', ''), request.user, request.POST.get('nota', ''))
    except (motor.TransicionInvalida, ValueError) as error:
        messages.error(request, str(error) if isinstance(error, motor.TransicionInvalida) else 'Estado no válido.')
    else:
        messages.success(request, 'Alerta actualizada.')
    return redirect('auditoria:alerta', pk=pk)


@ver_evidencia
@require_POST
def evidencia(request, pk):
    alerta = get_object_or_404(AlertaSeguridad, pk=pk)
    contenido, huella, _archivo = contencion.preservar_evidencia(alerta, request.user)
    respuesta = HttpResponse(contenido, content_type='application/json; charset=utf-8')
    respuesta['Content-Disposition'] = f'attachment; filename="alerta-{alerta.pk}-{huella[:12]}.json"'
    respuesta['X-Evidencia-SHA256'] = huella
    return respuesta


@ejecutar_contencion
@require_POST
def contener(request, pk):
    alerta = get_object_or_404(AlertaSeguridad, pk=pk)
    accion = request.POST.get('accion', '')
    objetivo = get_user_model().objects.filter(pk=alerta.actor_id).first() if alerta.actor_id else None
    if accion not in ACCIONES_SOBRE_CUENTA or objetivo is None:
        messages.error(request, 'Acción no válida para esta alerta.')
        return redirect('auditoria:alerta', pk=pk)
    etiqueta, funcion = ACCIONES_SOBRE_CUENTA[accion]
    try:
        funcion(objetivo, request.user)
    except contencion.ContencionError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f'Hecho: {etiqueta.lower()}.')
    return redirect('auditoria:alerta', pk=pk)


@ejecutar_contencion
def modo(request):
    if request.method == 'POST':
        nuevo = request.POST.get('modo', '')
        if nuevo in ModoSistema.values:
            contencion.cambiar_modo(nuevo, request.user, motivo_codigo=request.POST.get('motivo', '')[:40])
            messages.success(request, f'Modo del sistema: {ModoSistema(nuevo).label}.')
        else:
            messages.error(request, 'Modo no válido.')
        return redirect(reverse('auditoria:modo'))
    return render(request, 'gestion_interna/auditoria/modo.html', {
        'seccion': 'contencion', 'modo': contencion.modo_actual(), 'modos': ModoSistema.choices,
    })

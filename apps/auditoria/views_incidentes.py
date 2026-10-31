"""Casos de respuesta a incidentes. Analizar y registrar: `gestionar_alertas`. Autorizar notificaciones: `ejecutar_contencion`."""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.usuarios.permisos import permiso_requerido

from . import incidentes as plan
from .models import AlertaSeguridad, IncidenteSeguridad, Severidad

gestionar = permiso_requerido('gestionar_alertas')
autorizar = permiso_requerido('ejecutar_contencion')


def _hacer(request, codigo, funcion, *args, mensaje='Listo.'):
    incidente = get_object_or_404(IncidenteSeguridad, codigo=codigo)
    try:
        funcion(incidente, request.user, *args)
    except (plan.IncidenteError, ValueError) as error:
        messages.error(request, str(error) if isinstance(error, plan.IncidenteError) else 'Dato no válido.')
    else:
        messages.success(request, mensaje)
    return redirect('auditoria:incidente', codigo=codigo)


@gestionar
def lista(request):
    incidentes = list(IncidenteSeguridad.objects.all()[:100])
    for i in incidentes:
        i.con_plazos_vencidos = i.fase != 'CERRADO' and bool(plan.vencidos(i))
    return render(request, 'gestion_interna/auditoria/incidentes.html', {
        'seccion': 'incidentes', 'incidentes': incidentes, 'severidades': Severidad.choices,
    })


@gestionar
@require_POST
def abrir(request):
    alertas = AlertaSeguridad.objects.filter(pk__in=[p for p in request.POST.getlist('alerta') if p.isdigit()])
    severidad = request.POST.get('severidad', '')
    resumen = request.POST.get('resumen', '').strip()
    if severidad not in Severidad.values or len(resumen) < 10:
        messages.error(request, 'Indica la severidad y un resumen de al menos 10 caracteres, sin datos personales.')
        return redirect('auditoria:incidentes')
    incidente = plan.abrir(resumen, severidad, request.user, alertas)
    return redirect('auditoria:incidente', codigo=incidente.codigo)


@gestionar
def detalle(request, codigo):
    incidente = get_object_or_404(IncidenteSeguridad, codigo=codigo)
    ahora = timezone.now()
    return render(request, 'gestion_interna/auditoria/incidente.html', {
        'seccion': 'incidentes', 'i': incidente, 'ahora': ahora,
        'plazos': [(clave, texto, limite, hecho, hecho is None and limite < ahora) for clave, (texto, limite, hecho) in incidente.plazos.items()],
        'pendientes': plan.pendientes_de_cierre(incidente),
        'clasificaciones': IncidenteSeguridad.Clasificacion.choices,
        'puede_autorizar': request.user.has_perm('usuarios.ejecutar_contencion'),
        'alertas': incidente.alertas.all(),
    })


@gestionar
@require_POST
def clasificar(request, codigo):
    p = request.POST
    criterios = {c: c in p for c in ('afecta_datos_personales', 'afecta_continuidad', 'afecta_salud_personas',
                                     'hay_datos_sensibles', 'hay_menores_14', 'riesgo_razonable')}
    criterios.update(titulares_aprox=p.get('titulares_aprox') or 0, categorias_datos=p.get('categorias_datos', ''))
    incidente = get_object_or_404(IncidenteSeguridad, codigo=codigo)
    try:
        plan.clasificar(incidente, p.get('clasificacion', ''), request.user, **criterios)
    except (plan.IncidenteError, ValueError):
        messages.error(request, 'No se pudo registrar la clasificación.')
    else:
        messages.success(request, 'Clasificación registrada.')
    return redirect('auditoria:incidente', codigo=codigo)


@gestionar
@require_POST
def avanzar(request, codigo):
    return _hacer(request, codigo, plan.avanzar, request.POST.get('evidencia', '').strip(), mensaje='Fase actualizada.')


@gestionar
@require_POST
def proponer(request, codigo):
    return _hacer(request, codigo, plan.proponer_notificacion, mensaje='Notificación propuesta. Falta que otra persona la autorice.')


@autorizar
@require_POST
def autorizar_notificacion(request, codigo):
    return _hacer(request, codigo, plan.autorizar_notificacion, mensaje='Notificación autorizada.')


@gestionar
@require_POST
def notificada(request, codigo):
    return _hacer(request, codigo, plan.registrar_notificacion, request.POST.get('cual', ''), mensaje='Notificación registrada.')


@gestionar
@require_POST
def sin_notificar(request, codigo):
    return _hacer(request, codigo, plan.justificar_sin_notificar, request.POST.get('motivo', ''), mensaje='Justificación registrada.')


@gestionar
@require_POST
def lecciones(request, codigo):
    return _hacer(request, codigo, plan.registrar_lecciones, request.POST.get('lecciones', ''), mensaje='Lecciones registradas.')


@gestionar
@require_POST
def cerrar(request, codigo):
    return _hacer(request, codigo, plan.cerrar, mensaje='Caso cerrado.')

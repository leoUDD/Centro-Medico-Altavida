from datetime import date

from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.auditoria import servicio as auditoria
from apps.auditoria.models import Operacion
from apps.pacientes.models import Paciente
from apps.pacientes.views import paciente_de, solo_pacientes
from apps.seguridad.indice import indice_rut
from apps.seguridad.rut import rut_valido
from apps.usuarios.permisos import permiso_requerido

from . import servicio
from .models import Consentimiento, Finalidad, RegistroConsentimiento, Representacion

VERSION_AVISO = 1
gestionar_representaciones = permiso_requerido('gestionar_agenda')
ver_consentimientos = permiso_requerido('ver_consentimientos')


def aviso(request):
    """Aviso de privacidad: público, para poder leerlo antes de crear la cuenta."""
    return render(request, 'consentimientos/aviso.html', {
        'version': VERSION_AVISO, 'finalidades': Finalidad.objects.filter(activa=True),
    })


@solo_pacientes
def mis_consentimientos(request):
    paciente = paciente_de(request)
    representados = [
        {'paciente': r.menor, 'representacion': r, 'filas': servicio.estado_por_finalidad(r.menor)}
        for r in Representacion.objects.filter(representante=paciente).select_related('menor') if r.vigente
    ]
    return render(request, 'consentimientos/mis_consentimientos.html', {
        'seccion': 'consentimientos', 'paciente': paciente, 'es_menor': servicio.es_menor(paciente),
        'filas': servicio.estado_por_finalidad(paciente), 'representados': representados,
        'historial': paciente.registros_consentimiento.select_related('finalidad', 'texto').order_by('-fecha', '-id')[:30],
    })


@solo_pacientes
@require_POST
def cambiar(request, codigo, accion):
    if accion not in ('otorgar', 'revocar'):
        return redirect('consentimientos:mis')
    actor = paciente_de(request)
    destino = actor
    otro = request.POST.get('paciente', '')
    if otro and otro != actor.codigo:
        destino = get_object_or_404(Paciente, codigo=otro)
    try:
        servicio.cambiar(destino, codigo, accion == 'otorgar', request.user, actor_paciente=actor)
    except servicio.ConsentimientoError as error:
        # Un intento de decidir por otra persona sin representación verificada queda registrado.
        auditoria.registrar(Operacion.CONSENTIMIENTO_CAMBIO, 'consentimiento', destino.codigo, resultado='DENEGADO',
                            actor=request.user, detalle={'finalidad': codigo, 'motivo_codigo': 'sin_representacion'})
        messages.error(request, str(error))
    else:
        messages.success(request, 'Autorización registrada.' if accion == 'otorgar' else 'Retiraste tu autorización. Desde ahora no se usa para esa finalidad.')
    return redirect('consentimientos:mis')


def _nacimiento(paciente):
    try:
        return date.fromisoformat(paciente.fecha_nacimiento)
    except (TypeError, ValueError):
        return None


@gestionar_representaciones
def representaciones(request):
    return render(request, 'consentimientos/representaciones.html', {
        'seccion': 'representaciones',
        'lista': Representacion.objects.select_related('menor', 'representante').order_by('-creada_en')[:50],
        'parentescos': Representacion.Parentesco.choices, 'acreditaciones': Representacion.Acreditacion.choices,
    })


def _paciente_por_rut(texto):
    if not rut_valido(texto):
        return None
    return Paciente.objects.filter(identidad__rut_indice=indice_rut(texto)).first()


@gestionar_representaciones
@require_POST
def registrar_representacion(request):
    """Recepción verifica en persona el documento y deja constancia. No se guardan copias del documento."""
    menor = _paciente_por_rut(request.POST.get('rut_menor', ''))
    representante = _paciente_por_rut(request.POST.get('rut_representante', ''))
    parentesco = request.POST.get('parentesco', '')
    acreditacion = request.POST.get('acreditacion', '')
    if not menor or not representante or menor.pk == representante.pk:
        messages.error(request, 'No encontramos a ambas personas, o son la misma. Las dos deben estar registradas.')
    elif not servicio.es_menor(menor) or servicio.es_menor(representante):
        messages.error(request, 'La persona representada debe ser menor de edad y quien representa, mayor de edad.')
    elif parentesco not in Representacion.Parentesco.values or acreditacion not in Representacion.Acreditacion.values:
        messages.error(request, 'Indica el parentesco y el documento que revisaste.')
    elif Representacion.objects.filter(menor=menor, representante=representante).exists():
        messages.error(request, 'Ya existe una representación entre estas dos personas.')
    else:
        nacimiento = _nacimiento(menor)
        mayoria = nacimiento.replace(year=nacimiento.year + servicio.EDAD_CONSENTIMIENTO_PROPIO) if nacimiento else None
        from django.utils import timezone
        representacion = Representacion.objects.create(
            menor=menor, representante=representante, parentesco=parentesco, acreditacion=acreditacion,
            estado=Representacion.Estado.VERIFICADA, verificada_en=timezone.now(), verificada_por=request.user.pk,
            vigente_hasta=mayoria,
        )
        auditoria.registrar(Operacion.CONSENTIMIENTO_CAMBIO, 'representacion', menor.codigo, actor=request.user,
                            detalle={'accion': 'representacion_verificada', 'tipo': acreditacion, 'estado_nuevo': representacion.estado})
        messages.success(request, 'Representación verificada y registrada.')
    return redirect('consentimientos:representaciones')


@gestionar_representaciones
@require_POST
def terminar_representacion(request, pk):
    representacion = get_object_or_404(Representacion, pk=pk, estado=Representacion.Estado.VERIFICADA)
    representacion.estado = Representacion.Estado.TERMINADA
    representacion.save(update_fields=['estado'])
    revocados = servicio.cerrar_vencidos(representacion.menor, request.user)
    auditoria.registrar(Operacion.CONSENTIMIENTO_CAMBIO, 'representacion', representacion.menor.codigo, actor=request.user,
                        detalle={'accion': 'representacion_terminada', 'cantidad': revocados})
    messages.success(request, 'Representación terminada. Los consentimientos que dio el representante quedaron revocados.')
    return redirect('consentimientos:representaciones')


@ver_consentimientos
def panel(request):
    """Vista del Encargado de privacidad: cifras y movimientos, solo con códigos seudónimos."""
    resumen = Finalidad.objects.annotate(
        otorgados=Count('consentimientos', filter=Q(consentimientos__estado=Consentimiento.Estado.OTORGADO)),
        revocados=Count('consentimientos', filter=Q(consentimientos__estado=Consentimiento.Estado.REVOCADO)),
    )
    auditoria.registrar(Operacion.CONSENTIMIENTO_CAMBIO, 'consentimiento', '', actor=request.user,
                        detalle={'accion': 'consulta_panel'})
    return render(request, 'consentimientos/panel.html', {
        'seccion': 'consentimientos', 'resumen': resumen,
        'movimientos': RegistroConsentimiento.objects.select_related('paciente', 'finalidad', 'texto').order_by('-fecha', '-id')[:50],
    })

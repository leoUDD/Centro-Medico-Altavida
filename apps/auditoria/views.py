from datetime import date, datetime, time

from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.usuarios.permisos import permiso_requerido

from . import servicio
from .models import EventoAuditoria, Operacion, Resultado

ver_auditoria = permiso_requerido('ver_auditoria')
POR_PAGINA = 50


def _fecha(texto, fin=False):
    try:
        dia = date.fromisoformat(texto)
    except (TypeError, ValueError):
        return None
    return timezone.make_aware(datetime.combine(dia, time.max if fin else time.min))


@ver_auditoria
def eventos(request):
    filtros = {
        'operacion': request.GET.get('operacion', ''), 'resultado': request.GET.get('resultado', ''),
        'actor': request.GET.get('actor', '').strip(), 'recurso': request.GET.get('recurso', '').strip(),
        'desde': request.GET.get('desde', ''), 'hasta': request.GET.get('hasta', ''),
    }
    consulta = EventoAuditoria.objects.order_by('-id')
    if filtros['operacion'] in Operacion.values:
        consulta = consulta.filter(operacion=filtros['operacion'])
    if filtros['resultado'] in Resultado.values:
        consulta = consulta.filter(resultado=filtros['resultado'])
    if filtros['actor'].isdigit():
        consulta = consulta.filter(actor_id=int(filtros['actor']))
    if filtros['recurso']:
        consulta = consulta.filter(recurso_ref=filtros['recurso'])
    if (desde := _fecha(filtros['desde'])):
        consulta = consulta.filter(fecha__gte=desde)
    if (hasta := _fecha(filtros['hasta'], fin=True)):
        consulta = consulta.filter(fecha__lte=hasta)

    pagina = Paginator(consulta, POR_PAGINA).get_page(request.GET.get('pagina'))
    # Consultar el registro también queda registrado (quién miró, cuántos eventos vio), sin copiar los filtros.
    servicio.registrar(Operacion.AUDITORIA_CONSULTA, 'auditoria', '', detalle={'cantidad': len(pagina)})
    parametros = request.GET.copy()
    parametros.pop('pagina', None)
    return render(request, 'gestion_interna/auditoria/eventos.html', {
        'seccion': 'auditoria', 'pagina': pagina, 'filtros': filtros, 'parametros': parametros.urlencode(),
        'operaciones': Operacion.choices, 'resultados': Resultado.choices,
        'total': EventoAuditoria.objects.count(), 'meses': servicio.meses_de_retencion(),
    })


@ver_auditoria
@require_POST
def verificar(request):
    integra, primer_problema, total = servicio.verificar()
    servicio.registrar(
        Operacion.AUDITORIA_VERIFICACION, 'auditoria', primer_problema or '',
        resultado=Resultado.OK if integra else Resultado.FALLIDO, detalle={'eventos': total},
    )
    if integra:
        messages.success(request, f'Cadena íntegra: {total} eventos verificados, ninguno alterado.')
    else:
        messages.error(
            request, f'¡La cadena está rota! Se verificaron {total} eventos y el evento #{primer_problema} no coincide. '
                     'Trátalo como un posible incidente (ver el plan de respuesta).',
        )
    return redirect(reverse('auditoria:eventos'))

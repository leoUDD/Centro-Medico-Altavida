"""Panel del personal administrativo: agenda del día y recordatorios."""
import re
import unicodedata
from datetime import date

from django import forms
from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.notificaciones import recordatorios
from apps.notificaciones.models import EjecucionRecordatorios, Notificacion, Recordatorio, ReglaRecordatorio
from apps.pacientes.models import Paciente
from apps.profesionales.models import Profesional
from apps.seguridad.indice import indice_rut
from apps.seguridad.rut import rut_valido
from apps.pacientes.acceso import registrar_reidentificacion
from apps.usuarios.permisos import permiso_requerido

from . import calendario, servicios
from .models import Cita

solo_administrativos = permiso_requerido('gestionar_agenda', 'ver_identidad')
editar_contacto_paciente = permiso_requerido('editar_contacto_paciente', 'ver_identidad')
POR_PAGINA = 25
ESTADOS_FILTRO = {'confirmada': Cita.Estado.CONFIRMADA, 'por-confirmar': Cita.Estado.AGENDADA, 'cancelada': Cita.Estado.CANCELADA}


def _sin_tildes(texto):
    return unicodedata.normalize('NFD', texto.casefold()).encode('ascii', 'ignore').decode()


def _fecha(texto):
    try:
        return date.fromisoformat(texto)
    except (TypeError, ValueError):
        return timezone.localdate()


def _estado_recordatorio(cita):
    """Texto y tono de la columna "Recordatorio" a partir de lo ocurrido con sus envíos."""
    envios = list(cita.recordatorios.all())
    fallidos = [r for r in envios if r.estado == Recordatorio.Estado.FALLIDO]
    if cita.estado == Cita.Estado.CANCELADA:
        return {'texto': 'Cita cancelada', 'problema': False}
    if fallidos:
        return {'texto': f'{fallidos[0].get_canal_display()}: {fallidos[0].error or "no entregado"}', 'problema': True}
    enviados = sorted((r for r in envios if r.estado == Recordatorio.Estado.ENVIADO), key=lambda r: r.regla.horas_antes)
    if enviados:
        return {'texto': f'Enviado {enviados[0].regla.horas_antes} h antes', 'problema': False}
    if any(r.estado == Recordatorio.Estado.PENDIENTE for r in envios):
        return {'texto': 'Pendiente de envío', 'problema': False}
    return {'texto': 'Sin recordatorios aún', 'problema': False}


def _filtrar_por_paciente(citas, consulta):
    if rut_valido(consulta):
        indice = indice_rut(consulta)
        return [c for c in citas if c.paciente.identidad.rut_indice == indice]
    palabras = _sin_tildes(consulta).split()
    return [c for c in citas if all(p in _sin_tildes(c.paciente.nombre_completo) for p in palabras)]


@solo_administrativos
def dashboard(request):
    fecha = _fecha(request.GET.get('fecha'))
    filtro_prof = request.GET.get('profesional', '')
    filtro_estado = request.GET.get('estado', '')
    consulta = request.GET.get('q', '').strip()

    del_dia = list(
        Cita.objects.filter(inicio__date=fecha)
        .select_related('paciente__identidad', 'profesional__usuario', 'sucursal', 'tipo_examen')
        .prefetch_related('recordatorios__regla').order_by('inicio')
    )
    vigentes = [c for c in del_dia if c.vigente]
    confirmadas = sum(c.estado == Cita.Estado.CONFIRMADA for c in vigentes)
    hoy = timezone.localdate()
    fallidos = (
        Recordatorio.objects.filter(estado=Recordatorio.Estado.FALLIDO, cita__inicio__date__gte=hoy)
        .exclude(cita__estado=Cita.Estado.CANCELADA)
    )

    citas = del_dia
    if filtro_prof == 'laboratorio':
        citas = [c for c in citas if c.tipo == Cita.Tipo.EXAMEN]
    elif filtro_prof.isdigit():
        citas = [c for c in citas if c.profesional_id == int(filtro_prof)]
    if filtro_estado in ESTADOS_FILTRO:
        citas = [c for c in citas if c.estado == ESTADOS_FILTRO[filtro_estado]]
    if consulta:
        citas = _filtrar_por_paciente(citas, consulta)

    pagina = Paginator(citas, POR_PAGINA).get_page(request.GET.get('pagina'))
    for cita in pagina:
        cita.recordatorio_estado = _estado_recordatorio(cita)
    registrar_reidentificacion(request.user, 'Agenda del día', len(pagina))

    parametros = request.GET.copy()
    parametros.pop('pagina', None)
    return render(request, 'gestion_interna/recepcion/dashboard.html', {
        'fecha': fecha, 'es_hoy': fecha == hoy,
        'fecha_texto': f'{calendario.DIAS[fecha.weekday()]} {fecha.day} de {calendario.MESES[fecha.month - 1]} de {fecha.year}',
        'total': len(del_dia), 'consultas': sum(c.tipo == Cita.Tipo.CONSULTA for c in del_dia),
        'examenes': sum(c.tipo == Cita.Tipo.EXAMEN for c in del_dia),
        'confirmadas': confirmadas, 'porcentaje': round(100 * confirmadas / len(vigentes)) if vigentes else 0,
        'por_confirmar': sum(c.estado == Cita.Estado.AGENDADA for c in vigentes),
        'cantidad_fallidos': fallidos.count(),
        'pagina': pagina, 'filtrados': len(citas), 'parametros': parametros.urlencode(),
        'profesionales': Profesional.objects.filter(activo=True).select_related('usuario'),
        'filtro_prof': filtro_prof, 'filtro_estado': filtro_estado, 'consulta': consulta,
        'reglas': ReglaRecordatorio.objects.all(),
        'regla_24h': ReglaRecordatorio.objects.filter(horas_antes=24).first(),
        'ultima_ejecucion': EjecucionRecordatorios.objects.first(),
        'pendientes': Recordatorio.objects.filter(estado=Recordatorio.Estado.PENDIENTE).count(),
        'con_problemas': fallidos.select_related('cita__paciente__identidad', 'cita__profesional__usuario', 'cita__sucursal')[:10],
        'ahora': timezone.now(),
    })


def _volver(request):
    return redirect(request.POST.get('volver') if (request.POST.get('volver') or '').startswith('/administracion/') else reverse('recepcion:dashboard'))


@solo_administrativos
@require_POST
def confirmar_cita(request, pk):
    try:
        servicios.confirmar_asistencia(get_object_or_404(Cita, pk=pk))
    except servicios.ReservaError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, 'Cita confirmada.')
    return _volver(request)


@solo_administrativos
@require_POST
def cancelar_cita(request, pk):
    cita = get_object_or_404(Cita, pk=pk)
    try:
        servicios.cancelar_cita(cita)
    except servicios.ReservaError as e:
        messages.error(request, str(e))
    else:
        Notificacion.objects.create(
            paciente=cita.paciente, tipo=Notificacion.Tipo.CITA, cita=cita, titulo='Tu hora fue cancelada',
            detalle=f'El centro canceló tu hora del {calendario.cuando(cita.inicio)}. Puedes agendar una nueva desde tu cuenta.',
        )
        messages.success(request, 'Cita cancelada y paciente avisado.')
    return _volver(request)


@solo_administrativos
@require_POST
def generar_ahora(request):
    ejecucion = recordatorios.ejecutar(usuario=request.user)
    messages.success(
        request,
        f'Recordatorios: {ejecucion.creados} generados, {ejecucion.enviados} enviados, {ejecucion.fallidos} con problemas.',
    )
    return redirect(reverse('recepcion:dashboard') + '#recordatorios')


@solo_administrativos
@require_POST
def guardar_reglas(request):
    plantilla = request.POST.get('plantilla', '').strip()
    if not plantilla or not recordatorios.plantilla_valida(plantilla):
        messages.error(request, 'El mensaje solo puede usar {nombre}, {fecha}, {hora} y {profesional}.')
        return redirect(reverse('recepcion:dashboard') + '#recordatorios')
    for regla in ReglaRecordatorio.objects.all():
        regla.activa = f'regla_{regla.horas_antes}' in request.POST
        if regla.horas_antes == 24:
            regla.plantilla = plantilla[:500]
        regla.save()
    messages.success(request, 'Reglas de recordatorio guardadas.')
    return redirect(reverse('recepcion:dashboard') + '#recordatorios')


@solo_administrativos
@require_POST
def reintentar(request, pk):
    recordatorio = get_object_or_404(Recordatorio, pk=pk, estado=Recordatorio.Estado.FALLIDO)
    recordatorio.estado, recordatorio.error = Recordatorio.Estado.PENDIENTE, ''
    recordatorio.save(update_fields=['estado', 'error'])
    enviados, _ = recordatorios.enviar_pendientes(Recordatorio.objects.filter(pk=pk))
    messages.success(request, 'Recordatorio reenviado.') if enviados else messages.error(request, 'El recordatorio volvió a fallar. Revisa el contacto.')
    return redirect(reverse('recepcion:dashboard') + '#recordatorios')


class ContactoForm(forms.Form):
    email = forms.EmailField(label='Correo electrónico', required=False)
    telefono = forms.CharField(label='Teléfono celular', required=False, max_length=20)

    def clean_telefono(self):
        telefono = re.sub(r'[^0-9+]', '', self.cleaned_data['telefono'])
        if telefono and len(re.sub(r'\D', '', telefono)) < 9:
            raise forms.ValidationError('Ingresa un número de al menos 9 dígitos, por ejemplo +56 9 1234 5678.')
        return telefono


@editar_contacto_paciente
def editar_contacto(request, pk):
    paciente = get_object_or_404(Paciente, pk=pk)
    form = ContactoForm(request.POST or None, initial={'email': paciente.email, 'telefono': paciente.telefono})
    if request.method == 'POST' and form.is_valid():
        paciente.actualizar_identidad(email=form.cleaned_data['email'], telefono=form.cleaned_data['telefono'])
        registrar_reidentificacion(request.user, 'Corrección de contacto', 1)
        messages.success(request, 'Contacto actualizado. Ya puedes reintentar el recordatorio.')
        return redirect(reverse('recepcion:dashboard') + '#recordatorios')
    return render(request, 'gestion_interna/recepcion/contacto.html', {'form': form, 'paciente': paciente, 'seccion': 'recordatorios'})

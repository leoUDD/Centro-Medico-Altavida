from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.laboratorio.models import OrdenExamen, TipoExamen
from apps.pacientes.views import paciente_de, solo_pacientes
from apps.profesionales.models import Especialidad, Profesional
from apps.sucursales.models import Sucursal

from . import calendario, servicios
from .disponibilidad import dias_con_horas, horas_consulta, horas_examen
from .models import Cita


def _ultimo(datos, nombre):
    """Último valor enviado: los botones de día, hora y mes van después de los campos ocultos que conservan el estado."""
    valores = datos.getlist(nombre) if hasattr(datos, 'getlist') else []
    return valores[-1] if valores else ''


def _elegir(queryset, pk):
    """Registro con ese pk dentro del queryset, o el primero si no hay ninguno válido."""
    try:
        return queryset.filter(pk=int(pk)).first() or queryset.first()
    except (TypeError, ValueError):
        return queryset.first()


def _a_reprogramar(request, paciente, tipo):
    pk = request.POST.get('reprogramar') or request.GET.get('reprogramar')
    if not (pk and pk.isdigit()):
        return None
    return Cita.objects.filter(
        pk=pk, paciente=paciente, tipo=tipo, inicio__gt=timezone.now(),
    ).exclude(estado=Cita.Estado.CANCELADA).first()


def _seleccion_calendario(datos, buscar_horas):
    """Mes, día y hora elegidos (ya validados contra la disponibilidad real) y lo necesario para dibujarlos."""
    anio, mes = calendario.parsear_mes(_ultimo(datos, 'mes'))
    dias_ok = dias_con_horas(buscar_horas, anio, mes)
    dia = calendario.parsear_dia(_ultimo(datos, 'dia'))
    if dia not in dias_ok:
        dia = None
    horas = buscar_horas(dia) if dia else {}
    texto_hora = _ultimo(datos, 'hora')
    inicio = next((i for i in horas if f'{timezone.localtime(i):%H:%M}' == texto_hora), None)
    return {
        'calendario': calendario.construir(anio, mes, dias_ok, dia),
        'mes': f'{anio}-{mes:02d}',
        'dia': dia,
        'horas': [{'valor': f'{timezone.localtime(i):%H:%M}', 'elegida': i == inicio} for i in horas],
        'hora': f'{timezone.localtime(inicio):%H:%M}' if inicio else '',
        'inicio': inicio,
        'resumen': calendario.resumen(inicio) if inicio else '',
    }, horas


@solo_pacientes
def consulta(request):
    paciente = paciente_de(request)
    reprogramar = _a_reprogramar(request, paciente, Cita.Tipo.CONSULTA)
    publicado = request.method == 'POST'
    datos = request.POST if publicado else {}

    # Solo se ofrecen especialidades que tienen al menos un profesional activo.
    especialidades = Especialidad.objects.filter(activa=True, profesionales__activo=True).distinct()
    especialidad = _elegir(especialidades, datos.get('especialidad'))
    profesionales = Profesional.objects.filter(activo=True, especialidad=especialidad).select_related('usuario', 'especialidad')
    elegido = profesionales.filter(pk=datos.get('profesional')).first() if str(datos.get('profesional', '')).isdigit() else None
    modalidad = datos.get('modalidad') if datos.get('modalidad') in Cita.Modalidad.values else Cita.Modalidad.PRESENCIAL
    motivo = datos.get('motivo', '').strip()[:1000]

    candidatos = [elegido] if elegido else list(profesionales)
    if modalidad == Cita.Modalidad.TELEMEDICINA:
        candidatos = [p for p in candidatos if p.ofrece_telemedicina]
    seleccion, horas = _seleccion_calendario(datos, lambda dia: horas_consulta(candidatos, dia) if candidatos else {})

    error = None
    if publicado and datos.get('accion') == 'confirmar':
        if seleccion['inicio'] is None:
            error = 'Elige un día y una hora disponibles.'
        else:
            try:
                profesional = horas[seleccion['inicio']][0]
                cita = servicios.reservar_consulta(paciente, profesional, seleccion['inicio'], modalidad, motivo, reprogramar)
            except servicios.ReservaError as e:
                error = str(e)
            else:
                messages.success(request, f'Tu hora quedó agendada para el {calendario.cuando(cita.inicio)}.')
                return redirect('notificaciones:lista')

    return render(request, 'portal_paciente/agendar_consulta.html', {
        'seccion': 'consulta', 'error': error, 'reprogramar': reprogramar, 'sin_agenda': not especialidades.exists(),
        'especialidades': especialidades, 'especialidad': especialidad,
        'profesionales': profesionales, 'profesional': elegido,
        'modalidades': Cita.Modalidad.choices, 'modalidad': modalidad, 'motivo': motivo,
        'sin_horarios': not candidatos,
        'detalle_reserva': ' · '.join(filter(None, [
            str(especialidad or ''), elegido.nombre if elegido else 'Cualquier profesional disponible',
            Cita.Modalidad(modalidad).label,
        ])),
        'pie_reserva': 'Te recordaremos 24 horas antes.',
        **seleccion,
    })


@solo_pacientes
def examen(request):
    paciente = paciente_de(request)
    reprogramar = _a_reprogramar(request, paciente, Cita.Tipo.EXAMEN)
    publicado = request.method == 'POST'
    datos = request.POST if publicado else {}

    tipos = TipoExamen.objects.filter(activo=True)
    # Sin elección previa, se ofrece primero el examen de la orden de Altavida que el paciente aún no usa.
    pendiente = OrdenExamen.objects.filter(paciente=paciente, utilizada=False, tipo_examen__activo=True).first()
    por_defecto = reprogramar.tipo_examen_id if reprogramar else (pendiente.tipo_examen_id if pendiente else None)
    tipo = _elegir(tipos, datos.get('tipo_examen') or por_defecto)
    sedes = Sucursal.objects.filter(activa=True)
    sede = _elegir(sedes, datos.get('sucursal') or (reprogramar.sucursal_id if reprogramar else None))

    opciones = []
    if tipo:
        ordenes = OrdenExamen.objects.filter(paciente=paciente, tipo_examen=tipo).select_related('medico')
        ordenes = ordenes.filter(Q(utilizada=False) | Q(pk=reprogramar.orden_id if reprogramar else None))
        opciones = [{'valor': f'altavida:{o.pk}', 'orden': o} for o in ordenes]
    opciones.append({'valor': 'externa', 'orden': None})
    valores = [o['valor'] for o in opciones]
    orden_elegida = datos.get('orden') if datos.get('orden') in valores else valores[0]

    seleccion, horas = _seleccion_calendario(datos, lambda dia: horas_examen(sede, tipo, dia) if tipo and sede else {})

    error = None
    if publicado and datos.get('accion') == 'confirmar':
        if seleccion['inicio'] is None:
            error = 'Elige un día y una hora disponibles.'
        else:
            orden = next((o['orden'] for o in opciones if o['valor'] == orden_elegida), None)
            try:
                cita = servicios.reservar_examen(
                    paciente, tipo, sede, seleccion['inicio'], orden=orden,
                    archivo=request.FILES.get('archivo'), reprogramar=reprogramar,
                )
            except servicios.ReservaError as e:
                error = str(e)
            else:
                messages.success(request, f'Tu toma de examen quedó agendada para el {calendario.cuando(cita.inicio)}.')
                return redirect('notificaciones:lista')

    ayuno = f'Ayuno de {tipo.ayuno_horas} h' if tipo and tipo.requiere_ayuno else ''
    return render(request, 'portal_paciente/agendar_examen.html', {
        'seccion': 'examen', 'error': error, 'reprogramar': reprogramar, 'sin_agenda': not (tipos.exists() and sedes.exists()),
        'tipos': tipos, 'tipo': tipo, 'sedes': sedes, 'sede': sede,
        'opciones_orden': opciones, 'orden_elegida': orden_elegida,
        'detalle_reserva': ' · '.join(filter(None, [str(tipo or ''), f'Laboratorio {sede}' if sede else '', ayuno])),
        'pie_reserva': 'Te recordaremos el ayuno la noche anterior.' if ayuno else 'Te recordaremos 24 horas antes.',
        **seleccion,
    })


def _cita_propia(request, pk):
    return get_object_or_404(Cita, pk=pk, paciente=paciente_de(request))


@solo_pacientes
@require_POST
def confirmar(request, pk):
    try:
        servicios.confirmar_asistencia(_cita_propia(request, pk))
    except servicios.ReservaError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, 'Confirmaste tu asistencia. ¡Te esperamos!')
    return redirect('notificaciones:lista')


@solo_pacientes
@require_POST
def cancelar(request, pk):
    try:
        servicios.cancelar_cita(_cita_propia(request, pk))
    except servicios.ReservaError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, 'Tu hora fue cancelada.')
    return redirect('notificaciones:lista')

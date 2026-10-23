import unicodedata
from datetime import timedelta

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.convenios.models import Cobertura
from apps.pacientes import acceso
from apps.pacientes.models import Paciente
from apps.seguridad.indice import indice_rut
from apps.seguridad.rut import rut_valido
from apps.usuarios.permisos import permiso_requerido

from .autorizacion import autorizar_paciente
from .bitacora import registrar_acceso as _registrar
from .forms import DiagnosticoForm, EmergenciaForm, NuevaFichaForm
from .models import AccesoFicha, Diagnostico, HistorialMedico

# El médico ve identidad (nombre, RUT) y datos clínicos; para escribir necesita además el permiso de edición.
ver_ficha = permiso_requerido('ver_datos_clinicos', 'ver_identidad')
editar_ficha = permiso_requerido('ver_datos_clinicos', 'editar_datos_clinicos', 'ver_identidad')
solo_emergencia = permiso_requerido('acceso_emergencia', 'ver_identidad')


def _sin_tildes(texto):
    return unicodedata.normalize('NFD', texto.casefold()).encode('ascii', 'ignore').decode()


def _buscar_pacientes(usuario, consulta):
    """Por RUT: índice ciego, sobre todos los pacientes (para poder pedir un acceso de emergencia).
    Por nombre: solo entre los pacientes con relación, y en memoria porque los datos están cifrados."""
    if rut_valido(consulta):
        return list(Paciente.objects.filter(identidad__rut_indice=indice_rut(consulta)))
    palabras = _sin_tildes(consulta).split()
    return [
        p for p in acceso.pacientes_con_relacion(usuario).order_by('-creado')
        if all(pal in _sin_tildes(p.nombre_completo) for pal in palabras)
    ]


def _decimal_o_vacio(valor):
    return '' if valor is None else valor


@ver_ficha
def buscar(request):
    consulta = request.GET.get('q', '').strip()
    resultados = _buscar_pacientes(request.user, consulta) if consulta else []
    con_relacion = {p.pk for p in resultados if acceso.tipo_de_acceso(request.user, p)}
    acceso.registrar_reidentificacion(request.user, 'Búsqueda de pacientes', len(con_relacion))
    visibles = [p for p in resultados if p.pk in con_relacion]
    seleccionado = None
    if visibles:
        seleccionado = next((p for p in visibles if str(p.pk) == request.GET.get('p')), visibles[0])
    return render(request, 'gestion_interna/fichas/buscar.html', {
        'seccion': 'buscar',
        'consulta': consulta,
        'resultados': resultados,
        'con_relacion': con_relacion,
        'seleccionado': seleccionado,
        'historial': getattr(seleccionado, 'historial', None) if seleccionado else None,
        'cobertura': seleccionado.coberturas.select_related('prevision').first() if seleccionado else None,
        'diagnosticos': seleccionado.diagnosticos.all()[:2] if seleccionado else [],
    })


@editar_ficha
def nueva(request):
    form = NuevaFichaForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        with transaction.atomic():
            paciente = Paciente.objects.create(
                creado_por=request.user,
                rut=d['rut'], nombres=d['nombres'], apellidos=d['apellidos'],
                fecha_nacimiento=d['fecha_nacimiento'].isoformat(), sexo=d['sexo'],
                grupo_sanguineo=d['grupo_sanguineo'],
                peso=_decimal_o_vacio(d['peso']), estatura=_decimal_o_vacio(d['estatura']),
                email=d['email'], telefono=d['telefono'],
                contacto_emergencia_nombre=d['contacto_emergencia_nombre'],
                contacto_emergencia_parentesco=d['contacto_emergencia_parentesco'],
                contacto_emergencia_telefono=d['contacto_emergencia_telefono'],
            )
            HistorialMedico.objects.create(
                paciente=paciente, alergias=d['alergias'], enfermedades=d['enfermedades'],
                medicamentos_activos=d['medicamentos_activos'], operaciones=d['operaciones'],
            )
            Cobertura.objects.create(paciente=paciente, prevision=d['prevision'])
            _registrar(paciente, request.user, AccesoFicha.Accion.CREACION)
        messages.success(request, f'Ficha creada para {paciente.nombre_completo}.')
        return redirect('fichas:detalle', pk=paciente.pk)
    return render(request, 'gestion_interna/fichas/nueva.html', {'form': form, 'seccion': 'nueva'})


@ver_ficha
def detalle(request, pk):
    paciente, redireccion = autorizar_paciente(request, pk)
    if redireccion:
        return redireccion
    _registrar(paciente, request.user, AccesoFicha.Accion.CONSULTA)
    return render(request, 'gestion_interna/fichas/detalle.html', {
        'seccion': 'buscar',
        'paciente': paciente,
        'historial': getattr(paciente, 'historial', None),
        'cobertura': paciente.coberturas.select_related('prevision').first(),
        'diagnosticos': paciente.diagnosticos.select_related('medico'),
        'recetas': paciente.recetas.all()[:10],
    })


@solo_emergencia
def emergencia(request, pk):
    """Pantalla de acceso excepcional: no muestra nada identificable hasta que el médico justifica el acceso."""
    paciente = get_object_or_404(Paciente, pk=pk)
    if acceso.tipo_de_acceso(request.user, paciente):
        return redirect('fichas:detalle', pk=pk)
    form = EmergenciaForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        acceso.abrir_emergencia(request.user, paciente, form.cleaned_data['motivo'])
        _registrar(paciente, request.user, AccesoFicha.Accion.EMERGENCIA)
        messages.success(request, 'Acceso de emergencia abierto por 2 horas. Queda registrado con tu motivo.')
        return redirect('fichas:detalle', pk=pk)
    return render(request, 'gestion_interna/fichas/emergencia.html', {
        'seccion': 'buscar', 'paciente': paciente, 'form': form,
        'horas': int(acceso.DURACION_EMERGENCIA.total_seconds() // 3600),
    })


PERIODOS = {'12m': ('Últimos 12 meses', 365), '5a': ('Últimos 5 años', 5 * 365), 'todo': ('Todo', None)}


@ver_ficha
def historial(request, pk):
    paciente, redireccion = autorizar_paciente(request, pk)
    if redireccion:
        return redireccion
    _registrar(paciente, request.user, AccesoFicha.Accion.CONSULTA)
    estado = request.GET.get('estado', '')
    periodo = request.GET.get('periodo', '12m')
    if periodo not in PERIODOS:
        periodo = '12m'
    consulta = request.GET.get('q', '').strip()

    diagnosticos = paciente.diagnosticos.select_related('medico')
    if estado in Diagnostico.Estado.values:
        diagnosticos = diagnosticos.filter(estado=estado)
    dias = PERIODOS[periodo][1]
    if dias:
        diagnosticos = diagnosticos.filter(fecha__gte=timezone.now() - timedelta(days=dias))
    lista = list(diagnosticos)
    if consulta:
        # Código, diagnóstico y tratamiento están cifrados: se filtra en memoria, sobre un solo paciente.
        palabras = _sin_tildes(consulta).split()
        lista = [
            d for d in lista
            if all(pal in _sin_tildes(f'{d.codigo_cie10} {d.diagnostico} {d.tratamiento}') for pal in palabras)
        ]
    return render(request, 'gestion_interna/fichas/historial.html', {
        'seccion': 'diagnosticos',
        'paciente': paciente, 'historial': getattr(paciente, 'historial', None),
        'cobertura': paciente.coberturas.select_related('prevision').first(),
        'diagnosticos': lista, 'q': consulta, 'estado': estado, 'periodo': periodo,
        'estados': Diagnostico.Estado.choices, 'periodos': [(k, v[0]) for k, v in PERIODOS.items()],
        'filtrado': bool(consulta or estado or periodo != '12m'),
    })


@editar_ficha
def nuevo_diagnostico(request, pk):
    paciente, redireccion = autorizar_paciente(request, pk)
    if redireccion:
        return redireccion
    form = DiagnosticoForm(request.POST or None, initial={'estado': Diagnostico.Estado.EN_TRATAMIENTO})
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            Diagnostico.objects.create(paciente=paciente, medico=request.user, **form.cleaned_data)
            _registrar(paciente, request.user, AccesoFicha.Accion.DIAGNOSTICO)
        messages.success(request, 'Diagnóstico registrado.')
        return redirect('fichas:historial', pk=paciente.pk)
    return render(request, 'gestion_interna/fichas/nuevo_diagnostico.html', {
        'seccion': 'diagnosticos',
        'paciente': paciente, 'historial': getattr(paciente, 'historial', None), 'form': form,
    })

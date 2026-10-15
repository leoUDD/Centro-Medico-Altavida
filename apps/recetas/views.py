from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.fichas_clinicas.bitacora import registrar_acceso
from apps.fichas_clinicas.models import AccesoFicha
from apps.pacientes.models import Paciente
from apps.usuarios.models import Usuario
from apps.usuarios.permisos import rol_requerido

from .alergias import en_conflicto, palabras_en_alerta
from .forms import ItemsFormSet, RecetaForm
from .models import ItemReceta, Receta

solo_medicos = rol_requerido(Usuario.Rol.MEDICO)
PREFIJO = 'items'


def _contexto_paciente(paciente):
    return {
        'seccion': 'recetas',
        'paciente': paciente,
        'historial': getattr(paciente, 'historial', None),
        'cobertura': paciente.coberturas.select_related('prevision').first(),
    }


def _items_activos(formset):
    return [f.cleaned_data for f in formset.forms if f.cleaned_data and not f.cleaned_data.get('DELETE')]


def _guardar(request, paciente, receta, form, items, emitir):
    with transaction.atomic():
        if receta is None:
            receta = Receta(paciente=paciente, medico=request.user)
        receta.diagnostico = form.cleaned_data['diagnostico']
        receta.indicaciones = form.cleaned_data['indicaciones']
        receta.save()
        receta.items.all().delete()
        ItemReceta.objects.bulk_create([
            ItemReceta(receta=receta, orden=n, medicamento=i['medicamento'], dosis=i['dosis'],
                       frecuencia=i['frecuencia'], duracion=i['duracion'], via=i['via'])
            for n, i in enumerate(items, start=1)
        ])
        if emitir:
            receta.estado = Receta.Estado.EMITIDA
            receta.emitida_en = timezone.now()
            receta.save(update_fields=['estado', 'emitida_en'])
            receta.firma = receta.calcular_firma()
            receta.save(update_fields=['firma'])
            registrar_acceso(paciente, request.user, AccesoFicha.Accion.RECETA)
    return receta


def _formulario(request, paciente, receta=None):
    historial = getattr(paciente, 'historial', None)
    palabras = palabras_en_alerta(historial.alergias if historial else '')
    if request.method == 'POST':
        form = RecetaForm(request.POST, paciente=paciente)
        formset = ItemsFormSet(request.POST, prefix=PREFIJO)
        emitir = request.POST.get('accion') == 'emitir'
        if form.is_valid() and formset.is_valid():
            items = _items_activos(formset)
            conflictos = [i['medicamento'] for i in items if en_conflicto(i['medicamento'], palabras)]
            error = None
            if emitir and not request.user.check_password(request.POST.get('clave', '')):
                error = 'La contraseña no es correcta. No se emitió la receta.'
            elif emitir and conflictos and not request.POST.get('confirmo_alergia'):
                error = ('Hay medicamentos de una familia a la que el paciente es alérgico '
                         f'({", ".join(conflictos)}). Confirma que lo revisaste para emitir.')
            if error:
                form.add_error(None, error)
            else:
                receta = _guardar(request, paciente, receta, form, items, emitir)
                if emitir:
                    messages.success(request, f'Receta {receta.folio} emitida y firmada.')
                    return redirect('recetas:detalle', pk=receta.pk)
                messages.success(request, 'Borrador guardado.')
                return redirect('recetas:editar', pk=receta.pk)
    elif receta is not None:
        form = RecetaForm(
            paciente=paciente, initial={'diagnostico': receta.diagnostico_id, 'indicaciones': receta.indicaciones},
        )
        formset = ItemsFormSet(prefix=PREFIJO, initial=[i.como_dict() for i in receta.items.all()])
    else:
        form = RecetaForm(paciente=paciente)
        formset = ItemsFormSet(prefix=PREFIJO, initial=[{'via': ItemReceta.Via.ORAL}])
    return render(request, 'gestion_interna/recetas/formulario.html', {
        **_contexto_paciente(paciente), 'form': form, 'formset': formset, 'receta': receta,
        'palabras_alerta': palabras, 'hoy': timezone.localdate(),
        'sin_diagnosticos': not paciente.diagnosticos.exists(),
    })


@solo_medicos
def nueva(request, paciente_pk):
    paciente = get_object_or_404(Paciente, pk=paciente_pk)
    return _formulario(request, paciente)


@solo_medicos
def editar(request, pk):
    receta = get_object_or_404(Receta.objects.select_related('paciente', 'diagnostico'), pk=pk)
    if receta.emitida or receta.medico_id != request.user.pk:
        return redirect('recetas:detalle', pk=receta.pk)
    return _formulario(request, receta.paciente, receta)


@solo_medicos
def detalle(request, pk):
    receta = get_object_or_404(Receta.objects.select_related('paciente', 'medico', 'diagnostico'), pk=pk)
    registrar_acceso(receta.paciente, request.user, AccesoFicha.Accion.CONSULTA)
    return render(request, 'gestion_interna/recetas/detalle.html', {
        **_contexto_paciente(receta.paciente), 'receta': receta, 'items': receta.items.all(),
    })

from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.pacientes.views import paciente_de, solo_pacientes

from .models import Notificacion, PreferenciasNotificacion

FILTROS = {'': None, 'sin-leer': None, 'citas': Notificacion.Tipo.CITA, 'resultados': Notificacion.Tipo.RESULTADO}
CAMPOS_PREFERENCIAS = ['canal_correo', 'canal_sms', 'recordar_48h', 'recordar_24h', 'recordar_2h']


@solo_pacientes
def lista(request):
    paciente = paciente_de(request)
    filtro = request.GET.get('f', '')
    if filtro not in FILTROS:
        filtro = ''
    todas = paciente.notificaciones.select_related('cita')
    avisos = todas
    if filtro == 'sin-leer':
        avisos = todas.filter(leida=False)
    elif FILTROS[filtro]:
        avisos = todas.filter(tipo=FILTROS[filtro])
    return render(request, 'portal_paciente/notificaciones.html', {
        'seccion': 'notificaciones',
        'paciente': paciente,
        'avisos': avisos,
        'filtro': filtro,
        'sin_leer': todas.filter(leida=False).count(),
        'ahora': timezone.now(),
        'preferencias': PreferenciasNotificacion.para(paciente),
    })


@solo_pacientes
@require_POST
def marcar_todas(request):
    paciente_de(request).notificaciones.filter(leida=False).update(leida=True)
    return redirect('notificaciones:lista')


@solo_pacientes
@require_POST
def guardar_preferencias(request):
    preferencias = PreferenciasNotificacion.para(paciente_de(request))
    for campo in CAMPOS_PREFERENCIAS:
        setattr(preferencias, campo, campo in request.POST)
    preferencias.save()
    messages.success(request, 'Preferencias guardadas.')
    return redirect('notificaciones:lista')

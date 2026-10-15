from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import LoginForm, RegistroPacienteForm

INICIO_POR_ROL = {
    'MEDICO': 'fichas:buscar',
    'PACIENTE': 'pacientes:resultados',
    'ADMINISTRATIVO': 'recepcion:dashboard',
}


def login_vista(request):
    if request.user.is_authenticated:
        return redirect('inicio')
    form = LoginForm(request.POST or None)
    error = None
    if request.method == 'POST' and form.is_valid():
        usuario = authenticate(request, username=form.cleaned_data['usuario'], password=form.cleaned_data['clave'])
        if usuario is not None:
            login(request, usuario)
            destino = request.POST.get('next', '')
            if destino and url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}):
                return redirect(destino)
            return redirect('inicio')
        error = 'Las credenciales no son correctas.'
    return render(request, 'cuentas/login.html', {'form': form, 'error': error, 'next': request.GET.get('next', '')})


@require_POST
def logout_vista(request):
    logout(request)
    return redirect('login')


def registro_vista(request):
    if request.user.is_authenticated:
        return redirect('inicio')
    form = RegistroPacienteForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            usuario = form.guardar()
        login(request, usuario)
        return redirect('inicio')
    return render(request, 'cuentas/registro.html', {'form': form})


@login_required
def inicio(request):
    return redirect(INICIO_POR_ROL[request.user.rol])

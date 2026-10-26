from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST

from apps.seguridad import intentos

from .forms import LoginForm, RegistroPacienteForm

INICIO_POR_ROL = {
    'MEDICO': 'fichas:buscar',
    'PACIENTE': 'pacientes:resultados',
    'ADMINISTRATIVO': 'recepcion:dashboard',
    'ADMIN_SISTEMA': 'admin:index',
}


@sensitive_post_parameters('clave')
def login_vista(request):
    if request.user.is_authenticated:
        return redirect('inicio')
    form = LoginForm(request.POST or None)
    error = None
    status = 200
    if request.method == 'POST' and form.is_valid():
        identificador = form.cleaned_data['usuario']
        if intentos.bloqueado(request, identificador):
            return render(request, 'cuentas/login.html', {
                'form': form, 'error': 'Demasiados intentos fallidos. Espera unos minutos e inténtalo de nuevo.',
                'next': request.GET.get('next', ''),
            }, status=429)
        usuario = authenticate(request, username=identificador, password=form.cleaned_data['clave'])
        if usuario is not None:
            intentos.limpiar(request, identificador)
            login(request, usuario)
            destino = request.POST.get('next', '')
            if destino and url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}):
                return redirect(destino)
            return redirect('inicio')
        intentos.registrar_fallo(request, identificador)
        error = 'Las credenciales no son correctas.'
    return render(request, 'cuentas/login.html', {'form': form, 'error': error, 'next': request.GET.get('next', '')}, status=status)


@require_POST
def logout_vista(request):
    logout(request)
    return redirect('login')


@sensitive_post_parameters('clave', 'clave2')
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

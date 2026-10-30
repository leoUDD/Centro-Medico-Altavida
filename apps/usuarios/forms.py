import secrets

from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from apps.consentimientos import servicio as consentimientos
from apps.pacientes.models import Paciente
from apps.seguridad.indice import indice_correo, indice_rut
from apps.seguridad.rut import normalizar_rut, rut_valido


class LoginForm(forms.Form):
    usuario = forms.CharField(label='Correo electrónico o RUT')
    clave = forms.CharField(label='Contraseña', widget=forms.PasswordInput)


class RegistroPacienteForm(forms.Form):
    nombres = forms.CharField(label='Nombres', max_length=100)
    apellidos = forms.CharField(label='Apellidos', max_length=100)
    rut = forms.CharField(label='RUT', max_length=12)
    fecha_nacimiento = forms.DateField(label='Fecha de nacimiento', widget=forms.DateInput(attrs={'type': 'date'}))
    email = forms.EmailField(label='Correo electrónico')
    telefono = forms.CharField(label='Teléfono celular', max_length=20)
    clave = forms.CharField(label='Contraseña', widget=forms.PasswordInput)
    clave2 = forms.CharField(label='Repite la contraseña', widget=forms.PasswordInput)
    # No es un consentimiento: la atención clínica no depende de él (Hito 1). Solo deja constancia de que se informó.
    aviso_privacidad = forms.BooleanField(
        label='Leí el aviso de privacidad',
        error_messages={'required': 'Debes confirmar que leíste el aviso de privacidad para crear la cuenta.'},
    )
    # Consentimientos opcionales, uno por canal y sin marcar de antemano.
    recordatorios_correo = forms.BooleanField(label='Recordatorios de citas por correo', required=False)
    recordatorios_sms = forms.BooleanField(label='Recordatorios de citas por SMS', required=False)

    def clean_fecha_nacimiento(self):
        nacimiento = self.cleaned_data['fecha_nacimiento']
        hoy = timezone.localdate()
        edad = hoy.year - nacimiento.year - ((hoy.month, hoy.day) < (nacimiento.month, nacimiento.day))
        if edad < consentimientos.EDAD_CONSENTIMIENTO_PROPIO:
            raise forms.ValidationError(
                'Las cuentas de menores de edad las crea su representante legal en recepción, con documento.')
        return nacimiento

    def clean_rut(self):
        rut = self.cleaned_data['rut']
        if not rut_valido(rut):
            raise forms.ValidationError('El RUT no es válido. Revisa el dígito verificador.')
        indice = indice_rut(rut)
        if Paciente.objects.filter(identidad__rut_indice=indice).exists() or get_user_model().objects.filter(rut_indice=indice).exists():
            raise forms.ValidationError('Ya existe una cuenta con este RUT.')
        return normalizar_rut(rut)

    def clean_email(self):
        email = self.cleaned_data['email']
        if get_user_model().objects.filter(correo_indice=indice_correo(email)).exists():
            raise forms.ValidationError('Ya existe una cuenta con este correo.')
        return email

    def clean(self):
        datos = super().clean()
        clave, clave2 = datos.get('clave'), datos.get('clave2')
        if clave and clave2 and clave != clave2:
            self.add_error('clave2', 'Las contraseñas no coinciden.')
        elif clave:
            try:
                password_validation.validate_password(clave)
            except forms.ValidationError as error:
                self.add_error('clave', error)
        return datos

    @sensitive_variables()
    def guardar(self):
        datos = self.cleaned_data
        Usuario = get_user_model()
        # La cuenta no lleva datos personales: usuario aleatorio, sin nombre ni correo en claro.
        # Lo identificable vive cifrado en IdentidadPaciente; aquí solo hay índices ciegos para poder iniciar sesión.
        usuario = Usuario.objects.create_user(
            username='p_' + secrets.token_hex(8), password=datos['clave'], rol=Usuario.Rol.PACIENTE,
            rut_indice=indice_rut(datos['rut']), correo_indice=indice_correo(datos['email']),
        )
        paciente = Paciente.objects.create(
            usuario=usuario, rut=datos['rut'], nombres=datos['nombres'], apellidos=datos['apellidos'],
            fecha_nacimiento=datos['fecha_nacimiento'].isoformat(), email=datos['email'],
            telefono=datos['telefono'],
        )
        consentimientos.acusar_aviso(paciente, 1)
        for campo, codigo in (('recordatorios_correo', consentimientos.RECORDATORIOS_CORREO),
                              ('recordatorios_sms', consentimientos.RECORDATORIOS_SMS)):
            if datos[campo]:
                consentimientos.otorgar(paciente, codigo, usuario)
        return usuario

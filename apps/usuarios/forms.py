from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.utils import timezone

from apps.pacientes.models import Paciente
from apps.seguridad.indice import indice_rut
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
    consentimiento_datos = forms.BooleanField(
        label='Autorizo el tratamiento de mis datos personales y de salud',
        error_messages={'required': 'Debes autorizar el tratamiento de tus datos para crear la cuenta.'},
    )
    recordatorios = forms.BooleanField(label='Quiero recibir recordatorios de citas', required=False)

    def clean_rut(self):
        rut = self.cleaned_data['rut']
        if not rut_valido(rut):
            raise forms.ValidationError('El RUT no es válido. Revisa el dígito verificador.')
        indice = indice_rut(rut)
        if Paciente.objects.filter(rut_indice=indice).exists() or get_user_model().objects.filter(rut_indice=indice).exists():
            raise forms.ValidationError('Ya existe una cuenta con este RUT.')
        return normalizar_rut(rut)

    def clean_email(self):
        email = self.cleaned_data['email']
        if get_user_model().objects.filter(email__iexact=email).exists():
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

    def guardar(self):
        datos = self.cleaned_data
        Usuario = get_user_model()
        usuario = Usuario.objects.create_user(
            username=datos['email'], email=datos['email'], password=datos['clave'],
            first_name=datos['nombres'], last_name=datos['apellidos'],
            rol=Usuario.Rol.PACIENTE, rut_indice=indice_rut(datos['rut']),
        )
        Paciente.objects.create(
            usuario=usuario, rut=datos['rut'], nombres=datos['nombres'], apellidos=datos['apellidos'],
            fecha_nacimiento=datos['fecha_nacimiento'].isoformat(), email=datos['email'],
            telefono=datos['telefono'], consentimiento_datos=True, consentimiento_fecha=timezone.now(),
            recordatorios_activos=datos['recordatorios'],
        )
        return usuario

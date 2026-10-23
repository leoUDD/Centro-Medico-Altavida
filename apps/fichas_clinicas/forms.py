import re

from django import forms

from apps.convenios.models import Prevision
from apps.pacientes.models import Paciente
from apps.seguridad.indice import indice_rut
from apps.seguridad.rut import normalizar_rut, rut_valido

from .models import Diagnostico

SEXOS = [('', 'No informa'), ('F', 'Femenino'), ('M', 'Masculino')]
GRUPOS = [('', 'Desconocido')] + [(g, g) for g in ('O+', 'O-', 'A+', 'A-', 'B+', 'B-', 'AB+', 'AB-')]


def _area(label, **kwargs):
    return forms.CharField(label=label, widget=forms.Textarea(attrs={'rows': 3}), **kwargs)


class NuevaFichaForm(forms.Form):
    nombres = forms.CharField(label='Nombres', max_length=100)
    apellidos = forms.CharField(label='Apellidos', max_length=100)
    rut = forms.CharField(label='RUT', max_length=12)
    fecha_nacimiento = forms.DateField(label='Fecha de nacimiento', widget=forms.DateInput(attrs={'type': 'date'}))
    sexo = forms.ChoiceField(label='Sexo registral', choices=SEXOS, required=False)
    prevision = forms.ModelChoiceField(label='Previsión', queryset=Prevision.objects.none(), empty_label='Selecciona')

    email = forms.EmailField(label='Correo electrónico', required=False)
    telefono = forms.CharField(label='Teléfono', max_length=20)

    grupo_sanguineo = forms.ChoiceField(label='Grupo sanguíneo', choices=GRUPOS, required=False)
    peso = forms.DecimalField(label='Peso (kg)', required=False, min_value=0, max_value=500, decimal_places=1)
    estatura = forms.DecimalField(label='Talla (cm)', required=False, min_value=0, max_value=300, decimal_places=1)
    alergias = _area('Alergias')
    enfermedades = _area('Enfermedades crónicas', required=False)
    medicamentos_activos = _area('Medicamentos de uso habitual', required=False)
    operaciones = _area('Antecedentes quirúrgicos y familiares', required=False)

    contacto_emergencia_nombre = forms.CharField(label='Nombre', max_length=150, required=False)
    contacto_emergencia_parentesco = forms.CharField(label='Parentesco', max_length=60, required=False)
    contacto_emergencia_telefono = forms.CharField(label='Teléfono', max_length=20, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['prevision'].queryset = Prevision.objects.filter(activo=True).order_by('id')

    def clean_rut(self):
        rut = self.cleaned_data['rut']
        if not rut_valido(rut):
            raise forms.ValidationError('El RUT no es válido. Revisa el dígito verificador.')
        if Paciente.objects.filter(identidad__rut_indice=indice_rut(rut)).exists():
            raise forms.ValidationError('Ya existe una ficha para este RUT.')
        return normalizar_rut(rut)


class DiagnosticoForm(forms.Form):
    codigo_cie10 = forms.CharField(label='Código CIE-10', max_length=8)
    diagnostico = forms.CharField(label='Diagnóstico', max_length=300)
    tratamiento = _area('Tratamiento', required=False)
    estado = forms.ChoiceField(label='Estado', choices=Diagnostico.Estado.choices)

    def clean_codigo_cie10(self):
        codigo = self.cleaned_data['codigo_cie10'].strip().upper()
        if not re.fullmatch(r'[A-Z]\d{2}(\.\d{1,2})?', codigo):
            raise forms.ValidationError('Usa el formato CIE-10, por ejemplo E11.9 o J06.')
        return codigo


class EmergenciaForm(forms.Form):
    motivo = forms.CharField(
        label='Motivo del acceso', min_length=15, max_length=500, widget=forms.Textarea(attrs={'rows': 3}),
        error_messages={'min_length': 'Describe la urgencia con al menos 15 caracteres.'},
    )

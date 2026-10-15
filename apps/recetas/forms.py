from django import forms
from django.forms import formset_factory

from apps.fichas_clinicas.models import Diagnostico

from .models import ItemReceta


class RecetaForm(forms.Form):
    diagnostico = forms.ModelChoiceField(
        label='Diagnóstico asociado (CIE-10)', queryset=Diagnostico.objects.none(), empty_label='Selecciona un diagnóstico',
        error_messages={'required': 'Selecciona el diagnóstico al que corresponde la receta.'},
    )
    indicaciones = forms.CharField(label='Indicaciones generales', required=False, widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, paciente, **kwargs):
        super().__init__(*args, **kwargs)
        campo = self.fields['diagnostico']
        campo.queryset = paciente.diagnosticos.select_related('medico')
        campo.label_from_instance = lambda d: f'{d.codigo_cie10 or "s/c"} · {d.diagnostico}'


class ItemRecetaForm(forms.Form):
    medicamento = forms.CharField(label='Medicamento y concentración', max_length=200)
    dosis = forms.CharField(label='Dosis', max_length=100)
    frecuencia = forms.CharField(label='Frecuencia', max_length=100)
    duracion = forms.CharField(label='Duración', max_length=100)
    via = forms.ChoiceField(label='Vía', choices=ItemReceta.Via.choices)


ItemsFormSet = formset_factory(
    ItemRecetaForm, extra=0, min_num=1, validate_min=True, can_delete=True, absolute_max=20, max_num=20, validate_max=True,
)

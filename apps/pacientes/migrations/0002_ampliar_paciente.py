import apps.seguridad.campos
from django.db import migrations, models

from apps.seguridad.indice import indice_rut


def migrar_datos(apps, schema_editor):
    Paciente = apps.get_model('pacientes', 'Paciente')
    for paciente in Paciente.objects.all():
        paciente.nombres = paciente.nombre
        paciente.rut_indice = indice_rut(paciente.rut)
        paciente.save(update_fields=['nombres', 'rut_indice'])


class Migration(migrations.Migration):

    dependencies = [
        ('pacientes', '0001_initial'),
    ]

    operations = [
        migrations.AddField('paciente', 'nombres', apps.seguridad.campos.CampoCifrado(default=''), preserve_default=False),
        migrations.AddField('paciente', 'apellidos', apps.seguridad.campos.CampoCifrado(default=''), preserve_default=False),
        migrations.AddField('paciente', 'rut_indice', models.CharField(max_length=64, null=True, editable=False)),
        migrations.AddField('paciente', 'grupo_sanguineo', apps.seguridad.campos.CampoCifrado(blank=True, default=''), preserve_default=False),
        migrations.AddField('paciente', 'comuna', apps.seguridad.campos.CampoCifrado(blank=True, default=''), preserve_default=False),
        migrations.AddField('paciente', 'contacto_emergencia_nombre', apps.seguridad.campos.CampoCifrado(blank=True, default=''), preserve_default=False),
        migrations.AddField('paciente', 'contacto_emergencia_parentesco', apps.seguridad.campos.CampoCifrado(blank=True, default=''), preserve_default=False),
        migrations.AddField('paciente', 'contacto_emergencia_telefono', apps.seguridad.campos.CampoCifrado(blank=True, default=''), preserve_default=False),
        migrations.AddField('paciente', 'consentimiento_datos', models.BooleanField(default=False)),
        migrations.AddField('paciente', 'consentimiento_fecha', models.DateTimeField(blank=True, null=True)),
        migrations.AddField('paciente', 'recordatorios_activos', models.BooleanField(default=False)),
        migrations.AlterField('paciente', 'sexo', apps.seguridad.campos.CampoCifrado(blank=True)),
        migrations.RunPython(migrar_datos, migrations.RunPython.noop),
        migrations.RemoveField('paciente', 'nombre'),
        migrations.AlterField('paciente', 'rut_indice', models.CharField(max_length=64, unique=True, editable=False)),
    ]

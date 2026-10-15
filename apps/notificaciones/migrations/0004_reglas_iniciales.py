from django.db import migrations

# (horas antes, activa, correo, sms, con confirmación) — las del diseño del dashboard administrativo.
REGLAS = [(48, True, True, False, False), (24, True, True, True, True), (2, False, False, True, False)]


def crear_reglas(apps, schema_editor):
    Regla = apps.get_model('notificaciones', 'ReglaRecordatorio')
    for horas, activa, correo, sms, confirmacion in REGLAS:
        Regla.objects.get_or_create(
            horas_antes=horas,
            defaults={'activa': activa, 'canal_correo': correo, 'canal_sms': sms, 'con_confirmacion': confirmacion},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('notificaciones', '0003_reglarecordatorio_ejecucionrecordatorios_and_more'),
    ]

    operations = [
        migrations.RunPython(crear_reglas, migrations.RunPython.noop),
    ]

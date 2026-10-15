from django.db import migrations

PREVISIONES = [('Fonasa', 'FONASA'), ('Isapre', 'ISAPRE'), ('Particular', 'PARTICULAR')]


def crear_previsiones(apps, schema_editor):
    Prevision = apps.get_model('convenios', 'Prevision')
    for nombre, tipo in PREVISIONES:
        Prevision.objects.get_or_create(nombre=nombre, defaults={'tipo': tipo})


class Migration(migrations.Migration):

    dependencies = [
        ('convenios', '0002_alter_prevision_tipo'),
    ]

    operations = [
        migrations.RunPython(crear_previsiones, migrations.RunPython.noop),
    ]

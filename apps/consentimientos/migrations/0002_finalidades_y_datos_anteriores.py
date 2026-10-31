from django.db import migrations
from django.utils import timezone

TEXTO_CORREO = (
    'Autorizo a Centro Médico Altavida a enviarme por correo electrónico recordatorios de mis citas médicas. '
    'Para esto se usa solo mi correo, mi nombre de pila, la fecha y hora de la cita y el nombre del profesional; '
    'nunca diagnósticos ni datos clínicos. Puedo retirar esta autorización cuando quiera desde Mis consentimientos, '
    'sin que eso afecte mi atención ni mis citas.'
)
TEXTO_SMS = (
    'Autorizo a Centro Médico Altavida a enviarme por SMS recordatorios de mis citas médicas. '
    'Para esto se usa solo mi número de teléfono, mi nombre de pila, la fecha y hora de la cita y el nombre del '
    'profesional; nunca diagnósticos ni datos clínicos. Puedo retirar esta autorización cuando quiera desde Mis '
    'consentimientos, sin que eso afecte mi atención ni mis citas.'
)


def cargar(apps, schema_editor):
    import hashlib
    Finalidad = apps.get_model('consentimientos', 'Finalidad')
    Texto = apps.get_model('consentimientos', 'TextoConsentimiento')
    Consentimiento = apps.get_model('consentimientos', 'Consentimiento')
    Registro = apps.get_model('consentimientos', 'RegistroConsentimiento')
    Paciente = apps.get_model('pacientes', 'Paciente')

    definiciones = [
        ('RECORDATORIOS_CORREO', 'Recordatorios de citas por correo', 'CORREO', 'Correo electrónico', TEXTO_CORREO),
        ('RECORDATORIOS_SMS', 'Recordatorios de citas por SMS', 'SMS', 'Número de teléfono', TEXTO_SMS),
    ]
    textos = {}
    for codigo, nombre, canal, dato, texto in definiciones:
        finalidad, _ = Finalidad.objects.get_or_create(codigo=codigo, defaults={
            'nombre': nombre, 'canal': canal, 'dato_usado': dato,
            'descripcion': 'Avisarte de tus próximas citas para que no las olvides.',
        })
        textos[codigo], _ = Texto.objects.get_or_create(finalidad=finalidad, version=1, defaults={
            'texto': texto, 'huella': hashlib.sha256(texto.encode('utf-8')).hexdigest(),
        })

    # Datos del modelo anterior: la casilla del registro pasa a ser acuse del aviso (consentimiento_datos) y los
    # recordatorios activos pasan a ser un consentimiento por canal, marcado como migrado.
    for paciente in Paciente.objects.filter(consentimiento_datos=True):
        fecha = paciente.consentimiento_fecha or timezone.now()
        paciente.aviso_privacidad_version, paciente.aviso_privacidad_en = 1, fecha
        paciente.save(update_fields=['aviso_privacidad_version', 'aviso_privacidad_en'])
        if not paciente.recordatorios_activos:
            continue
        for codigo, texto in textos.items():
            Consentimiento.objects.get_or_create(paciente=paciente, finalidad=texto.finalidad, defaults={
                'texto': texto, 'estado': 'OTORGADO', 'otorgado_en': fecha, 'otorgante': 'TITULAR',
            })
            Registro.objects.create(
                paciente=paciente, finalidad=texto.finalidad, texto=texto, accion='OTORGADO', fecha=fecha,
                otorgante='TITULAR', canal='MIGRACION',
            )


class Migration(migrations.Migration):
    dependencies = [
        ('consentimientos', '0001_initial'),
        ('pacientes', '0004_paciente_aviso_privacidad_en_and_more'),
    ]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]

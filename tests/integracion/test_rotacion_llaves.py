import base64
import io

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.pacientes.models import Paciente


def nueva_llave(byte):
    return base64.urlsafe_b64encode(bytes([byte]) * 32).decode()


class RotacionDeLlavesTests(TestCase):
    def test_el_comando_reescribe_los_datos_con_la_llave_nueva(self):
        paciente = Paciente.objects.create(rut='12.345.678-5', nombres='Ana', apellidos='Pérez', sexo='F')
        actuales = settings.LLAVES_CIFRADO
        durante = {
            'clinica': {'actual': nueva_llave(3), 'anterior': actuales['clinica']['actual']},
            'identidad': {'actual': nueva_llave(4), 'anterior': actuales['identidad']['actual']},
        }
        with override_settings(LLAVES_CIFRADO=durante):
            salida = io.StringIO()
            call_command('rotar_llaves', stdout=salida)
            self.assertIn('registros reescritos', salida.getvalue())
        despues = {'clinica': {'actual': nueva_llave(3), 'anterior': ''}, 'identidad': {'actual': nueva_llave(4), 'anterior': ''}}
        with override_settings(LLAVES_CIFRADO=despues):
            recuperado = Paciente.objects.get(pk=paciente.pk)
            self.assertEqual((recuperado.sexo, recuperado.rut, recuperado.nombre_completo), ('F', '12.345.678-5', 'Ana Pérez'))

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


class MigracionDelFormatoAnteriorTests(TestCase):
    """Datos cifrados antes del refuerzo: sin id de llave y sin datos asociados (AAD)."""

    def token_antiguo(self, texto):
        import os
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        nonce = os.urandom(12)
        llave = base64.urlsafe_b64decode(settings.CLAVE_CIFRADO)
        return base64.urlsafe_b64encode(nonce + AESGCM(llave).encrypt(nonce, texto.encode(), None)).decode()

    def test_sin_la_opcion_el_formato_anterior_se_rechaza_con_un_mensaje_claro(self):
        from apps.seguridad.cifrado import LlaveDesconocida, descifrar
        with self.assertRaisesRegex(LlaveDesconocida, 'rotar_llaves'):
            descifrar(self.token_antiguo('dato'), 'pacientes.paciente.sexo')

    @override_settings(CIFRADO_FORMATO_ANTERIOR=True)
    def test_rotar_llaves_migra_los_datos_al_formato_actual(self):
        from django.db import connection
        from apps.seguridad.cifrado import identificador_de
        paciente = Paciente.objects.create(rut='12.345.678-5', nombres='Ana', apellidos='Pérez')
        with connection.cursor() as cursor:
            cursor.execute('UPDATE pacientes_paciente SET sexo = %s WHERE id = %s', [self.token_antiguo('F'), paciente.pk])
        self.assertEqual(Paciente.objects.get(pk=paciente.pk).sexo, 'F')
        call_command('rotar_llaves', stdout=io.StringIO())
        with connection.cursor() as cursor:
            cursor.execute('SELECT sexo FROM pacientes_paciente WHERE id = %s', [paciente.pk])
            guardado = cursor.fetchone()[0]
        self.assertRegex(identificador_de(guardado), r'^[0-9a-f]{8}$')
        with override_settings(CIFRADO_FORMATO_ANTERIOR=False):
            self.assertEqual(Paciente.objects.get(pk=paciente.pk).sexo, 'F')

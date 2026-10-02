from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase

from apps.pacientes.models import Paciente


class CamposCifradosTests(TestCase):
    def test_en_la_base_de_datos_el_rut_esta_cifrado(self):
        paciente = Paciente.objects.create(
            rut='12.345.678-9', nombre='Ana Pérez', fecha_nacimiento='1990-05-01', sexo='F',
        )
        with connection.cursor() as cursor:
            cursor.execute('SELECT rut, nombre FROM pacientes_paciente WHERE id = %s', [paciente.pk])
            rut_guardado, nombre_guardado = cursor.fetchone()
        self.assertNotIn('12.345.678-9', rut_guardado)
        self.assertNotIn('Ana', nombre_guardado)

    def test_al_leer_por_el_orm_se_recupera_el_dato(self):
        paciente = Paciente.objects.create(
            rut='12.345.678-9', nombre='Ana Pérez', fecha_nacimiento='1990-05-01', sexo='F',
        )
        recuperado = Paciente.objects.get(pk=paciente.pk)
        self.assertEqual(recuperado.rut, '12.345.678-9')
        self.assertEqual(recuperado.nombre, 'Ana Pérez')


class HashContrasenaTests(TestCase):
    def test_la_contrasena_se_guarda_con_argon2(self):
        usuario = get_user_model().objects.create_user('medico1', password='Clave-Segura-123')
        self.assertTrue(usuario.password.startswith('argon2$'))
        self.assertTrue(usuario.check_password('Clave-Segura-123'))
        self.assertFalse(usuario.check_password('otra-clave'))

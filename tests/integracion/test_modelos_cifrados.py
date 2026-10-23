from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase

from apps.pacientes.models import IdentidadPaciente, Paciente


def crudo(tabla, columnas, pk):
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT {columnas} FROM {tabla} WHERE id = %s', [pk])
        return cursor.fetchone()


class CamposCifradosTests(TestCase):
    def crear(self):
        return Paciente.objects.create(
            rut='12.345.678-9', nombres='Ana', apellidos='Pérez', fecha_nacimiento='1990-05-01', sexo='F',
            email='ana@correo.cl', telefono='+56 9 1234 5678',
        )

    def test_en_la_base_de_datos_la_identidad_esta_cifrada(self):
        paciente = self.crear()
        rut, nombres, correo, telefono = crudo(
            'pacientes_identidadpaciente', 'rut, nombres, email, telefono', paciente.identidad.pk,
        )
        for guardado, original in ((rut, '12.345.678-9'), (nombres, 'Ana'), (correo, 'ana@correo.cl'), (telefono, '1234')):
            self.assertNotIn(original, guardado)

    def test_la_tabla_del_paciente_no_contiene_datos_que_lo_identifiquen(self):
        paciente = self.crear()
        columnas = [c.name for c in connection.introspection.get_table_description(connection.cursor(), 'pacientes_paciente')]
        for identificador in ('rut', 'nombres', 'apellidos', 'email', 'telefono', 'fecha_nacimiento', 'direccion', 'comuna'):
            self.assertNotIn(identificador, columnas)
        self.assertTrue(paciente.codigo.startswith('P'))
        self.assertNotIn('Ana', paciente.codigo)

    def test_al_leer_por_el_orm_se_recupera_el_dato(self):
        paciente = self.crear()
        recuperado = Paciente.objects.get(pk=paciente.pk)
        self.assertEqual(recuperado.rut, '12.345.678-9')
        self.assertEqual(recuperado.nombre_completo, 'Ana Pérez')
        self.assertEqual(recuperado.sexo, 'F')

    def test_el_indice_ciego_permite_buscar_sin_descifrar(self):
        paciente = self.crear()
        self.assertEqual(Paciente.objects.get(identidad__rut_indice=IdentidadPaciente.objects.get().rut_indice), paciente)

    def test_borrar_la_identidad_deja_al_paciente_anonimo(self):
        paciente = self.crear()
        paciente.identidad.delete()
        paciente = Paciente.objects.get(pk=paciente.pk)
        self.assertEqual((paciente.nombre_completo, paciente.rut, paciente.email), ('', '', ''))


class HashContrasenaTests(TestCase):
    def test_la_contrasena_se_guarda_con_argon2(self):
        usuario = get_user_model().objects.create_user('medico1', password='Clave-Segura-123')
        self.assertTrue(usuario.password.startswith('argon2$'))
        self.assertTrue(usuario.check_password('Clave-Segura-123'))
        self.assertFalse(usuario.check_password('otra-clave'))

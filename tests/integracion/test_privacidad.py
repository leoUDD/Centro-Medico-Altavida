from django.conf import settings
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from apps.convenios.models import Prevision
from apps.pacientes.models import Paciente
from apps.seguridad.cifrado import identificador_de
from apps.usuarios.models import Usuario

CLAVE = 'Clave-Muy-Segura-123'


class SeudonimizacionTests(TestCase):
    def test_las_tablas_clinicas_apuntan_al_paciente_no_a_su_identidad(self):
        for tabla in ('fichas_clinicas_diagnostico', 'recetas_receta', 'laboratorio_resultadoexamen', 'agenda_cita',
                      'notificaciones_notificacion', 'laboratorio_ordenexamen'):
            columnas = [c.name for c in connection.introspection.get_table_description(connection.cursor(), tabla)]
            self.assertIn('paciente_id', columnas, tabla)
            self.assertFalse({'rut', 'nombres', 'apellidos', 'email', 'telefono'} & set(columnas), tabla)

    def test_la_cuenta_del_paciente_no_guarda_datos_personales_en_claro(self):
        usuario = Usuario.objects.create_user('p_abc', password=CLAVE, rol='PACIENTE')
        Paciente.objects.create(usuario=usuario, rut='15482331K', nombres='María José', apellidos='Fuentes', email='maria@correo.cl')
        with connection.cursor() as cursor:
            cursor.execute('SELECT * FROM usuarios_usuario')
            fila = ' '.join(str(v) for v in cursor.fetchone())
        for dato in ('María', 'Fuentes', 'maria@correo.cl', '15482331'):
            self.assertNotIn(dato, fila)
        self.assertEqual(Usuario.objects.get().nombre_visible, 'María')

    def test_el_codigo_es_aleatorio_y_unico(self):
        codigos = {Paciente.objects.create(rut=f'1000000{i}', nombres='A', apellidos='B').codigo for i in range(5)}
        self.assertEqual(len(codigos), 5)

    def test_la_identidad_usa_una_llave_distinta_de_la_clinica(self):
        paciente = Paciente.objects.create(rut='12.345.678-5', nombres='Ana', apellidos='Pérez', sexo='F')
        with connection.cursor() as cursor:
            cursor.execute('SELECT rut FROM pacientes_identidadpaciente WHERE id = %s', [paciente.identidad.pk])
            kid_identidad = identificador_de(cursor.fetchone()[0])
            cursor.execute('SELECT sexo FROM pacientes_paciente WHERE id = %s', [paciente.pk])
            kid_clinica = identificador_de(cursor.fetchone()[0])
        self.assertNotEqual(kid_identidad, kid_clinica)

    def test_las_tres_llaves_son_distintas(self):
        self.assertEqual(len({settings.CLAVE_CIFRADO, settings.CLAVE_IDENTIDAD, settings.CLAVE_INDICES}), 3)


class MinimizacionTests(TestCase):
    def test_se_eliminaron_los_campos_innecesarios(self):
        columnas = lambda tabla: {c.name for c in connection.introspection.get_table_description(connection.cursor(), tabla)}  # noqa: E731
        self.assertNotIn('direccion', columnas('pacientes_identidadpaciente'))
        self.assertNotIn('comuna', columnas('pacientes_identidadpaciente'))
        self.assertNotIn('datos_cobertura', columnas('convenios_cobertura'))
        self.assertNotIn('medicamentos', columnas('fichas_clinicas_diagnostico'))
        self.assertNotIn('canal_navegador', columnas('notificaciones_preferenciasnotificacion'))

    def test_la_ficha_se_puede_crear_sin_los_datos_opcionales(self):
        medico = Usuario.objects.create_user('med', email='med@c.cl', password=CLAVE, rol='MEDICO')
        self.client.force_login(medico)
        datos = {
            'nombres': 'Luis', 'apellidos': 'Soto', 'rut': '12.345.678-5', 'fecha_nacimiento': '1980-01-02',
            'prevision': Prevision.objects.get(nombre='Fonasa').pk, 'telefono': '+56 9 1111 2222', 'alergias': 'Ninguna conocida',
        }
        self.client.post(reverse('fichas:nueva'), datos)
        paciente = Paciente.objects.get()
        self.assertEqual((paciente.sexo, paciente.grupo_sanguineo, paciente.peso, paciente.estatura, paciente.email), ('',) * 5)

    def test_el_formulario_no_pide_direccion_ni_comuna(self):
        self.client.force_login(Usuario.objects.create_user('med', email='med@c.cl', password=CLAVE, rol='MEDICO'))
        r = self.client.get(reverse('fichas:nueva'))
        self.assertNotContains(r, 'Dirección')
        self.assertNotContains(r, 'Comuna')

    def test_las_pantallas_no_muestran_la_fecha_de_nacimiento_solo_la_edad(self):
        medico = Usuario.objects.create_user('med', email='med@c.cl', password=CLAVE, rol='MEDICO')
        paciente = Paciente.objects.create(rut='12.345.678-5', nombres='Ana', apellidos='Pérez', fecha_nacimiento='1980-01-02', creado_por=medico)
        self.client.force_login(medico)
        r = self.client.get(reverse('fichas:detalle', args=[paciente.pk]))
        self.assertNotContains(r, '1980-01-02')
        self.assertContains(r, 'años')

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from django.urls import reverse

from apps.convenios.models import Prevision
from apps.fichas_clinicas.models import AccesoFicha, Diagnostico
from apps.pacientes.models import Paciente
from apps.profesionales.models import Especialidad, Profesional
from apps.seguridad.indice import indice_correo, indice_rut
from apps.usuarios.models import Usuario

CLAVE = 'Clave-Muy-Segura-123'

DATOS_REGISTRO = {
    'nombres': 'Ana', 'apellidos': 'Pérez Soto', 'rut': '12.345.678-5', 'fecha_nacimiento': '1990-05-01',
    'email': 'ana@correo.cl', 'telefono': '+56 9 1234 5678', 'clave': CLAVE, 'clave2': CLAVE,
    'consentimiento_datos': 'on',
}


class RegistroYLoginTests(TestCase):
    def test_registro_crea_usuario_paciente_con_indice_de_rut(self):
        r = self.client.post(reverse('registro'), DATOS_REGISTRO)
        self.assertRedirects(r, reverse('inicio'), fetch_redirect_response=False)
        usuario = Usuario.objects.get(correo_indice=indice_correo('ana@correo.cl'))
        self.assertEqual(usuario.rol, Usuario.Rol.PACIENTE)
        self.assertEqual(usuario.rut_indice, indice_rut('12.345.678-5'))
        # La cuenta no guarda datos personales: usuario aleatorio, sin nombre ni correo en claro.
        self.assertTrue(usuario.username.startswith('p_'))
        self.assertEqual((usuario.first_name, usuario.last_name), ('', ''))
        self.assertIsNone(usuario.email)
        self.assertEqual(usuario.correo_indice, indice_correo('ana@correo.cl'))
        self.assertEqual(usuario.paciente.email, 'ana@correo.cl')
        self.assertEqual(usuario.paciente.rut, '123456785')
        self.assertTrue(usuario.paciente.consentimiento_datos)

    def test_registro_rechaza_rut_invalido_y_falta_de_consentimiento(self):
        datos = {**DATOS_REGISTRO, 'rut': '12.345.678-9'}
        datos.pop('consentimiento_datos')
        r = self.client.post(reverse('registro'), datos)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Usuario.objects.exists())
        self.assertIn('rut', r.context['form'].errors)
        self.assertIn('consentimiento_datos', r.context['form'].errors)

    def test_registro_rechaza_clave_corta(self):
        r = self.client.post(reverse('registro'), {**DATOS_REGISTRO, 'clave': 'Corta-1', 'clave2': 'Corta-1'})
        self.assertIn('clave', r.context['form'].errors)

    def test_login_con_correo_y_con_rut(self):
        self.client.post(reverse('registro'), DATOS_REGISTRO)
        self.client.post(reverse('logout'))
        for identificador in ('ana@correo.cl', '12.345.678-5', '123456785'):
            r = self.client.post(reverse('login'), {'usuario': identificador, 'clave': CLAVE})
            self.assertRedirects(r, reverse('inicio'), fetch_redirect_response=False, msg_prefix=identificador)
            self.client.post(reverse('logout'))

    def test_login_con_clave_incorrecta(self):
        self.client.post(reverse('registro'), DATOS_REGISTRO)
        self.client.post(reverse('logout'))
        r = self.client.post(reverse('login'), {'usuario': '12.345.678-5', 'clave': 'otra'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'no son correctas')

    def test_login_no_redirige_a_sitios_externos(self):
        Usuario.objects.create_user('m', email='m@c.cl', password=CLAVE, rol=Usuario.Rol.MEDICO)
        r = self.client.post(reverse('login'), {'usuario': 'm@c.cl', 'clave': CLAVE, 'next': 'https://malo.example/'})
        self.assertRedirects(r, reverse('inicio'), fetch_redirect_response=False)

    def test_cada_rol_va_a_su_inicio(self):
        Usuario.objects.create_user('m', email='m@c.cl', password=CLAVE, rol=Usuario.Rol.MEDICO)
        self.client.login(username='m@c.cl', password=CLAVE)
        r = self.client.get(reverse('inicio'))
        self.assertRedirects(r, reverse('fichas:buscar'), fetch_redirect_response=False)


class FichasTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.medico = Usuario.objects.create_user('med', email='med@c.cl', password=CLAVE, rol=Usuario.Rol.MEDICO)
        cls.paciente_user = Usuario.objects.create_user('pac', email='pac@c.cl', password=CLAVE)
        cls.paciente = Paciente.objects.create(
            rut='15482331K', nombres='María José', apellidos='Fuentes Soto', fecha_nacimiento='1985-03-12',
            creado_por=cls.medico,
        )

    def test_solo_medicos_acceden(self):
        self.assertEqual(self.client.get(reverse('fichas:buscar')).status_code, 302)
        self.client.force_login(self.paciente_user)
        self.assertEqual(self.client.get(reverse('fichas:buscar')).status_code, 403)
        self.assertEqual(self.client.get(reverse('fichas:detalle', args=[self.paciente.pk])).status_code, 403)

    def test_busqueda_por_rut_y_por_nombre_sin_tildes(self):
        self.client.force_login(self.medico)
        r = self.client.get(reverse('fichas:buscar'), {'q': '15.482.331-K'})
        self.assertEqual(r.context['resultados'], [self.paciente])
        r = self.client.get(reverse('fichas:buscar'), {'q': 'maria jose fuentes'})
        self.assertEqual(r.context['resultados'], [self.paciente])
        r = self.client.get(reverse('fichas:buscar'), {'q': 'inexistente'})
        self.assertEqual(r.context['resultados'], [])

    def test_ver_ficha_queda_en_la_bitacora(self):
        self.client.force_login(self.medico)
        r = self.client.get(reverse('fichas:detalle', args=[self.paciente.pk]))
        self.assertContains(r, 'María José Fuentes Soto')
        self.assertTrue(AccesoFicha.objects.filter(paciente=self.paciente, usuario=self.medico, accion='CONSULTA').exists())

    def test_crear_ficha(self):
        self.client.force_login(self.medico)
        prevision = Prevision.objects.get(nombre='Fonasa')
        datos = {
            'nombres': 'Luis', 'apellidos': 'Soto', 'rut': '12.345.678-5', 'fecha_nacimiento': '1980-01-02',
            'sexo': 'M', 'prevision': prevision.pk, 'telefono': '+56 9 1111 2222', 'alergias': 'Penicilina',
            'peso': '70.5',
        }
        r = self.client.post(reverse('fichas:nueva'), datos)
        paciente = Paciente.objects.get(identidad__rut_indice=indice_rut('12.345.678-5'))
        self.assertEqual(paciente.creado_por, self.medico)
        self.assertRedirects(r, reverse('fichas:detalle', args=[paciente.pk]), fetch_redirect_response=False)
        self.assertEqual(paciente.historial.alergias, 'Penicilina')
        self.assertEqual(paciente.coberturas.get().prevision, prevision)
        self.assertTrue(AccesoFicha.objects.filter(paciente=paciente, accion='CREACION').exists())

    def test_crear_ficha_exige_alergias_y_rut_unico(self):
        self.client.force_login(self.medico)
        prevision = Prevision.objects.get(nombre='Fonasa')
        base = {
            'nombres': 'Luis', 'apellidos': 'Soto', 'rut': '15.482.331-K', 'fecha_nacimiento': '1980-01-02',
            'sexo': 'M', 'prevision': prevision.pk, 'telefono': '1',
        }
        r = self.client.post(reverse('fichas:nueva'), base)
        self.assertIn('rut', r.context['form'].errors)
        self.assertIn('alergias', r.context['form'].errors)


class DiagnosticosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.medico = Usuario.objects.create_user(
            'med', email='med@c.cl', password=CLAVE, rol=Usuario.Rol.MEDICO, first_name='Camila', last_name='Rojas',
        )
        Profesional.objects.create(
            usuario=cls.medico, especialidad=Especialidad.objects.create(nombre='Medicina general'), titulo='Dra.',
        )
        cls.paciente = Paciente.objects.create(
            rut='15482331K', nombres='María José', apellidos='Fuentes Soto', fecha_nacimiento='1985-03-12',
            creado_por=cls.medico,
        )
        cls.dx_diabetes = Diagnostico.objects.create(
            paciente=cls.paciente, medico=cls.medico, codigo_cie10='E11.9', diagnostico='Diabetes mellitus tipo 2',
            tratamiento='Metformina 850 mg',
        )
        cls.dx_lumbago = Diagnostico.objects.create(
            paciente=cls.paciente, medico=cls.medico, codigo_cie10='M54.5', diagnostico='Lumbago',
            estado=Diagnostico.Estado.RESUELTO,
        )
        Diagnostico.objects.filter(pk=cls.dx_lumbago.pk).update(fecha=timezone.now() - timedelta(days=800))

    def setUp(self):
        self.client.force_login(self.medico)

    def url(self, nombre='fichas:historial'):
        return reverse(nombre, args=[self.paciente.pk])

    def test_por_defecto_muestra_ultimos_12_meses(self):
        r = self.client.get(self.url())
        self.assertEqual(r.context['diagnosticos'], [self.dx_diabetes])
        self.assertContains(r, 'Camila Rojas · Medicina general')

    def test_filtros_por_periodo_estado_y_texto(self):
        r = self.client.get(self.url(), {'periodo': 'todo'})
        self.assertEqual(len(r.context['diagnosticos']), 2)
        r = self.client.get(self.url(), {'periodo': 'todo', 'estado': 'RESUELTO'})
        self.assertEqual(r.context['diagnosticos'], [self.dx_lumbago])
        r = self.client.get(self.url(), {'periodo': 'todo', 'q': 'metformina'})
        self.assertEqual(r.context['diagnosticos'], [self.dx_diabetes])
        r = self.client.get(self.url(), {'periodo': 'todo', 'q': 'm54.5'})
        self.assertEqual(r.context['diagnosticos'], [self.dx_lumbago])

    def test_registrar_diagnostico(self):
        datos = {'codigo_cie10': 'j06.9', 'diagnostico': 'Infección respiratoria', 'estado': 'EN_TRATAMIENTO',
                 'tratamiento': 'Reposo'}
        r = self.client.post(self.url('fichas:nuevo_diagnostico'), datos)
        self.assertRedirects(r, self.url(), fetch_redirect_response=False)
        dx = Diagnostico.objects.exclude(pk__in=[self.dx_diabetes.pk, self.dx_lumbago.pk]).get()
        self.assertEqual(dx.codigo_cie10, 'J06.9')
        self.assertEqual(dx.medico, self.medico)
        self.assertTrue(AccesoFicha.objects.filter(paciente=self.paciente, accion='REGISTRO').exists())

    def test_codigo_cie10_invalido(self):
        datos = {'codigo_cie10': 'diabetes', 'diagnostico': 'x', 'estado': 'RESUELTO'}
        r = self.client.post(self.url('fichas:nuevo_diagnostico'), datos)
        self.assertIn('codigo_cie10', r.context['form'].errors)
        self.assertEqual(Diagnostico.objects.count(), 2)

    def test_pacientes_no_acceden(self):
        paciente_user = Usuario.objects.create_user('pac', email='pac@c.cl', password=CLAVE)
        self.client.force_login(paciente_user)
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        self.assertEqual(self.client.post(self.url('fichas:nuevo_diagnostico'), {}).status_code, 403)

from datetime import time, timedelta

from django.contrib.auth.models import Group
from django.db import connection
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.agenda.models import Cita
from apps.fichas_clinicas.models import AccesoFicha, Diagnostico, HistorialMedico
from apps.laboratorio.models import ResultadoExamen
from apps.pacientes.acceso import abrir_emergencia, pacientes_con_relacion, tipo_de_acceso
from apps.pacientes.models import AccesoEmergencia, AccesoIdentidad, Paciente
from apps.profesionales.models import Especialidad, Profesional
from apps.recetas.models import Receta
from apps.sucursales.models import Sucursal
from apps.usuarios import roles
from apps.usuarios.models import Usuario

CLAVE = 'Clave-Muy-Segura-123'


class RbacBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.medico = Usuario.objects.create_user('med', email='med@c.cl', password=CLAVE, rol='MEDICO', first_name='Camila', last_name='Rojas')
        cls.otro_medico = Usuario.objects.create_user('med2', email='med2@c.cl', password=CLAVE, rol='MEDICO')
        cls.admin = Usuario.objects.create_user('adm', email='adm@c.cl', password=CLAVE, rol='ADMINISTRATIVO')
        cls.sistema = Usuario.objects.create_superuser('sis', 'sis@c.cl', CLAVE)
        cls.paciente_user = Usuario.objects.create_user('pac', password=CLAVE, rol='PACIENTE')
        cls.paciente = Paciente.objects.create(
            usuario=cls.paciente_user, rut='15482331K', nombres='María José', apellidos='Fuentes Soto',
            fecha_nacimiento='1985-03-12', email='maria@correo.cl', telefono='+56 9 1234 4821', creado_por=cls.medico,
        )
        HistorialMedico.objects.create(paciente=cls.paciente, alergias='Penicilina')
        cls.diagnostico = Diagnostico.objects.create(
            paciente=cls.paciente, medico=cls.medico, codigo_cie10='E11.9', diagnostico='Diabetes mellitus tipo 2',
        )
        cls.resultado = ResultadoExamen.objects.create(paciente=cls.paciente, tipo_examen='Perfil lipídico', laboratorio='Sede Central')
        cls.receta = Receta.objects.create(paciente=cls.paciente, medico=cls.medico, diagnostico=cls.diagnostico)

    def urls_clinicas(self):
        p = self.paciente.pk
        return [
            reverse('fichas:buscar'), reverse('fichas:nueva'), reverse('fichas:detalle', args=[p]),
            reverse('fichas:historial', args=[p]), reverse('fichas:nuevo_diagnostico', args=[p]),
            reverse('laboratorio:examenes', args=[p]), reverse('recetas:nueva', args=[p]),
            reverse('recetas:detalle', args=[self.receta.pk]), reverse('fichas:emergencia', args=[p]),
        ]

    def urls_portal(self):
        return [reverse('pacientes:resultados'), reverse('notificaciones:lista'), reverse('agenda:consulta'), reverse('agenda:examen')]

    def urls_recepcion(self):
        return [reverse('recepcion:dashboard'), reverse('recepcion:contacto', args=[self.paciente.pk])]

    def estado(self, usuario, url):
        self.client.force_login(usuario)
        return self.client.get(url).status_code


class RolesYPermisosTests(RbacBase):
    def permisos_de(self, rol):
        grupo = getattr(self, rol).groups.get()
        return {p.codename for p in grupo.permissions.all()}

    def test_cada_rol_tiene_exactamente_los_permisos_definidos(self):
        esperado = {'paciente_user': 'PACIENTE', 'medico': 'MEDICO', 'admin': 'ADMINISTRATIVO', 'sistema': 'ADMIN_SISTEMA'}
        for atributo, rol in esperado.items():
            self.assertEqual(self.permisos_de(atributo), set(roles.ROLES[rol]['permisos']), rol)

    def test_el_grupo_sigue_al_rol(self):
        self.assertEqual(list(self.medico.groups.values_list('name', flat=True)), ['Médico'])
        self.medico.rol = 'ADMINISTRATIVO'
        self.medico.save()
        self.assertEqual(list(self.medico.groups.values_list('name', flat=True)), ['Personal administrativo'])
        self.assertEqual(Group.objects.count(), 4)

    def test_createsuperuser_crea_administrador_del_sistema(self):
        self.assertEqual(self.sistema.rol, Usuario.Rol.ADMIN_SISTEMA)
        self.assertTrue(self.sistema.is_superuser)

    def test_el_administrador_de_sistema_no_tiene_permisos_clinicos_ni_de_identidad(self):
        for perm in ('usuarios.ver_identidad', 'usuarios.ver_datos_clinicos', 'usuarios.emitir_recetas',
                     'fichas_clinicas.view_diagnostico', 'recetas.view_receta', 'laboratorio.view_resultadoexamen',
                     'pacientes.view_identidadpaciente', 'convenios.view_cobertura'):
            self.assertFalse(self.sistema.has_perm(perm), perm)
        self.assertTrue(self.sistema.has_perm('usuarios.view_usuario'))
        self.assertTrue(self.sistema.has_perm('fichas_clinicas.view_accesoficha'))


class MatrizDeAccesoTests(RbacBase):
    """Lo que cada rol NO debe poder abrir (403) y lo que sí."""

    def test_paciente_solo_accede_a_su_portal(self):
        for url in self.urls_clinicas() + self.urls_recepcion():
            self.assertEqual(self.estado(self.paciente_user, url), 403, url)
        for url in self.urls_portal():
            self.assertEqual(self.estado(self.paciente_user, url), 200, url)

    def test_medico_no_accede_al_portal_ni_a_la_recepcion(self):
        for url in self.urls_portal() + self.urls_recepcion():
            self.assertEqual(self.estado(self.medico, url), 403, url)
        self.assertEqual(self.estado(self.medico, reverse('fichas:detalle', args=[self.paciente.pk])), 200)

    def test_administrativo_no_ve_nada_clinico(self):
        for url in self.urls_clinicas() + self.urls_portal():
            self.assertEqual(self.estado(self.admin, url), 403, url)
        for url in self.urls_recepcion():
            self.assertEqual(self.estado(self.admin, url), 200, url)

    def test_administrador_de_sistema_no_ve_datos_de_salud_ni_la_agenda_de_pacientes(self):
        for url in self.urls_clinicas() + self.urls_portal() + self.urls_recepcion():
            self.assertEqual(self.estado(self.sistema, url), 403, url)

    def test_sin_sesion_se_redirige_al_login(self):
        self.client.logout()
        for url in self.urls_clinicas() + self.urls_portal() + self.urls_recepcion():
            r = self.client.get(url)
            self.assertEqual(r.status_code, 302, url)
            self.assertTrue(r.url.startswith(reverse('login')), url)


class SitioDeAdministracionTests(RbacBase):
    def test_el_administrador_del_sistema_no_ve_los_modelos_clinicos(self):
        self.client.force_login(self.sistema)
        indice = self.client.get('/admin/').content.decode()
        self.assertIn('Usuarios', indice)
        self.assertNotIn('Diagnósticos', indice)
        self.assertNotIn('Recetas', indice)
        self.assertNotIn('Resultados de exámenes', indice)
        for ruta in ('fichas_clinicas/diagnostico/', 'recetas/receta/', 'laboratorio/resultadoexamen/',
                     'pacientes/paciente/', 'convenios/cobertura/'):
            self.assertEqual(self.client.get(f'/admin/{ruta}').status_code, 403, ruta)

    def test_las_bitacoras_son_de_solo_lectura(self):
        AccesoFicha.objects.create(paciente=self.paciente, usuario=self.medico, accion='CONSULTA')
        self.client.force_login(self.sistema)
        self.assertEqual(self.client.get('/admin/fichas_clinicas/accesoficha/').status_code, 200)
        self.assertEqual(self.client.get('/admin/fichas_clinicas/accesoficha/add/').status_code, 403)

    def test_el_personal_que_no_es_administrador_no_entra_al_sitio_de_administracion(self):
        for usuario in (self.medico, self.admin, self.paciente_user):
            self.client.force_login(usuario)
            self.assertEqual(self.client.get('/admin/').status_code, 302)

    def test_el_admin_no_muestra_motivo_de_consulta_ni_detalle_de_avisos(self):
        from apps.agenda.admin import CitaAdmin
        from apps.notificaciones.admin import NotificacionAdmin
        self.assertIn('motivo', CitaAdmin.exclude)
        self.assertIn('detalle', NotificacionAdmin.exclude)


class RelacionTerapeuticaTests(RbacBase):
    def test_medico_con_relacion_ve_al_paciente(self):
        self.assertEqual(tipo_de_acceso(self.medico, self.paciente), 'relacion')
        self.assertEqual(self.estado(self.medico, reverse('fichas:detalle', args=[self.paciente.pk])), 200)

    def test_medico_sin_relacion_es_enviado_a_emergencia_en_todas_las_pantallas_clinicas(self):
        p = self.paciente.pk
        for url in (reverse('fichas:detalle', args=[p]), reverse('fichas:historial', args=[p]),
                    reverse('fichas:nuevo_diagnostico', args=[p]), reverse('laboratorio:examenes', args=[p]),
                    reverse('recetas:nueva', args=[p]), reverse('recetas:detalle', args=[self.receta.pk])):
            self.client.force_login(self.otro_medico)
            r = self.client.get(url)
            self.assertRedirects(r, reverse('fichas:emergencia', args=[p]), fetch_redirect_response=False, msg_prefix=url)

    def test_sin_relacion_no_puede_escribir(self):
        self.client.force_login(self.otro_medico)
        datos = {'codigo_cie10': 'J06.9', 'diagnostico': 'x', 'estado': 'RESUELTO'}
        self.client.post(reverse('fichas:nuevo_diagnostico', args=[self.paciente.pk]), datos)
        self.client.post(reverse('laboratorio:observacion', args=[self.resultado.pk]), {'observacion': 'x'})
        self.assertEqual(Diagnostico.objects.count(), 1)
        self.resultado.refresh_from_db()
        self.assertEqual(self.resultado.observacion_medico, '')

    def test_una_cita_vigente_da_relacion_y_una_cancelada_no(self):
        sede = Sucursal.objects.create(nombre='Sede')
        prof = Profesional.objects.create(usuario=self.otro_medico, especialidad=Especialidad.objects.create(nombre='General'))
        inicio = timezone.now() + timedelta(days=2)
        cita = Cita.objects.create(
            paciente=self.paciente, tipo='CONSULTA', profesional=prof, sucursal=sede, inicio=inicio, fin=inicio + timedelta(minutes=30),
        )
        self.assertEqual(tipo_de_acceso(self.otro_medico, self.paciente), 'relacion')
        Cita.objects.filter(pk=cita.pk).update(estado='CANCELADA')
        self.assertIsNone(tipo_de_acceso(self.otro_medico, self.paciente))

    def test_busqueda_por_nombre_solo_entre_pacientes_con_relacion(self):
        self.client.force_login(self.otro_medico)
        r = self.client.get(reverse('fichas:buscar'), {'q': 'maria jose'})
        self.assertEqual(r.context['resultados'], [])
        self.assertNotContains(r, 'María José')

    def test_busqueda_por_rut_ofrece_emergencia_sin_revelar_el_nombre(self):
        self.client.force_login(self.otro_medico)
        r = self.client.get(reverse('fichas:buscar'), {'q': '15.482.331-K'})
        self.assertContains(r, 'Acceso de emergencia')
        self.assertContains(r, '••.•••.331-K')
        self.assertNotContains(r, 'María')
        self.assertNotContains(r, 'Fuentes')

    def test_la_busqueda_deja_constancia_de_la_reidentificacion(self):
        self.client.force_login(self.medico)
        self.client.get(reverse('fichas:buscar'), {'q': 'fuentes'})
        acceso = AccesoIdentidad.objects.get()
        self.assertEqual((acceso.usuario, acceso.finalidad, acceso.cantidad), (self.medico, 'Búsqueda de pacientes', 1))

    def test_pacientes_con_relacion(self):
        self.assertEqual(list(pacientes_con_relacion(self.medico)), [self.paciente])
        self.assertEqual(list(pacientes_con_relacion(self.otro_medico)), [])


class AccesoDeEmergenciaTests(RbacBase):
    def setUp(self):
        self.client.force_login(self.otro_medico)
        self.url = reverse('fichas:emergencia', args=[self.paciente.pk])

    def test_la_pantalla_no_muestra_la_identidad(self):
        r = self.client.get(self.url)
        self.assertContains(r, 'Acceso de emergencia')
        self.assertNotContains(r, 'María')
        self.assertNotContains(r, 'Fuentes')

    def test_exige_un_motivo_real(self):
        r = self.client.post(self.url, {'motivo': 'urgente'})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(AccesoEmergencia.objects.exists())

    def test_abrir_el_acceso_registra_motivo_cifrado_y_permite_ver_la_ficha(self):
        r = self.client.post(self.url, {'motivo': 'Paciente inconsciente en urgencias'})
        self.assertRedirects(r, reverse('fichas:detalle', args=[self.paciente.pk]), fetch_redirect_response=False)
        acceso = AccesoEmergencia.objects.get()
        self.assertEqual(acceso.motivo, 'Paciente inconsciente en urgencias')
        self.assertAlmostEqual((acceso.vence - acceso.inicio).total_seconds(), 7200, delta=5)
        with connection.cursor() as cursor:
            cursor.execute('SELECT motivo FROM pacientes_accesoemergencia WHERE id = %s', [acceso.pk])
            self.assertNotIn('inconsciente', cursor.fetchone()[0])
        self.assertTrue(AccesoFicha.objects.filter(accion='EMERGENCIA', usuario=self.otro_medico).exists())
        self.assertEqual(self.client.get(reverse('fichas:detalle', args=[self.paciente.pk])).status_code, 200)

    def test_el_acceso_vence_solo(self):
        acceso = abrir_emergencia(self.otro_medico, self.paciente, 'Urgencia en guardia nocturna')
        self.assertEqual(tipo_de_acceso(self.otro_medico, self.paciente), 'emergencia')
        AccesoEmergencia.objects.filter(pk=acceso.pk).update(vence=timezone.now() - timedelta(minutes=1))
        self.assertIsNone(tipo_de_acceso(self.otro_medico, self.paciente))

    def test_solo_los_medicos_pueden_abrir_emergencias(self):
        for usuario in (self.admin, self.paciente_user, self.sistema):
            self.client.force_login(usuario)
            self.assertEqual(self.client.post(self.url, {'motivo': 'Motivo suficientemente largo'}).status_code, 403)
        self.assertFalse(AccesoEmergencia.objects.exists())

    def test_quien_ya_tiene_relacion_no_necesita_emergencia(self):
        self.client.force_login(self.medico)
        self.assertRedirects(self.client.get(self.url), reverse('fichas:detalle', args=[self.paciente.pk]), fetch_redirect_response=False)

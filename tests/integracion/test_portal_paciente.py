import json
from datetime import timedelta

from django.db import connection
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.laboratorio.models import ResultadoExamen
from apps.notificaciones.models import Notificacion, PreferenciasNotificacion
from apps.pacientes.models import Paciente
from apps.usuarios.models import Usuario

CLAVE = 'Clave-Muy-Segura-123'
PERFIL = json.dumps([
    {'nombre': 'Colesterol total', 'valor': 238, 'unidad': 'mg/dL', 'min': None, 'max': 200},
    {'nombre': 'Colesterol HDL', 'valor': 52, 'unidad': 'mg/dL', 'min': 40, 'max': None},
])


def crear_paciente(nombre, rut, email):
    usuario = Usuario.objects.create_user(nombre, email=email, password=CLAVE)
    paciente = Paciente.objects.create(
        usuario=usuario, rut=rut, nombres=nombre.title(), apellidos='Prueba', fecha_nacimiento='1985-03-12',
        telefono='+56 9 1234 4821',
    )
    return usuario, paciente


class PortalPacienteBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario, cls.paciente = crear_paciente('maria', '15482331K', 'maria@c.cl')
        cls.otro_usuario, cls.otro = crear_paciente('pedro', '123456785', 'pedro@c.cl')
        cls.medico = Usuario.objects.create_user(
            'med', email='med@c.cl', password=CLAVE, rol=Usuario.Rol.MEDICO, first_name='Camila', last_name='Rojas',
        )

    def setUp(self):
        self.client.force_login(self.usuario)


class ResultadosPacienteTests(PortalPacienteBase):
    def setUp(self):
        super().setUp()
        self.perfil = ResultadoExamen.objects.create(
            paciente=self.paciente, tipo_examen='Perfil lipídico', laboratorio='Sede Central', estado='DISPONIBLE',
            fecha_toma=timezone.now(), solicitado_por=self.medico, resultado=PERFIL,
        )
        self.orina = ResultadoExamen.objects.create(
            paciente=self.paciente, tipo_examen='Orina completa', laboratorio='Sede Central',
            fecha_toma=timezone.now() - timedelta(days=5), fecha_estimada=timezone.localdate() + timedelta(days=2),
        )
        self.ajeno = ResultadoExamen.objects.create(
            paciente=self.otro, tipo_examen='Examen ajeno', laboratorio='Sede Central', estado='DISPONIBLE',
        )

    def test_muestra_resultados_en_lenguaje_simple(self):
        r = self.client.get(reverse('pacientes:resultados'))
        self.assertContains(r, 'Sobre lo esperado')
        self.assertContains(r, 'Dentro de lo esperado')
        self.assertContains(r, 'menos de 200')
        self.assertContains(r, 'Solicitado por Camila Rojas')
        self.assertContains(r, 'En proceso')

    def test_no_muestra_examenes_de_otros_pacientes(self):
        r = self.client.get(reverse('pacientes:resultados'), {'e': self.ajeno.pk})
        self.assertNotContains(r, 'Examen ajeno')
        self.assertEqual(r.context['seleccionado'], self.perfil)

    def test_el_paciente_no_ve_la_observacion_del_medico(self):
        self.perfil.observacion_medico = 'Nota interna del médico'
        self.perfil.save()
        self.assertNotContains(self.client.get(reverse('pacientes:resultados')), 'Nota interna')

    def test_login_de_paciente_lleva_a_sus_resultados(self):
        self.client.logout()
        r = self.client.post(reverse('login'), {'usuario': 'maria@c.cl', 'clave': CLAVE})
        self.assertRedirects(r, reverse('inicio'), fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse('inicio')), reverse('pacientes:resultados'), fetch_redirect_response=False)

    def test_los_medicos_no_entran(self):
        self.client.force_login(self.medico)
        self.assertEqual(self.client.get(reverse('pacientes:resultados')).status_code, 403)
        self.assertEqual(self.client.get(reverse('notificaciones:lista')).status_code, 403)


class NotificacionesTests(PortalPacienteBase):
    def test_al_quedar_disponible_un_resultado_se_crea_el_aviso_una_sola_vez(self):
        examen = ResultadoExamen.objects.create(paciente=self.paciente, tipo_examen='Perfil lipídico', laboratorio='X')
        self.assertFalse(Notificacion.objects.exists())
        examen.estado = 'DISPONIBLE'
        examen.save()
        examen.save()
        aviso = Notificacion.objects.get()
        self.assertEqual(aviso.tipo, 'RESULTADO')
        self.assertEqual(aviso.titulo, 'Tus resultados de perfil lipídico están disponibles')
        self.assertFalse(aviso.leida)

    def test_lista_filtros_y_contador(self):
        Notificacion.objects.create(paciente=self.paciente, tipo='CITA', titulo='Recordatorio', detalle='Martes 10:30')
        Notificacion.objects.create(paciente=self.paciente, tipo='RESULTADO', titulo='Resultados', leida=True)
        Notificacion.objects.create(paciente=self.otro, tipo='CITA', titulo='Ajena')
        r = self.client.get(reverse('notificaciones:lista'))
        self.assertEqual(len(r.context['avisos']), 2)
        self.assertEqual(r.context['sin_leer'], 1)
        self.assertNotContains(r, 'Ajena')
        self.assertEqual(len(self.client.get(reverse('notificaciones:lista'), {'f': 'sin-leer'}).context['avisos']), 1)
        self.assertEqual(len(self.client.get(reverse('notificaciones:lista'), {'f': 'citas'}).context['avisos']), 1)
        self.assertEqual(len(self.client.get(reverse('notificaciones:lista'), {'f': 'resultados'}).context['avisos']), 1)

    def test_el_menu_muestra_el_distintivo_de_sin_leer(self):
        Notificacion.objects.create(paciente=self.paciente, tipo='CITA', titulo='A')
        Notificacion.objects.create(paciente=self.paciente, tipo='CITA', titulo='B')
        self.assertEqual(self.client.get(reverse('pacientes:resultados')).context['notificaciones_sin_leer'], 2)

    def test_detalle_se_guarda_cifrado(self):
        aviso = Notificacion.objects.create(paciente=self.paciente, tipo='CITA', titulo='Cita', detalle='Medicina general el martes')
        with connection.cursor() as cursor:
            cursor.execute('SELECT detalle FROM notificaciones_notificacion WHERE id = %s', [aviso.pk])
            self.assertNotIn('Medicina', cursor.fetchone()[0])

    def test_marcar_todas_solo_afecta_al_propio_paciente(self):
        propia = Notificacion.objects.create(paciente=self.paciente, tipo='CITA', titulo='Mía')
        ajena = Notificacion.objects.create(paciente=self.otro, tipo='CITA', titulo='Ajena')
        r = self.client.post(reverse('notificaciones:marcar_todas'))
        self.assertRedirects(r, reverse('notificaciones:lista'), fetch_redirect_response=False)
        propia.refresh_from_db()
        ajena.refresh_from_db()
        self.assertTrue(propia.leida)
        self.assertFalse(ajena.leida)
        self.assertEqual(self.client.get(reverse('notificaciones:marcar_todas')).status_code, 405)

    def test_preferencias_por_defecto_y_guardado(self):
        self.assertFalse(PreferenciasNotificacion.objects.exists())
        self.assertTrue(self.client.get(reverse('notificaciones:lista')).context['preferencias'].recordar_24h)
        self.client.post(reverse('notificaciones:preferencias'), {'canal_correo': 'on', 'recordar_2h': 'on'})
        p = PreferenciasNotificacion.objects.get(paciente=self.paciente)
        self.assertEqual(
            (p.canal_correo, p.canal_sms, p.canal_navegador, p.recordar_48h, p.recordar_24h, p.recordar_2h),
            (True, False, False, False, False, True),
        )
        self.assertFalse(PreferenciasNotificacion.objects.filter(paciente=self.otro).exists())

    def test_preferencias_iniciales_respetan_el_registro(self):
        self.paciente.recordatorios_activos = False
        self.paciente.save()
        p = PreferenciasNotificacion.para(self.paciente)
        self.assertFalse(p.canal_correo)
        self.assertFalse(p.canal_sms)

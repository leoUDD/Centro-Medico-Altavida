from datetime import timedelta
from unittest import mock

from django.core import mail
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.agenda.models import Cita
from apps.notificaciones import recordatorios
from apps.notificaciones.models import EjecucionRecordatorios, Notificacion, PreferenciasNotificacion, Recordatorio, ReglaRecordatorio
from apps.pacientes.models import Paciente
from apps.profesionales.models import Especialidad, Profesional
from apps.sucursales.models import Sucursal
from apps.usuarios.models import Usuario

CLAVE = 'Clave-Muy-Segura-123'


class PlantillaTests(SimpleTestCase):
    def test_solo_marcadores_conocidos(self):
        self.assertTrue(recordatorios.plantilla_valida('Hola {nombre}, el {fecha} a las {hora} con {profesional}.'))
        self.assertFalse(recordatorios.plantilla_valida('Tu diagnóstico es {diagnostico}'))
        self.assertFalse(recordatorios.plantilla_valida('Hola {nombre.__class__}'))
        self.assertFalse(recordatorios.plantilla_valida('llave suelta {'))


class RecepcionBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.sede = Sucursal.objects.create(nombre='Sede Central')
        cls.medico = Usuario.objects.create_user('m1', email='m1@c.cl', password=CLAVE, rol='MEDICO', first_name='Camila', last_name='Rojas')
        cls.profesional = Profesional.objects.create(
            usuario=cls.medico, titulo='Dra.', especialidad=Especialidad.objects.create(nombre='Medicina general'),
        )
        cls.admin = Usuario.objects.create_user('adm', email='adm@c.cl', password=CLAVE, rol='ADMINISTRATIVO', first_name='Pedro', last_name='Salinas')
        cls.usuario = Usuario.objects.create_user('maria', email='maria@c.cl', password=CLAVE)
        cls.paciente = Paciente.objects.create(
            usuario=cls.usuario, rut='15482331K', nombres='María José', apellidos='Fuentes Soto',
            fecha_nacimiento='1985-03-12', email='maria@correo.cl', telefono='+56 9 1234 4821',
        )
        PreferenciasNotificacion.objects.create(paciente=cls.paciente, canal_correo=True, canal_sms=True)

    def cita_manana(self, hora, **kw):
        """Cita mañana a una hora local fija: así varias citas caen siempre el mismo día, sin importar cuándo se ejecute la prueba."""
        manana = timezone.localtime(timezone.now()).replace(hour=hora, minute=0, second=0, microsecond=0) + timedelta(days=1)
        return self.cita(0, inicio=manana, **kw)

    def cita(self, en_horas, creada_hace_horas=72, estado='AGENDADA', paciente=None, inicio=None, **extra):
        inicio = inicio or timezone.now() + timedelta(hours=en_horas)
        cita = Cita.objects.create(
            paciente=paciente or self.paciente, tipo='CONSULTA', profesional=self.profesional, sucursal=self.sede,
            modalidad='PRESENCIAL', inicio=inicio, fin=inicio + timedelta(minutes=30), estado=estado, **extra,
        )
        Cita.objects.filter(pk=cita.pk).update(creada=timezone.now() - timedelta(hours=creada_hace_horas))
        cita.refresh_from_db()
        return cita


class GeneracionTests(RecepcionBase):
    def test_regla_de_24h_genera_correo_y_sms(self):
        cita = self.cita(20)
        self.assertEqual(recordatorios.generar(), 2)
        self.assertEqual(
            set(Recordatorio.objects.filter(cita=cita).values_list('regla__horas_antes', 'canal')), {(24, 'CORREO'), (24, 'SMS')},
        )

    def test_es_idempotente(self):
        self.cita(20)
        recordatorios.generar()
        self.assertEqual(recordatorios.generar(), 0)

    def test_regla_de_48h_solo_correo(self):
        self.cita(40)
        recordatorios.generar()
        self.assertEqual(list(Recordatorio.objects.values_list('regla__horas_antes', 'canal')), [(48, 'CORREO')])

    def test_no_genera_si_aun_no_toca_ni_si_ya_es_tarde(self):
        self.cita(60)   # la regla de 48 h comienza dentro de 12 h
        self.cita(10)   # las ventanas de 48 h y 24 h ya cerraron y la de 2 h está inactiva
        self.assertEqual(recordatorios.generar(), 0)

    def test_no_avisa_citas_reservadas_dentro_de_la_ventana(self):
        self.cita(20, creada_hace_horas=1)
        self.assertEqual(recordatorios.generar(), 0)

    def test_ignora_canceladas(self):
        self.cita(20, estado='CANCELADA')
        self.assertEqual(recordatorios.generar(), 0)

    def test_respeta_las_preferencias_del_paciente(self):
        PreferenciasNotificacion.objects.filter(paciente=self.paciente).update(canal_sms=False)
        self.cita(20)
        recordatorios.generar()
        self.assertEqual(list(Recordatorio.objects.values_list('canal', flat=True)), ['CORREO'])
        Recordatorio.objects.all().delete()
        PreferenciasNotificacion.objects.filter(paciente=self.paciente).update(recordar_24h=False)
        self.assertEqual(recordatorios.generar(), 0)

    def test_regla_inactiva_no_genera(self):
        ReglaRecordatorio.objects.filter(horas_antes=24).update(activa=False)
        self.cita(20)
        self.assertEqual(recordatorios.generar(), 0)


class EnvioTests(RecepcionBase):
    def test_correo_enviado_con_datos_minimos_y_aviso_en_la_cuenta(self):
        cita = self.cita(20)
        recordatorios.generar()
        enviados, fallidos = recordatorios.enviar_pendientes()
        self.assertEqual((enviados, fallidos), (2, 0))
        self.assertEqual(len(mail.outbox), 1)
        correo = mail.outbox[0]
        self.assertEqual(correo.to, ['maria@correo.cl'])
        self.assertIn('Hola María,', correo.body)
        self.assertIn('Dra. Camila Rojas', correo.body)
        self.assertNotIn('15482331', correo.body)
        avisos = Notificacion.objects.filter(cita=cita, titulo__startswith='Recordatorio')
        self.assertEqual(avisos.count(), 1)

    def test_fallos_por_contacto_invalido(self):
        self.paciente.actualizar_identidad(email='', telefono='123')
        self.cita(20)
        recordatorios.generar()
        self.assertEqual(recordatorios.enviar_pendientes(), (0, 2))
        self.assertEqual(
            set(Recordatorio.objects.values_list('canal', 'error')), {('CORREO', 'Sin correo registrado'), ('SMS', 'Número inválido')},
        )
        self.assertFalse(Notificacion.objects.filter(titulo__startswith='Recordatorio').exists())

    def test_correo_rebotado(self):
        self.cita(20)
        recordatorios.generar()
        with mock.patch('apps.notificaciones.recordatorios.send_mail', side_effect=OSError('rechazado')):
            recordatorios.enviar_pendientes()
        self.assertEqual(Recordatorio.objects.get(canal='CORREO').error, 'Correo rebotado')

    def test_sms_se_registra_en_el_log_sin_contenido_ni_telefono_completo(self):
        self.cita(20)
        recordatorios.generar()
        with self.assertLogs('apps.notificaciones.sms', level='INFO') as log:
            recordatorios.enviar_pendientes()
        self.assertIn('4821', log.output[0])
        self.assertNotIn('María', log.output[0])
        self.assertNotIn('1234 4821', log.output[0])

    def test_ejecutar_registra_la_pasada(self):
        self.cita(20)
        ejecucion = recordatorios.ejecutar(usuario=self.admin)
        self.assertEqual((ejecucion.creados, ejecucion.enviados, ejecucion.fallidos, ejecucion.manual), (2, 2, 0, True))
        self.assertEqual(EjecucionRecordatorios.objects.count(), 1)


class DashboardTests(RecepcionBase):
    def setUp(self):
        self.client.force_login(self.admin)

    def url(self, cita=None, **parametros):
        if cita is not None:
            parametros['fecha'] = timezone.localtime(cita.inicio).date().isoformat()
        return reverse('recepcion:dashboard') + ('?' + '&'.join(f'{k}={v}' for k, v in parametros.items()) if parametros else '')

    def test_solo_administrativos(self):
        for usuario in (self.medico, self.usuario):
            self.client.force_login(usuario)
            self.assertEqual(self.client.get(reverse('recepcion:dashboard')).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('recepcion:dashboard')).status_code, 302)

    def test_inicio_del_administrativo(self):
        r = self.client.get(reverse('inicio'))
        self.assertRedirects(r, reverse('recepcion:dashboard'), fetch_redirect_response=False)

    def test_resumen_y_tabla_con_rut_oculto(self):
        c1 = self.cita_manana(10, estado='CONFIRMADA')
        self.cita_manana(11)
        self.cita_manana(12, estado='CANCELADA')
        r = self.client.get(self.url(c1))
        self.assertEqual((r.context['total'], r.context['confirmadas'], r.context['por_confirmar'], r.context['porcentaje']), (3, 1, 1, 50))
        self.assertContains(r, '••.•••.331-K')
        self.assertNotContains(r, '15.482.331-K')
        self.assertContains(r, 'María José Fuentes Soto')

    def test_filtros(self):
        c1 = self.cita_manana(10, estado='CONFIRMADA')
        otra = Paciente.objects.create(rut='123456785', nombres='Pedro', apellidos='Soto', fecha_nacimiento='1980-01-01')
        self.cita_manana(11, paciente=otra)
        self.assertEqual(len(self.client.get(self.url(c1, estado='confirmada')).context['pagina']), 1)
        self.assertEqual(len(self.client.get(self.url(c1, q='pedro')).context['pagina']), 1)
        self.assertEqual(len(self.client.get(self.url(c1, q='12.345.678-5')).context['pagina']), 1)
        self.assertEqual(len(self.client.get(self.url(c1, profesional=self.profesional.pk)).context['pagina']), 2)
        self.assertEqual(len(self.client.get(self.url(c1, profesional='laboratorio')).context['pagina']), 0)

    def test_confirmar_y_cancelar_avisa_al_paciente(self):
        cita = self.cita(5)
        self.client.post(reverse('recepcion:confirmar', args=[cita.pk]))
        cita.refresh_from_db()
        self.assertEqual(cita.estado, 'CONFIRMADA')
        self.client.post(reverse('recepcion:cancelar', args=[cita.pk]))
        cita.refresh_from_db()
        self.assertEqual(cita.estado, 'CANCELADA')
        self.assertTrue(Notificacion.objects.filter(cita=cita, titulo='Tu hora fue cancelada').exists())
        self.assertEqual(self.client.get(reverse('recepcion:cancelar', args=[cita.pk])).status_code, 405)

    def test_generar_ahora_y_reglas(self):
        self.cita(20)
        r = self.client.post(reverse('recepcion:generar'), follow=True)
        self.assertContains(r, '2 generados, 2 enviados')
        self.assertEqual(EjecucionRecordatorios.objects.get().usuario, self.admin)
        self.client.post(reverse('recepcion:reglas'), {'regla_48': 'on', 'plantilla': 'Hola {nombre}, tu hora es el {fecha}.'})
        self.assertEqual(
            dict(ReglaRecordatorio.objects.values_list('horas_antes', 'activa')), {48: True, 24: False, 2: False},
        )
        self.assertEqual(ReglaRecordatorio.objects.get(horas_antes=24).plantilla, 'Hola {nombre}, tu hora es el {fecha}.')

    def test_plantilla_con_marcador_desconocido_se_rechaza(self):
        antes = ReglaRecordatorio.objects.get(horas_antes=24).plantilla
        r = self.client.post(reverse('recepcion:reglas'), {'plantilla': 'Tu diagnóstico: {diagnostico}'}, follow=True)
        self.assertContains(r, 'solo puede usar')
        self.assertEqual(ReglaRecordatorio.objects.get(horas_antes=24).plantilla, antes)

    def test_envios_con_problemas_editar_contacto_y_reintentar(self):
        self.paciente.actualizar_identidad(telefono='123')
        cita = self.cita(20)
        recordatorios.ejecutar()
        fallido = Recordatorio.objects.get(estado='FALLIDO')
        r = self.client.get(self.url(cita))
        self.assertEqual(r.context['cantidad_fallidos'], 1)
        self.assertContains(r, 'SMS: Número inválido')
        r = self.client.post(reverse('recepcion:contacto', args=[self.paciente.pk]), {'email': 'nuevo@correo.cl', 'telefono': '+56 9 8765 4321'})
        self.assertRedirects(r, reverse('recepcion:dashboard') + '#recordatorios', fetch_redirect_response=False)
        self.paciente = Paciente.objects.get(pk=self.paciente.pk)
        self.assertEqual((self.paciente.email, self.paciente.telefono), ('nuevo@correo.cl', '+56987654321'))
        self.client.post(reverse('recepcion:reintentar', args=[fallido.pk]))
        fallido.refresh_from_db()
        self.assertEqual(fallido.estado, 'ENVIADO')

    def test_contacto_invalido(self):
        r = self.client.post(reverse('recepcion:contacto', args=[self.paciente.pk]), {'email': 'no-es-correo', 'telefono': '12'})
        self.assertEqual(set(r.context['form'].errors), {'email', 'telefono'})

    def test_acciones_solo_para_administrativos(self):
        cita = self.cita(5)
        self.client.force_login(self.medico)
        self.assertEqual(self.client.post(reverse('recepcion:cancelar', args=[cita.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse('recepcion:generar')).status_code, 403)
        self.assertEqual(self.client.get(reverse('recepcion:contacto', args=[self.paciente.pk])).status_code, 403)

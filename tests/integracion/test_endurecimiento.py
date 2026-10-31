"""Pruebas de autenticación, errores, registros y configuración segura."""
import logging
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import authenticate
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.notificaciones.sms import enviar_sms
from apps.pacientes.models import Paciente
from apps.seguridad.indice import indice_correo, indice_rut
from apps.seguridad.registros import RedactarDatosPersonales, redactar
from apps.usuarios.models import Usuario

CLAVE = 'Clave-Muy-Segura-123'
RAIZ = Path(__file__).resolve().parents[2]


class CorreoDeInicioDeSesionTests(TestCase):
    def setUp(self):
        self.usuario = Usuario.objects.create_user(
            'p_x', password=CLAVE, rol='PACIENTE',
            rut_indice=indice_rut('11.111.111-1'), correo_indice=indice_correo('viejo@mail.cl'),
        )
        self.paciente = Paciente.objects.create(
            usuario=self.usuario, rut='11.111.111-1', nombres='Ana', apellidos='Pérez', email='viejo@mail.cl',
        )

    def test_cambiar_el_correo_actualiza_el_indice_de_inicio_de_sesion(self):
        self.paciente.actualizar_identidad(email='nuevo@mail.cl')
        self.assertIsNone(authenticate(username='viejo@mail.cl', password=CLAVE))
        self.assertEqual(authenticate(username='nuevo@mail.cl', password=CLAVE), self.usuario)

    def test_quitar_el_correo_deja_solo_el_inicio_con_rut(self):
        self.paciente.actualizar_identidad(email='')
        self.assertIsNone(authenticate(username='viejo@mail.cl', password=CLAVE))
        self.assertEqual(authenticate(username='11.111.111-1', password=CLAVE), self.usuario)

    def test_recepcion_no_acepta_un_correo_de_otra_cuenta(self):
        Usuario.objects.create_user('p_y', password=CLAVE, rol='PACIENTE', correo_indice=indice_correo('otro@mail.cl'))
        recepcion = Usuario.objects.create_user('rec', password=CLAVE, rol='ADMINISTRATIVO')
        self.client.force_login(recepcion)
        r = self.client.post(reverse('recepcion:contacto', args=[self.paciente.pk]), {'email': 'otro@mail.cl', 'telefono': '+56912345678'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'ya está asociado')
        self.assertEqual(Paciente.objects.get(pk=self.paciente.pk).email, 'viejo@mail.cl')


class LimiteDeIntentosTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        Usuario.objects.create_user('medico1', password=CLAVE, rol='MEDICO')

    def _login(self, clave, usuario='medico1'):
        return self.client.post(reverse('login'), {'usuario': usuario, 'clave': clave})

    def test_se_bloquea_tras_los_intentos_fallidos_y_rechaza_incluso_la_clave_correcta(self):
        for _ in range(5):
            self.assertEqual(self._login('mala').status_code, 200)
        r = self._login(CLAVE)
        self.assertEqual(r.status_code, 429)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_un_inicio_correcto_reinicia_el_contador(self):
        for _ in range(4):
            self._login('mala')
        self.assertEqual(self._login(CLAVE).status_code, 302)
        self.client.logout()
        for _ in range(4):
            self.assertEqual(self._login('mala').status_code, 200)

    def test_el_bloqueo_de_una_cuenta_no_afecta_a_otra(self):
        Usuario.objects.create_user('medico2', password=CLAVE, rol='MEDICO')
        for _ in range(5):
            self._login('mala')
        self.assertEqual(self._login(CLAVE, 'medico2').status_code, 302)

    def test_la_cache_no_guarda_el_identificador_en_claro(self):
        from apps.seguridad import intentos
        request = self.client.get(reverse('login')).wsgi_request
        llaves = intentos._llaves(request, '15.482.331-K')
        self.assertTrue(all('15482331' not in k and '15.482' not in k for k in llaves))


class ErroresSegurosTests(TestCase):
    def setUp(self):
        self.client.raise_request_exception = False
        self.medico = Usuario.objects.create_user('med', password=CLAVE, rol='MEDICO')

    def test_un_error_500_no_expone_datos_personales_ni_detalles(self):
        self.client.force_login(self.medico)
        with patch('apps.fichas_clinicas.views._buscar_pacientes', side_effect=RuntimeError('RUT 15482331-K María Fuentes')), \
                self.assertLogs('django.request', level='ERROR'):
            r = self.client.get(reverse('fichas:buscar'), {'q': 'maria'})
        self.assertEqual(r.status_code, 500)
        cuerpo = r.content.decode()
        for dato in ('15482331', 'María', 'RuntimeError', 'Traceback', 'apps/'):
            self.assertNotIn(dato, cuerpo)

    def test_403_y_404_son_genericos(self):
        paciente = Usuario.objects.create_user('pac', password=CLAVE, rol='PACIENTE')
        self.client.force_login(paciente)
        r403 = self.client.get(reverse('fichas:buscar'))
        self.assertEqual(r403.status_code, 403)
        self.assertContains(r403, 'Acceso denegado', status_code=403)
        r404 = self.client.get('/no-existe/')
        self.assertContains(r404, 'Página no encontrada', status_code=404)


class RegistrosSinDatosPersonalesTests(TestCase):
    def test_redactar_enmascara_rut_correo_y_telefono(self):
        texto = redactar('Paciente 15.482.331-K, ana@mail.cl, +56 9 1234 4821')
        for dato in ('15.482.331', 'ana@mail.cl', '1234 4821'):
            self.assertNotIn(dato, texto)
        self.assertIn('[RUT]', texto)

    def test_el_filtro_limpia_mensaje_y_traceback(self):
        try:
            raise ValueError('falló para 15482331-K')
        except ValueError:
            import sys as _sys
            registro = logging.LogRecord('x', logging.ERROR, __file__, 1, 'usuario %s', ('ana@mail.cl',), _sys.exc_info())
        RedactarDatosPersonales().filter(registro)
        self.assertNotIn('ana@mail.cl', registro.msg)
        self.assertNotIn('15482331', registro.exc_text)

    def test_el_log_de_sms_no_incluye_el_mensaje_ni_el_telefono_completo(self):
        with self.assertLogs('apps.notificaciones.sms', level='INFO') as cm:
            enviar_sms('+56 9 1234 4821', 'Hola María, tu hora con la Dra. Rojas es mañana')
        salida = ' '.join(cm.output)
        for dato in ('María', 'Rojas', '1234', '+56 9'):
            self.assertNotIn(dato, salida)
        self.assertIn('4821', salida)


class ConfiguracionSeguraTests(TestCase):
    def _config(self, **entorno):
        env = {k: v for k, v in os.environ.items() if not k.startswith('DJANGO_') or k == 'DJANGO_SECRET_KEY'}
        # Valores vacíos explícitos: python-dotenv no pisa variables ya definidas, así el resultado no depende
        # del .env de quien ejecuta las pruebas (p. ej. DJANGO_DEBUG=1 en desarrollo).
        env.update({'DJANGO_DEBUG': '', 'DJANGO_HTTPS': ''})
        env.update(entorno)
        codigo = (
            "import django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings'); "
            "from django.conf import settings as s; "
            "print(s.DEBUG, s.SESSION_COOKIE_SECURE, s.CSRF_COOKIE_SECURE, s.SECURE_SSL_REDIRECT, s.SESSION_COOKIE_HTTPONLY)"
        )
        salida = subprocess.run([sys.executable, '-c', codigo], cwd=RAIZ, env=env, capture_output=True, text=True, check=True)
        return salida.stdout.split()

    def test_por_defecto_debug_esta_apagado(self):
        self.assertEqual(self._config()[0], 'False')

    def test_con_https_las_cookies_son_seguras_y_se_redirige(self):
        debug, sesion, csrf, redireccion, httponly = self._config(DJANGO_HTTPS='1')
        self.assertEqual((debug, sesion, csrf, redireccion, httponly), ('False', 'True', 'True', 'True', 'True'))

    def test_la_sesion_expira_por_inactividad(self):
        from django.conf import settings
        self.assertLessEqual(settings.SESSION_COOKIE_AGE, 30 * 60)
        self.assertTrue(settings.SESSION_SAVE_EVERY_REQUEST)

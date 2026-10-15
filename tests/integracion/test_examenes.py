import json
from datetime import timedelta

from django.db import connection
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.fichas_clinicas.models import AccesoFicha
from apps.laboratorio.models import ResultadoExamen, parsear_parametros
from apps.pacientes.models import Paciente
from apps.usuarios.models import Usuario

CLAVE = 'Clave-Muy-Segura-123'

PERFIL = json.dumps([
    {'nombre': 'Colesterol total', 'valor': 238, 'unidad': 'mg/dL', 'min': None, 'max': 200},
    {'nombre': 'Colesterol HDL', 'valor': 52, 'unidad': 'mg/dL', 'min': 40, 'max': None},
    {'nombre': 'Hemoglobina', 'valor': 11.2, 'unidad': 'g/dL', 'min': 12, 'max': 16},
])


class ParametrosTests(TestCase):
    def test_estado_y_referencia_se_calculan(self):
        filas = parsear_parametros(PERFIL)
        self.assertEqual([f['estado'] for f in filas], ['Alto', 'Normal', 'Bajo'])
        self.assertEqual([f['referencia'] for f in filas], ['< 200', '> 40', '12 – 16'])

    def test_json_invalido_o_vacio(self):
        self.assertEqual(parsear_parametros(''), [])
        self.assertEqual(parsear_parametros('no es json'), [])
        self.assertEqual(parsear_parametros('{"a": 1}'), [])


class ExamenesVistasTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.medico = Usuario.objects.create_user('med', email='med@c.cl', password=CLAVE, rol=Usuario.Rol.MEDICO)
        cls.paciente = Paciente.objects.create(
            rut='15482331K', nombres='María José', apellidos='Fuentes Soto', fecha_nacimiento='1985-03-12',
        )
        cls.perfil = ResultadoExamen.objects.create(
            paciente=cls.paciente, tipo_examen='Perfil lipídico', laboratorio='Sede Central',
            estado='DISPONIBLE', fecha_toma=timezone.now(), validado_por='TM Andrea Paredes', resultado=PERFIL,
        )
        cls.orina = ResultadoExamen.objects.create(
            paciente=cls.paciente, tipo_examen='Orina completa', laboratorio='Sede Central',
            fecha_toma=timezone.now() - timedelta(days=5),
        )

    def setUp(self):
        self.client.force_login(self.medico)

    def test_lista_y_detalle(self):
        r = self.client.get(reverse('laboratorio:examenes', args=[self.paciente.pk]))
        self.assertEqual(r.context['seleccionado'], self.perfil)
        self.assertContains(r, 'Colesterol total')
        self.assertContains(r, '2 valores fuera de rango')
        self.assertEqual((r.context['total'], r.context['disponibles'], r.context['pendientes']), (2, 1, 1))
        self.assertTrue(AccesoFicha.objects.filter(paciente=self.paciente, accion='CONSULTA').exists())

    def test_filtro_y_seleccion_de_pendiente(self):
        url = reverse('laboratorio:examenes', args=[self.paciente.pk])
        r = self.client.get(url, {'estado': 'PENDIENTE'})
        self.assertEqual(r.context['lista'], [self.orina])
        self.assertContains(r, 'aún no entrega')

    def test_guardar_observacion_cifrada(self):
        r = self.client.post(reverse('laboratorio:observacion', args=[self.perfil.pk]), {'observacion': 'Control en 3 meses'})
        self.assertRedirects(
            r, f"{reverse('laboratorio:examenes', args=[self.paciente.pk])}?e={self.perfil.pk}",
            fetch_redirect_response=False,
        )
        self.perfil.refresh_from_db()
        self.assertEqual(self.perfil.observacion_medico, 'Control en 3 meses')
        with connection.cursor() as cursor:
            cursor.execute('SELECT observacion_medico, resultado FROM laboratorio_resultadoexamen WHERE id = %s', [self.perfil.pk])
            observacion, resultado = cursor.fetchone()
        self.assertNotIn('Control', observacion)
        self.assertNotIn('Colesterol', resultado)
        self.assertTrue(AccesoFicha.objects.filter(accion='OBSERVACION').exists())

    def test_solo_medicos(self):
        paciente_user = Usuario.objects.create_user('pac', email='pac@c.cl', password=CLAVE)
        self.client.force_login(paciente_user)
        self.assertEqual(self.client.get(reverse('laboratorio:examenes', args=[self.paciente.pk])).status_code, 403)
        r = self.client.post(reverse('laboratorio:observacion', args=[self.perfil.pk]), {'observacion': 'x'})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client.get(reverse('laboratorio:observacion', args=[self.perfil.pk])).status_code, 403)

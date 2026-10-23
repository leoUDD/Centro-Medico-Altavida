import csv
import io
import tempfile
from datetime import timedelta
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.agenda.models import Cita
from apps.fichas_clinicas.models import Diagnostico
from apps.notificaciones.models import EjecucionRecordatorios, Notificacion
from apps.pacientes.models import Paciente
from apps.seguridad import anonimizacion, retencion
from apps.sucursales.models import Sucursal
from apps.usuarios.models import Usuario

CLAVE = 'Clave-Muy-Segura-123'


class RetencionTests(TestCase):
    def setUp(self):
        self.paciente = Paciente.objects.create(rut='12.345.678-5', nombres='Ana', apellidos='Pérez')
        self.sede = Sucursal.objects.create(nombre='Sede')

    def cita_examen(self, hace_dias):
        inicio = timezone.now() - timedelta(days=hace_dias)
        return Cita.objects.create(
            paciente=self.paciente, tipo='EXAMEN', sucursal=self.sede, inicio=inicio, fin=inicio + timedelta(minutes=15),
            orden_externa='QUJD', orden_externa_nombre='orden.pdf', orden_externa_tipo='application/pdf',
        )

    def test_la_orden_externa_se_borra_a_los_30_dias_de_la_toma(self):
        vieja, reciente = self.cita_examen(40), self.cita_examen(5)
        resultado = retencion.purgar()
        vieja.refresh_from_db()
        reciente.refresh_from_db()
        self.assertEqual((vieja.orden_externa, vieja.orden_externa_nombre, vieja.orden_externa_tipo), ('', '', ''))
        self.assertEqual(reciente.orden_externa, 'QUJD')
        self.assertEqual(resultado['ordenes_externas'], 1)

    def test_los_avisos_se_borran_a_los_90_dias(self):
        antiguo = Notificacion.objects.create(paciente=self.paciente, tipo='CITA', titulo='Viejo')
        reciente = Notificacion.objects.create(paciente=self.paciente, tipo='CITA', titulo='Nuevo')
        Notificacion.objects.filter(pk=antiguo.pk).update(creada=timezone.now() - timedelta(days=91))
        retencion.purgar()
        self.assertEqual(list(Notificacion.objects.values_list('titulo', flat=True)), ['Nuevo'])
        self.assertTrue(Notificacion.objects.filter(pk=reciente.pk).exists())

    def test_la_bitacora_de_ejecuciones_se_conserva_180_dias(self):
        vieja, reciente = EjecucionRecordatorios.objects.create(), EjecucionRecordatorios.objects.create()
        EjecucionRecordatorios.objects.filter(pk=vieja.pk).update(fecha=timezone.now() - timedelta(days=181))
        retencion.purgar()
        self.assertEqual(list(EjecucionRecordatorios.objects.values_list('pk', flat=True)), [reciente.pk])

    def test_los_datos_clinicos_no_se_purgan(self):
        medico = Usuario.objects.create_user('med', password=CLAVE, rol='MEDICO')
        dx = Diagnostico.objects.create(paciente=self.paciente, medico=medico, diagnostico='Hipertensión')
        Diagnostico.objects.filter(pk=dx.pk).update(fecha=timezone.now() - timedelta(days=4000))
        retencion.purgar()
        self.assertTrue(Diagnostico.objects.filter(pk=dx.pk).exists())

    def test_el_comando(self):
        salida = io.StringIO()
        call_command('purgar_datos', stdout=salida)
        self.assertIn('Retención aplicada', salida.getvalue())


class AnonimizacionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.medico = Usuario.objects.create_user('med', password=CLAVE, rol='MEDICO')
        for i in range(6):  # 6 mujeres de 41 años con diabetes: grupo de tamaño suficiente
            p = Paciente.objects.create(rut=f'1000000{i}', nombres=f'Paciente{i}', apellidos='Apellido', sexo='F', fecha_nacimiento='1985-03-12')
            Diagnostico.objects.create(paciente=p, medico=cls.medico, codigo_cie10='E11.9', diagnostico='Diabetes')
        raro = Paciente.objects.create(rut='20000000', nombres='Unico', apellidos='Caso', sexo='M', fecha_nacimiento='2015-06-01')
        Diagnostico.objects.create(paciente=raro, medico=cls.medico, codigo_cie10='Z99.1', diagnostico='Raro')

    def test_tramos_y_categorias(self):
        self.assertEqual(anonimizacion.tramo_edad(41), '40-49')
        self.assertEqual(anonimizacion.tramo_edad(85), '80+')
        self.assertEqual(anonimizacion.tramo_edad(None), 'Sin dato')
        self.assertEqual(anonimizacion.categoria_cie10('e11.9'), 'E11')
        self.assertEqual(anonimizacion.categoria_cie10(''), 'Sin código')

    def test_los_grupos_pequenos_se_suprimen(self):
        filas = anonimizacion.reporte_diagnosticos(k=5)
        self.assertEqual(len(filas), 1)
        periodo, tramo, sexo, categoria, casos = filas[0]
        self.assertEqual((tramo, sexo, categoria, casos), ('40-49', 'F', 'E11', 6))
        self.assertEqual(anonimizacion.reporte_diagnosticos(k=1).__len__(), 2)

    def test_el_resultado_no_contiene_identificadores(self):
        with tempfile.TemporaryDirectory() as carpeta:
            archivo = Path(carpeta) / 'reporte.csv'
            call_command('reporte_anonimo', salida=str(archivo), k=1, stdout=io.StringIO())
            texto = archivo.read_text(encoding='utf-8')
        for prohibido in ('Paciente0', 'Apellido', '1000000', 'Unico'):
            self.assertNotIn(prohibido, texto)
        filas = list(csv.reader(texto.splitlines()))
        self.assertEqual(filas[0], anonimizacion.COLUMNAS)
        for fila in filas[1:]:
            self.assertRegex(fila[0], r'^\d{4}-\d{2}$')  # solo año-mes, nunca el día

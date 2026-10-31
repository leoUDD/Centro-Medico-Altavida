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


class RetencionDePersonasTests(TestCase):
    """Contacto a los 24 meses y ficha a los 15 años, siempre contados desde la última atención."""

    def setUp(self):
        from apps.consentimientos import servicio as consentimientos
        self.consentimientos = consentimientos
        self.sede = Sucursal.objects.create(nombre='Sede')
        self.medico = Usuario.objects.create_user('med', email='m@c.cl', password=CLAVE, rol=Usuario.Rol.MEDICO)

    def paciente(self, rut, hace_dias, correo='a@c.cl'):
        p = Paciente.objects.create(rut=rut, nombres='Ana', apellidos='Pérez', email=correo, telefono='+56911112222',
                                    contacto_emergencia_nombre='Luis', contacto_emergencia_telefono='+56933334444')
        inicio = timezone.now() - timedelta(days=hace_dias)
        Cita.objects.create(paciente=p, tipo='CONSULTA', sucursal=self.sede, inicio=inicio, fin=inicio + timedelta(minutes=30))
        d = Diagnostico.objects.create(paciente=p, medico=self.medico, diagnostico='Gastritis')
        Diagnostico.objects.filter(pk=d.pk).update(fecha=inicio)  # la fecha es automática: se fija la de la atención
        return p

    def test_el_contacto_se_elimina_a_los_24_meses_pero_la_ficha_se_conserva(self):
        vieja = self.paciente('12.345.678-5', 800)
        self.consentimientos.otorgar(vieja, 'RECORDATORIOS_CORREO', None)
        self.assertEqual(retencion.purgar()['contactos_vencidos'], 1)
        vieja = Paciente.objects.get(pk=vieja.pk)
        self.assertEqual((vieja.email, vieja.telefono, vieja.contacto_emergencia_nombre), ('', '', ''))
        self.assertEqual(vieja.nombres, 'Ana')  # la identidad de la ficha sigue
        self.assertTrue(vieja.diagnosticos.exists() and vieja.citas.exists())
        self.assertFalse(self.consentimientos.vigente(vieja, 'RECORDATORIOS_CORREO'))
        self.assertTrue(vieja.registros_consentimiento.filter(accion='REVOCADO', canal='RETENCION').exists())

    def test_quien_se_atendio_hace_menos_de_24_meses_conserva_su_contacto(self):
        reciente = self.paciente('11.111.111-1', 300)
        self.assertEqual(retencion.purgar()['contactos_vencidos'], 0)
        self.assertEqual(Paciente.objects.get(pk=reciente.pk).email, 'a@c.cl')

    def test_repetir_la_purga_no_hace_nada_ni_ensucia_la_auditoria(self):
        self.paciente('12.345.678-5', 800)
        retencion.purgar()
        self.assertEqual(retencion.purgar()['contactos_vencidos'], 0)

    def test_la_ficha_se_elimina_recien_pasados_15_anios(self):
        dentro = self.paciente('12.345.678-5', 365 * 14)
        fuera = self.paciente('11.111.111-1', 365 * 16)
        resultado = retencion.purgar()
        self.assertEqual(resultado['fichas_vencidas'], 1)
        self.assertTrue(dentro.diagnosticos.exists())
        fuera = Paciente.objects.get(pk=fuera.pk)
        self.assertFalse(fuera.diagnosticos.exists() or fuera.citas.exists())
        self.assertFalse(hasattr(fuera, 'identidad'))
        self.assertIsNotNone(fuera.datos_bloqueados_desde)

    def test_la_purga_queda_en_la_auditoria_sin_datos_personales(self):
        from apps.auditoria.models import EventoAuditoria, Operacion
        p = self.paciente('11.111.111-1', 365 * 16)
        retencion.purgar()
        eventos = EventoAuditoria.objects.filter(operacion=Operacion.RETENCION_APLICADA, recurso_ref=p.codigo)
        self.assertEqual([e.detalle for e in eventos], [{'regla': 'contacto_vencido'}, {'regla': 'ficha_vencida'}])
        self.assertTrue(eventos.exists())

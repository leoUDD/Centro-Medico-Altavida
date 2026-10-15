import base64
from datetime import time, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.agenda import calendario, disponibilidad
from apps.agenda.models import Cita, HorarioAtencion, HorarioLaboratorio
from apps.laboratorio.models import OrdenExamen, TipoExamen
from apps.notificaciones.models import Notificacion
from apps.pacientes.models import Paciente
from apps.profesionales.models import Especialidad, Profesional
from apps.sucursales.models import Sucursal
from apps.usuarios.models import Usuario

CLAVE = 'Clave-Muy-Segura-123'


def hora_local(dia, texto):
    h, m = (int(x) for x in texto.split(':'))
    return timezone.make_aware(timezone.datetime.combine(dia, time(h, m)))


class AgendaBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dia = timezone.localdate() + timedelta(days=3)
        cls.sede = Sucursal.objects.create(nombre='Sede Central')
        cls.sede2 = Sucursal.objects.create(nombre='Sede Oriente')
        cls.especialidad = Especialidad.objects.create(nombre='Medicina general')
        cls.medico1 = Usuario.objects.create_user('m1', email='m1@c.cl', password=CLAVE, rol='MEDICO', first_name='Camila', last_name='Rojas')
        cls.medico2 = Usuario.objects.create_user('m2', email='m2@c.cl', password=CLAVE, rol='MEDICO', first_name='Felipe', last_name='Navarro')
        cls.prof1 = Profesional.objects.create(usuario=cls.medico1, especialidad=cls.especialidad, titulo='Dra.', duracion_minutos=30)
        cls.prof2 = Profesional.objects.create(
            usuario=cls.medico2, especialidad=cls.especialidad, titulo='Dr.', duracion_minutos=30, ofrece_telemedicina=False,
        )
        for dia_semana in range(7):
            HorarioAtencion.objects.create(
                profesional=cls.prof1, sucursal=cls.sede, dia_semana=dia_semana, hora_inicio=time(9, 0), hora_fin=time(11, 0),
            )
            HorarioAtencion.objects.create(
                profesional=cls.prof2, sucursal=cls.sede, dia_semana=dia_semana, hora_inicio=time(9, 0), hora_fin=time(10, 0),
            )
            HorarioLaboratorio.objects.create(
                sucursal=cls.sede, dia_semana=dia_semana, hora_inicio=time(7, 30), hora_fin=time(12, 0),
                duracion_minutos=30, cupos=1,
            )
        cls.usuario = Usuario.objects.create_user('maria', email='maria@c.cl', password=CLAVE)
        cls.paciente = Paciente.objects.create(
            usuario=cls.usuario, rut='15482331K', nombres='María', apellidos='Fuentes', fecha_nacimiento='1985-03-12',
        )
        cls.otro_usuario = Usuario.objects.create_user('pedro', email='pedro@c.cl', password=CLAVE)
        cls.otro = Paciente.objects.create(
            usuario=cls.otro_usuario, rut='123456785', nombres='Pedro', apellidos='Soto', fecha_nacimiento='1980-01-01',
        )
        cls.perfil = TipoExamen.objects.create(nombre='Perfil lipídico', ayuno_horas='8 a 12', preparacion='')
        cls.hemograma = TipoExamen.objects.create(nombre='Hemograma completo')

    def setUp(self):
        self.client.force_login(self.usuario)

    def reservar_consulta(self, hora='09:00', **extra):
        datos = {
            'accion': 'confirmar', 'especialidad': self.especialidad.pk, 'profesional': self.prof1.pk,
            'modalidad': 'PRESENCIAL', 'motivo': 'Control', 'mes': self.dia.strftime('%Y-%m'),
            'dia': self.dia.isoformat(), 'hora': hora,
        }
        datos.update(extra)
        return self.client.post(reverse('agenda:consulta'), datos)


class DisponibilidadTests(AgendaBase):
    def test_horas_de_consulta_y_exclusion_de_ocupadas_y_canceladas(self):
        horas = disponibilidad.horas_consulta([self.prof1], self.dia)
        self.assertEqual([timezone.localtime(h).strftime('%H:%M') for h in horas], ['09:00', '09:30', '10:00', '10:30'])
        ocupada = Cita.objects.create(
            paciente=self.otro, tipo='CONSULTA', profesional=self.prof1, inicio=hora_local(self.dia, '09:00'),
            fin=hora_local(self.dia, '09:30'),
        )
        self.assertNotIn(hora_local(self.dia, '09:00'), disponibilidad.horas_consulta([self.prof1], self.dia))
        ocupada.estado = 'CANCELADA'
        ocupada.save()
        self.assertIn(hora_local(self.dia, '09:00'), disponibilidad.horas_consulta([self.prof1], self.dia))

    def test_cualquier_profesional_asigna_el_primero_libre(self):
        horas = disponibilidad.horas_consulta([self.prof1, self.prof2], self.dia)
        self.assertEqual(horas[hora_local(self.dia, '09:00')][0], self.prof1)
        Cita.objects.create(
            paciente=self.otro, tipo='CONSULTA', profesional=self.prof1, inicio=hora_local(self.dia, '09:00'),
            fin=hora_local(self.dia, '09:30'),
        )
        horas = disponibilidad.horas_consulta([self.prof1, self.prof2], self.dia)
        self.assertEqual(horas[hora_local(self.dia, '09:00')][0], self.prof2)

    def test_no_ofrece_pasado_ni_mas_alla_del_horizonte(self):
        self.assertEqual(disponibilidad.horas_consulta([self.prof1], timezone.localdate() - timedelta(days=1)), {})
        lejano = timezone.localdate() + timedelta(days=disponibilidad.HORIZONTE_DIAS + 5)
        self.assertEqual(disponibilidad.horas_consulta([self.prof1], lejano), {})

    def test_examenes_con_ayuno_solo_en_la_manana_y_con_cupo(self):
        con_ayuno = disponibilidad.horas_examen(self.sede, self.perfil, self.dia)
        self.assertEqual(max(timezone.localtime(h).strftime('%H:%M') for h in con_ayuno), '09:30')
        sin_ayuno = disponibilidad.horas_examen(self.sede, self.hemograma, self.dia)
        self.assertIn(hora_local(self.dia, '11:30'), sin_ayuno)
        Cita.objects.create(
            paciente=self.otro, tipo='EXAMEN', sucursal=self.sede, inicio=hora_local(self.dia, '08:00'),
            fin=hora_local(self.dia, '08:30'),
        )
        self.assertNotIn(hora_local(self.dia, '08:00'), disponibilidad.horas_examen(self.sede, self.perfil, self.dia))
        self.assertEqual(disponibilidad.horas_examen(self.sede2, self.perfil, self.dia), {})

    def test_calendario_marca_los_dias_con_horas(self):
        dias = disponibilidad.dias_con_horas(lambda d: disponibilidad.horas_consulta([self.prof1], d), self.dia.year, self.dia.month)
        self.assertIn(self.dia, dias)
        mes = calendario.construir(self.dia.year, self.dia.month, dias, self.dia)
        elegido = [c for c in mes['celdas'] if c and c['elegido']]
        self.assertEqual(len(elegido), 1)
        self.assertEqual(calendario.parsear_mes('basura'), (timezone.localdate().year, timezone.localdate().month))


class AgendarConsultaTests(AgendaBase):
    def test_pantalla_muestra_opciones_y_horas(self):
        r = self.client.get(reverse('agenda:consulta'))
        self.assertContains(r, 'Medicina general')
        self.assertContains(r, 'Cualquier profesional disponible')
        r = self.client.post(reverse('agenda:consulta'), {'mes': self.dia.strftime('%Y-%m'), 'dia': self.dia.isoformat()})
        self.assertContains(r, '09:30')

    def test_reserva_confirmada(self):
        r = self.reservar_consulta('09:30')
        self.assertRedirects(r, reverse('notificaciones:lista'), fetch_redirect_response=False)
        cita = Cita.objects.get()
        self.assertEqual((cita.profesional, cita.sucursal, cita.modalidad), (self.prof1, self.sede, 'PRESENCIAL'))
        self.assertEqual(cita.motivo, 'Control')
        aviso = Notificacion.objects.get()
        self.assertEqual((aviso.tipo, aviso.titulo, aviso.cita), ('CITA', 'Tu hora quedó agendada', cita))
        self.assertIn('Dra. Camila Rojas', aviso.detalle)
        with connection.cursor() as cursor:
            cursor.execute('SELECT motivo FROM agenda_cita WHERE id = %s', [cita.pk])
            self.assertNotIn('Control', cursor.fetchone()[0])

    def test_no_se_puede_tomar_una_hora_ocupada(self):
        self.reservar_consulta('09:00')
        self.client.force_login(self.otro_usuario)
        r = self.reservar_consulta('09:00')
        self.assertContains(r, 'Elige un día y una hora disponibles')
        self.assertEqual(Cita.objects.count(), 1)

    def test_confirmar_exige_dia_y_hora(self):
        r = self.reservar_consulta(hora='', dia='')
        self.assertContains(r, 'Elige un día y una hora disponibles')
        self.assertFalse(Cita.objects.exists())

    def test_telemedicina_solo_con_profesionales_que_la_ofrecen(self):
        r = self.reservar_consulta('09:00', profesional=self.prof2.pk, modalidad='TELEMEDICINA')
        self.assertFalse(Cita.objects.exists())
        self.assertContains(r, 'No hay profesionales disponibles con esta selección')
        self.reservar_consulta('09:00', modalidad='TELEMEDICINA')
        cita = Cita.objects.get()
        self.assertIsNone(cita.sucursal)

    def test_cualquier_profesional(self):
        self.reservar_consulta('09:00', profesional='')
        self.client.force_login(self.otro_usuario)
        self.reservar_consulta('09:00', profesional='')
        self.assertEqual(set(Cita.objects.values_list('profesional', flat=True)), {self.prof1.pk, self.prof2.pk})

    def test_no_permite_dos_citas_al_mismo_tiempo(self):
        self.reservar_consulta('09:00')
        r = self.reservar_consulta('09:00', profesional=self.prof2.pk)
        self.assertContains(r, 'Ya tienes otra cita a esa hora')
        self.assertEqual(Cita.objects.count(), 1)

    def test_reprogramar_cancela_la_cita_original(self):
        self.reservar_consulta('09:00')
        original = Cita.objects.get()
        self.reservar_consulta('10:00', reprogramar=original.pk)
        original.refresh_from_db()
        self.assertEqual(original.estado, 'CANCELADA')
        self.assertEqual(Cita.objects.exclude(estado='CANCELADA').get().inicio, hora_local(self.dia, '10:00'))

    def test_el_paciente_no_reprograma_citas_ajenas(self):
        self.client.force_login(self.otro_usuario)
        self.reservar_consulta('09:00')
        ajena = Cita.objects.get()
        self.client.force_login(self.usuario)
        self.reservar_consulta('10:00', reprogramar=ajena.pk)
        ajena.refresh_from_db()
        self.assertEqual(ajena.estado, 'AGENDADA')
        self.assertEqual(Cita.objects.count(), 2)

    def test_confirmar_y_cancelar_asistencia(self):
        self.reservar_consulta('09:00')
        cita = Cita.objects.get()
        self.client.post(reverse('agenda:confirmar', args=[cita.pk]))
        cita.refresh_from_db()
        self.assertEqual(cita.estado, 'CONFIRMADA')
        self.client.post(reverse('agenda:cancelar', args=[cita.pk]))
        cita.refresh_from_db()
        self.assertEqual(cita.estado, 'CANCELADA')
        self.assertIn(hora_local(self.dia, '09:00'), disponibilidad.horas_consulta([self.prof1], self.dia))

    def test_no_se_actua_sobre_citas_ajenas_ni_por_get(self):
        self.client.force_login(self.otro_usuario)
        self.reservar_consulta('09:00')
        ajena = Cita.objects.get()
        self.client.force_login(self.usuario)
        self.assertEqual(self.client.post(reverse('agenda:cancelar', args=[ajena.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('agenda:cancelar', args=[ajena.pk])).status_code, 405)

    def test_notificaciones_muestran_acciones_de_la_cita(self):
        self.reservar_consulta('09:00')
        r = self.client.get(reverse('notificaciones:lista'))
        self.assertContains(r, 'Confirmar asistencia')
        self.assertContains(r, 'Cambiar hora')
        self.assertContains(r, 'Cancelar hora')

    def test_solo_pacientes(self):
        self.client.force_login(self.medico1)
        self.assertEqual(self.client.get(reverse('agenda:consulta')).status_code, 403)
        self.assertEqual(self.client.get(reverse('agenda:examen')).status_code, 403)


class AgendarExamenTests(AgendaBase):
    def reservar_examen(self, hora='08:00', tipo=None, **extra):
        datos = {
            'accion': 'confirmar', 'tipo_examen': (tipo or self.perfil).pk, 'sucursal': self.sede.pk,
            'mes': self.dia.strftime('%Y-%m'), 'dia': self.dia.isoformat(), 'hora': hora,
        }
        datos.update(extra)
        return self.client.post(reverse('agenda:examen'), datos)

    def test_con_orden_de_altavida(self):
        orden = OrdenExamen.objects.create(paciente=self.paciente, tipo_examen=self.perfil, medico=self.medico1)
        r = self.client.get(reverse('agenda:examen'))
        self.assertContains(r, 'Orden emitida en Altavida')
        r = self.reservar_examen(orden=f'altavida:{orden.pk}')
        self.assertRedirects(r, reverse('notificaciones:lista'), fetch_redirect_response=False)
        cita = Cita.objects.get()
        orden.refresh_from_db()
        self.assertEqual((cita.orden, orden.utilizada), (orden, True))
        self.assertIn('Ayuno de 8 a 12 horas', Notificacion.objects.get().detalle)
        self.client.post(reverse('agenda:cancelar', args=[cita.pk]))
        orden.refresh_from_db()
        self.assertFalse(orden.utilizada)

    def test_orden_externa_valida_se_guarda_cifrada(self):
        pdf = SimpleUploadedFile('orden.pdf', b'%PDF-1.4 contenido', content_type='application/pdf')
        self.reservar_examen(orden='externa', archivo=pdf)
        cita = Cita.objects.get()
        self.assertEqual(base64.b64decode(cita.orden_externa), b'%PDF-1.4 contenido')
        self.assertEqual((cita.orden_externa_tipo, cita.orden_externa_nombre), ('application/pdf', 'orden.pdf'))
        with connection.cursor() as cursor:
            cursor.execute('SELECT orden_externa FROM agenda_cita WHERE id = %s', [cita.pk])
            self.assertNotIn('JVBER', cursor.fetchone()[0])

    def test_orden_externa_invalida(self):
        r = self.reservar_examen(orden='externa')
        self.assertContains(r, 'Adjunta una orden médica')
        falso = SimpleUploadedFile('orden.pdf', b'no soy un pdf', content_type='application/pdf')
        r = self.reservar_examen(orden='externa', archivo=falso)
        self.assertContains(r, 'PDF o una foto')
        grande = SimpleUploadedFile('orden.pdf', b'%PDF' + b'0' * (5 * 1024 * 1024), content_type='application/pdf')
        r = self.reservar_examen(orden='externa', archivo=grande)
        self.assertContains(r, 'más de 5 MB')
        self.assertFalse(Cita.objects.exists())

    def test_la_orden_de_otro_paciente_no_sirve(self):
        ajena = OrdenExamen.objects.create(paciente=self.otro, tipo_examen=self.perfil, medico=self.medico1)
        pdf = SimpleUploadedFile('o.pdf', b'%PDF-1', content_type='application/pdf')
        self.reservar_examen(orden=f'altavida:{ajena.pk}', archivo=pdf)
        ajena.refresh_from_db()
        self.assertFalse(ajena.utilizada)
        self.assertIsNone(Cita.objects.get().orden)

    def test_ayuno_no_ofrece_horas_tardias_y_cupo_se_agota(self):
        pdf = lambda: SimpleUploadedFile('o.pdf', b'%PDF-1', content_type='application/pdf')  # noqa: E731
        self.reservar_examen('11:00', orden='externa', archivo=pdf())
        self.assertFalse(Cita.objects.exists())
        self.reservar_examen('08:00', orden='externa', archivo=pdf())
        self.client.force_login(self.otro_usuario)
        self.reservar_examen('08:00', orden='externa', archivo=pdf())
        self.assertEqual(Cita.objects.count(), 1)

    def test_sin_ayuno_se_puede_tarde(self):
        pdf = SimpleUploadedFile('o.pdf', b'%PDF-1', content_type='application/pdf')
        self.reservar_examen('11:00', tipo=self.hemograma, orden='externa', archivo=pdf)
        self.assertEqual(Cita.objects.get().tipo_examen, self.hemograma)

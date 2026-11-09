"""Oposición o bloqueo de un tratamiento: solicitud, verificación, ejecución, propagación a los procesos y levantamiento."""
from datetime import timedelta
from unittest import mock

from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.agenda.models import Cita
from apps.auditoria.models import EventoAuditoria, Operacion
from apps.consentimientos import servicio as consentimientos
from apps.consentimientos.models import Consentimiento, RegistroConsentimiento
from apps.derechos import oposiciones, servicio
from apps.derechos.models import OposicionTratamiento, SolicitudDerecho
from apps.fichas_clinicas.models import Diagnostico
from apps.notificaciones import recordatorios
from apps.notificaciones.models import PreferenciasNotificacion, Recordatorio
from apps.profesionales.models import Especialidad, Profesional
from apps.seguridad import anonimizacion
from apps.sucursales.models import Sucursal
from apps.usuarios.models import Usuario

from .test_consentimientos import CLAVE, CORREO, SMS
from .test_derechos import Flujo

T = SolicitudDerecho.Tipo
E = SolicitudDerecho.Estado
R = SolicitudDerecho.Resolucion
F = SolicitudDerecho.Fundamento
TR = SolicitudDerecho.Tratamiento


class OposicionBase(Flujo):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.sede = Sucursal.objects.create(nombre='Sede Central')
        medico = Usuario.objects.create_user('dra', email='d@c.cl', password=CLAVE, rol='MEDICO', first_name='C', last_name='R')
        cls.profesional = Profesional.objects.create(usuario=medico, titulo='Dra.', especialidad=Especialidad.objects.create(nombre='General'))

    def cita(self, paciente=None):
        inicio = timezone.now() + timedelta(hours=24)
        cita = Cita.objects.create(
            paciente=paciente or self.ana, tipo='CONSULTA', profesional=self.profesional, sucursal=self.sede,
            modalidad='PRESENCIAL', inicio=inicio, fin=inicio + timedelta(minutes=30), estado='AGENDADA',
        )
        Cita.objects.filter(pk=cita.pk).update(creada=timezone.now() - timedelta(hours=72))
        return cita

    def oponer(self, tratamiento, paciente=None):
        """Solicitud verificada (solo con la contraseña, nivel 1) y acogida por el Encargado."""
        paciente = paciente or self.ana
        usuario = paciente.usuario
        s = servicio.crear(paciente, paciente, T.OPOSICION, usuario, tratamiento=tratamiento)
        servicio.verificar(s, usuario, True)
        servicio.resolver(s, self.encargado, R.EJECUTADA)
        s.refresh_from_db()
        return s


class SolicitudYVerificacionTests(OposicionBase):
    def test_la_solicitud_nace_en_verificacion_con_plazo_y_pide_solo_la_contrasena(self):
        s = self.crear(T.OPOSICION, tratamiento=TR.RECORDATORIOS_SMS)
        self.assertEqual((s.estado, s.nivel_requerido, s.tratamiento), (E.EN_VERIFICACION, 1, TR.RECORDATORIOS_SMS))
        self.assertEqual(s.plazo_hasta, (s.recibida_en + timedelta(days=30)).date())
        self.assertEqual(len(mail.outbox), 0)  # no hay código: la oposición se puede deshacer y no expone datos
        self.assertFalse(OposicionTratamiento.objects.exists())  # nada se bloquea hasta resolver

    def test_exige_un_tratamiento_de_la_lista(self):
        for malo in ('', 'FICHA_CLINICA', 'DIAGNOSTICOS'):
            with self.assertRaises(servicio.DerechosError):
                self.crear(T.OPOSICION, tratamiento=malo)
        self.assertFalse(SolicitudDerecho.objects.exists())

    def test_la_atencion_clinica_no_es_un_tratamiento_oponible(self):
        valores = set(TR.values)
        self.assertEqual(valores, {'RECORDATORIOS_CORREO', 'RECORDATORIOS_SMS', 'ESTADISTICAS'})

    def test_un_solicitante_no_verificado_no_logra_ningun_bloqueo(self):
        s = self.crear(T.OPOSICION, tratamiento=TR.ESTADISTICAS)
        with self.assertRaises(servicio.DerechosError):
            servicio.resolver(s, self.encargado, R.EJECUTADA)
        self.assertFalse(OposicionTratamiento.objects.exists())
        self.assertFalse(oposiciones.hay_oposicion(self.ana, TR.ESTADISTICAS))
        # Con la contraseña equivocada tampoco avanza, y queda registrado.
        with self.assertRaises(servicio.DerechosError):
            servicio.verificar(s, self.u_ana, False)
        s.refresh_from_db()
        self.assertEqual(s.estado, E.EN_VERIFICACION)
        self.assertTrue(EventoAuditoria.objects.filter(operacion=Operacion.DERECHO_VERIFICACION, resultado='DENEGADO').exists())

    def test_se_puede_rechazar_sin_verificar_y_no_bloquea(self):
        s = self.crear(T.OPOSICION, tratamiento=TR.ESTADISTICAS)
        servicio.resolver(s, self.encargado, R.RECHAZADA, F.IDENTIDAD_NO_VERIFICADA)
        self.assertFalse(OposicionTratamiento.objects.exists())

    def test_un_tercero_sin_representacion_no_puede_pedirlo_por_otra_persona(self):
        with self.assertRaises(servicio.DerechosError):
            servicio.crear(self.beto, self.ana, T.OPOSICION, self.u_beto, tratamiento=TR.RECORDATORIOS_CORREO)

    def test_un_menor_no_se_opone_por_si_mismo(self):
        with self.assertRaises(servicio.DerechosError):
            servicio.crear(self.nino, self.nino, T.OPOSICION, self.u_nino, tratamiento=TR.RECORDATORIOS_CORREO)

    def test_una_solicitud_abierta_por_tratamiento_pero_se_pueden_pedir_varios(self):
        self.crear(T.OPOSICION, tratamiento=TR.RECORDATORIOS_CORREO)
        self.crear(T.OPOSICION, tratamiento=TR.RECORDATORIOS_SMS)  # otro tratamiento: permitido
        with self.assertRaises(servicio.DerechosError):
            self.crear(T.OPOSICION, tratamiento=TR.RECORDATORIOS_CORREO)  # el mismo, ya en curso


class EjecucionYPropagacionTests(OposicionBase):
    def test_acoger_bloquea_el_tratamiento_y_lo_deja_en_la_auditoria(self):
        s = self.oponer(TR.ESTADISTICAS)
        self.assertEqual((s.estado, s.resolucion), (E.RESUELTA, R.EJECUTADA))
        self.assertTrue(oposiciones.hay_oposicion(self.ana, TR.ESTADISTICAS))
        self.assertFalse(oposiciones.hay_oposicion(self.ana, TR.RECORDATORIOS_SMS))  # solo ese tratamiento
        self.assertFalse(oposiciones.hay_oposicion(self.beto, TR.ESTADISTICAS))  # solo esa persona
        evento = EventoAuditoria.objects.get(operacion=Operacion.OPOSICION)
        self.assertEqual((evento.detalle['tratamiento'], evento.detalle['estado_nuevo']), ('ESTADISTICAS', 'VIGENTE'))
        self.assertIn('Puedes levantar el bloqueo', s.respuesta)

    def test_rechazar_no_bloquea_nada(self):
        s = self.crear(T.OPOSICION, tratamiento=TR.ESTADISTICAS)
        servicio.verificar(s, self.u_ana, True)
        servicio.resolver(s, self.encargado, R.RECHAZADA, F.SOLICITUD_INFUNDADA)
        self.assertFalse(OposicionTratamiento.objects.exists())

    def test_oponerse_a_un_canal_revoca_el_consentimiento_cancela_lo_pendiente_y_no_envia(self):
        PreferenciasNotificacion.objects.create(paciente=self.ana, canal_correo=True, canal_sms=False)
        consentimientos.otorgar(self.ana, CORREO, self.u_ana)
        self.cita()
        recordatorios.generar()
        self.assertEqual(Recordatorio.objects.filter(estado='PENDIENTE').count(), 1)
        s = self.oponer(TR.RECORDATORIOS_CORREO)
        self.assertEqual(Consentimiento.objects.get(paciente=self.ana, finalidad__codigo=CORREO).estado, 'REVOCADO')
        ultimo = RegistroConsentimiento.objects.filter(paciente=self.ana).last()
        self.assertEqual((ultimo.accion, ultimo.canal), ('REVOCADO', 'OPOSICION'))
        self.assertEqual(Recordatorio.objects.get().estado, 'CANCELADO')
        self.assertIn('cancelamos 1 recordatorio', s.respuesta)
        with mock.patch('apps.notificaciones.recordatorios.send_mail') as enviar:
            self.assertEqual(recordatorios.enviar_pendientes(), (0, 0))
        enviar.assert_not_called()

    def test_el_generador_no_programa_recordatorios_de_un_canal_bloqueado(self):
        PreferenciasNotificacion.objects.create(paciente=self.ana, canal_correo=True, canal_sms=True)
        consentimientos.otorgar(self.ana, CORREO, self.u_ana)
        consentimientos.otorgar(self.ana, SMS, self.u_ana)
        self.oponer(TR.RECORDATORIOS_SMS)
        self.cita()
        recordatorios.generar()
        self.assertEqual(set(Recordatorio.objects.values_list('canal', flat=True)), {'CORREO'})  # el otro canal sigue

    def test_un_recordatorio_programado_antes_del_bloqueo_se_cancela_al_enviar_aunque_siga_el_consentimiento(self):
        PreferenciasNotificacion.objects.create(paciente=self.ana, canal_correo=True, canal_sms=False)
        consentimientos.otorgar(self.ana, CORREO, self.u_ana)
        self.cita()
        recordatorios.generar()
        # Bloqueo registrado sin pasar por la ejecución (p. ej. desde otro proceso): el enviador igual lo respeta.
        solicitud = self.crear(T.OPOSICION, tratamiento=TR.RECORDATORIOS_CORREO)
        OposicionTratamiento.objects.create(paciente=self.ana, tratamiento=TR.RECORDATORIOS_CORREO, solicitud=solicitud)
        with mock.patch('apps.notificaciones.recordatorios.send_mail') as enviar:
            recordatorios.enviar_pendientes()
        enviar.assert_not_called()
        self.assertEqual(Recordatorio.objects.get().error, 'Tratamiento bloqueado por el titular')

    def test_con_el_bloqueo_vigente_no_se_puede_volver_a_autorizar(self):
        self.oponer(TR.RECORDATORIOS_CORREO)
        with self.assertRaises(consentimientos.ConsentimientoError):
            consentimientos.otorgar(self.ana, CORREO, self.u_ana)
        consentimientos.otorgar(self.ana, SMS, self.u_ana)  # otro canal: sin problema

    def test_las_estadisticas_dejan_de_contar_a_quien_se_opuso(self):
        for paciente in (self.ana, self.beto):
            Diagnostico.objects.create(paciente=paciente, medico=self.medico, diagnostico='Gastritis', codigo_cie10='K29.7')
        self.assertEqual(sum(f[-1] for f in anonimizacion.reporte_diagnosticos(k=1)), 2)
        self.oponer(TR.ESTADISTICAS)
        self.assertEqual(sum(f[-1] for f in anonimizacion.reporte_diagnosticos(k=1)), 1)
        # La atención clínica no cambia: la ficha sigue intacta.
        self.assertEqual(Diagnostico.objects.filter(paciente=self.ana).count(), 1)


class LevantarBloqueoTests(OposicionBase):
    def test_con_la_contrasena_correcta_se_levanta_y_se_puede_volver_a_autorizar(self):
        s = self.oponer(TR.RECORDATORIOS_CORREO)
        o = OposicionTratamiento.objects.get()
        servicio.levantar_oposicion(o, self.ana, self.u_ana, True)
        o.refresh_from_db()
        self.assertFalse(o.vigente)
        self.assertEqual(o.levantada_por, self.u_ana.pk)
        self.assertFalse(oposiciones.hay_oposicion(self.ana, TR.RECORDATORIOS_CORREO))
        self.assertFalse(consentimientos.vigente(self.ana, CORREO))  # levantar no reactiva el consentimiento por sí solo
        consentimientos.otorgar(self.ana, CORREO, self.u_ana)
        self.assertTrue(consentimientos.vigente(self.ana, CORREO))
        self.assertEqual(
            list(EventoAuditoria.objects.filter(operacion=Operacion.OPOSICION).values_list('detalle__estado_nuevo', flat=True)),
            ['VIGENTE', 'LEVANTADA'])
        self.assertEqual(s.oposiciones.count(), 1)  # la fila se conserva: prueba desde y hasta cuándo estuvo bloqueado

    def test_con_la_contrasena_equivocada_no_se_levanta_y_queda_registrado(self):
        self.oponer(TR.ESTADISTICAS)
        o = OposicionTratamiento.objects.get()
        with self.assertRaises(servicio.DerechosError):
            servicio.levantar_oposicion(o, self.ana, self.u_ana, False)
        self.assertTrue(oposiciones.hay_oposicion(self.ana, TR.ESTADISTICAS))
        self.assertTrue(EventoAuditoria.objects.filter(operacion=Operacion.OPOSICION, resultado='DENEGADO').exists())

    def test_no_se_levanta_dos_veces_ni_se_puede_tener_dos_bloqueos_vigentes(self):
        self.oponer(TR.ESTADISTICAS)
        o = OposicionTratamiento.objects.get()
        servicio.levantar_oposicion(o, self.ana, self.u_ana, True)
        with self.assertRaises(servicio.DerechosError):
            servicio.levantar_oposicion(o, self.ana, self.u_ana, True)
        servicio.cerrar(SolicitudDerecho.objects.get(), self.encargado)  # la solicitud anterior debe estar cerrada
        self.oponer(TR.ESTADISTICAS)  # se puede volver a bloquear después de levantar
        self.assertEqual(OposicionTratamiento.objects.filter(levantada_en__isnull=True).count(), 1)

    def test_un_tercero_no_puede_levantar_el_bloqueo_de_otro(self):
        self.oponer(TR.ESTADISTICAS)
        o = OposicionTratamiento.objects.get()
        with self.assertRaises(servicio.DerechosError):
            servicio.levantar_oposicion(o, self.beto, self.u_beto, True)
        self.client.force_login(self.u_beto)
        self.assertEqual(self.client.post(reverse('derechos:levantar', args=[o.pk]), {'clave': CLAVE}).status_code, 404)
        self.assertTrue(oposiciones.hay_oposicion(self.ana, TR.ESTADISTICAS))


class OposicionPorPantallaYExportacionTests(OposicionBase):
    def test_flujo_completo_desde_el_portal_y_la_bandeja(self):
        self.client.force_login(self.u_ana)
        self.assertContains(self.client.get(reverse('derechos:nueva')), 'oponerte o bloquear')
        r = self.client.post(reverse('derechos:nueva'), {'tipo': T.OPOSICION, 'tratamiento': TR.ESTADISTICAS})
        s = SolicitudDerecho.objects.get()
        self.assertRedirects(r, reverse('derechos:detalle', args=[s.codigo]))
        self.client.post(reverse('derechos:verificar', args=[s.codigo]), {'clave': 'mala'})
        s.refresh_from_db()
        self.assertEqual(s.estado, E.EN_VERIFICACION)
        self.client.post(reverse('derechos:verificar', args=[s.codigo]), {'clave': CLAVE})
        s.refresh_from_db()
        self.assertEqual(s.estado, E.EN_EVALUACION)
        self.client.force_login(self.encargado)
        self.assertContains(self.client.get(reverse('derechos:gestionar', args=[s.codigo])), 'Tratamiento a bloquear')
        self.client.post(reverse('derechos:resolver', args=[s.codigo]), {'resolucion': 'EJECUTADA'})
        self.client.force_login(self.u_ana)
        r = self.client.get(reverse('derechos:mis'))
        self.assertContains(r, 'Tratamientos que bloqueaste')
        self.assertContains(r, 'Levantar bloqueo')
        o = OposicionTratamiento.objects.get()
        self.client.post(reverse('derechos:levantar', args=[o.pk]), {'clave': 'mala'})
        o.refresh_from_db()
        self.assertTrue(o.vigente)
        self.client.post(reverse('derechos:levantar', args=[o.pk]), {'clave': CLAVE})
        o.refresh_from_db()
        self.assertFalse(o.vigente)

    def test_la_exportacion_del_titular_incluye_sus_oposiciones(self):
        self.oponer(TR.ESTADISTICAS)
        datos = servicio.armar_exportacion(self.ana)
        self.assertEqual([o['tratamiento'] for o in datos['oposiciones_al_tratamiento']], ['ESTADISTICAS'])
        self.assertEqual(servicio.armar_exportacion(self.beto)['oposiciones_al_tratamiento'], [])

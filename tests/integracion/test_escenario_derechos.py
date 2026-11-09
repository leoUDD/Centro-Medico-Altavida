"""
Escenario de prueba de los mecanismos de derechos: una solicitud concreta por mecanismo y su variante no verificada.

Paciente del caso: Ana (con ficha clínica, un diagnóstico, una cita y recordatorios por correo autorizados).
Otra paciente, Beto, sirve para comprobar que nadie ve ni recibe datos ajenos.
"""
import json

from django.core import mail
from django.urls import reverse

from apps.auditoria.models import EventoAuditoria, Operacion
from apps.consentimientos import servicio as consentimientos
from apps.consentimientos.models import Consentimiento
from apps.derechos import oposiciones, servicio
from apps.derechos.models import SolicitudDerecho
from apps.fichas_clinicas.models import Diagnostico
from apps.notificaciones.models import PreferenciasNotificacion

from .test_consentimientos import CLAVE, CORREO
from .test_derechos import codigo_enviado
from .test_oposicion import OposicionBase

T = SolicitudDerecho.Tipo
E = SolicitudDerecho.Estado
R = SolicitudDerecho.Resolucion
F = SolicitudDerecho.Fundamento
TR = SolicitudDerecho.Tratamiento


class EscenarioBase(OposicionBase):
    def setUp(self):
        super().setUp()
        consentimientos.otorgar(self.ana, CORREO, self.u_ana)
        PreferenciasNotificacion.objects.create(paciente=self.ana, canal_correo=True, canal_sms=False)
        self.diagnostico = Diagnostico.objects.create(
            paciente=self.ana, medico=self.medico, diagnostico='Gastritis', codigo_cie10='K29.7')
        Diagnostico.objects.create(paciente=self.beto, medico=self.medico, diagnostico='Migraña', codigo_cie10='G43.9')
        self.cita()


class Mecanismo1CanalYModeloTests(EscenarioBase):
    def test_la_solicitud_entra_por_el_portal_y_queda_con_codigo_plazo_estado_e_historial(self):
        self.client.force_login(self.u_ana)
        self.client.post(reverse('derechos:nueva'), {'tipo': T.ACCESO})
        s = SolicitudDerecho.objects.get()
        self.assertRegex(s.codigo, r'^SD-[0-9A-F]{8}$')
        self.assertEqual((s.paciente, s.solicitante, s.tipo, s.estado), (self.ana, self.ana, T.ACCESO, E.EN_VERIFICACION))
        self.assertIsNotNone(s.plazo_hasta)
        self.assertEqual(list(s.historial.values_list('estado_nuevo', flat=True)), ['RECIBIDA', 'EN_VERIFICACION'])
        self.assertContains(self.client.get(reverse('derechos:mis')), s.codigo)  # seguimiento del titular

    def test_cada_tipo_de_solicitud_se_registra_con_el_mismo_modelo(self):
        s1 = self.crear(T.ACCESO)
        s2 = self.crear(T.RECTIFICACION, campo='telefono', valor='+56 9 5555 0000')
        s3 = self.crear(T.OPOSICION, tratamiento=TR.ESTADISTICAS)
        self.assertEqual({s.tipo for s in SolicitudDerecho.objects.all()}, {T.ACCESO, T.RECTIFICACION, T.OPOSICION})
        self.assertTrue(all(s.estado == E.EN_VERIFICACION and s.plazo_hasta for s in (s1, s2, s3)))


class Mecanismo2VerificacionTests(EscenarioBase):
    def test_otra_persona_con_sesion_no_puede_ver_verificar_ni_descargar_la_solicitud_de_ana(self):
        s = self.crear(T.ACCESO)
        self.client.force_login(self.u_beto)
        for nombre in ('detalle', 'reenviar', 'descargar'):
            r = self.client.post(reverse(f'derechos:{nombre}', args=[s.codigo])) if nombre != 'detalle' \
                else self.client.get(reverse('derechos:detalle', args=[s.codigo]))
            self.assertEqual(r.status_code, 404, nombre)
        r = self.client.post(reverse('derechos:verificar', args=[s.codigo]), {'clave': CLAVE, 'codigo': codigo_enviado()})
        self.assertEqual(r.status_code, 404)
        s.refresh_from_db()
        self.assertEqual(s.estado, E.EN_VERIFICACION)

    def test_clave_o_codigo_incorrectos_no_verifican(self):
        s = self.crear(T.ACCESO)
        with self.assertRaises(servicio.DerechosError):
            servicio.verificar(s, self.u_ana, False, codigo_enviado())  # clave mala, código bueno
        with self.assertRaises(servicio.DerechosError):
            servicio.verificar(s, self.u_ana, True, '000000')  # clave buena, código malo
        s.refresh_from_db()
        self.assertEqual((s.estado, s.verificada_en), (E.EN_VERIFICACION, None))

    def test_solo_con_la_identidad_verificada_se_atiende_la_solicitud(self):
        s = self.crear(T.ACCESO)
        servicio.verificar(s, self.u_ana, True, codigo_enviado())
        s.refresh_from_db()
        self.assertEqual(s.estado, E.EN_EVALUACION)
        self.assertIsNotNone(s.verificada_en)


class Mecanismo3AccesoYPortabilidadTests(EscenarioBase):
    def descarga(self, tipo):
        s = self.verificada(tipo)
        servicio.resolver(s, self.encargado, R.EJECUTADA)
        self.client.force_login(self.u_ana)
        r = self.client.post(reverse('derechos:descargar', args=[s.codigo]))
        self.assertEqual(r.status_code, 200)
        self.assertIn('application/json', r['Content-Type'])
        return json.loads(r.content), r.content.decode()

    def test_acceso_entrega_todos_los_datos_de_ana_y_solo_los_suyos(self):
        datos, texto = self.descarga(T.ACCESO)
        self.assertEqual(datos['paciente'], self.ana.codigo)
        self.assertEqual(datos['identidad']['nombres'], 'Ana')
        self.assertEqual([d['diagnostico'] for d in datos['diagnosticos']], ['Gastritis'])
        self.assertEqual(len(datos['citas']), 1)
        self.assertIn('informacion_sobre_el_tratamiento', datos)
        for ajeno in (self.beto.codigo, self.beto.nombres, self.beto.email, self.beto.rut_formateado, 'Migraña'):
            self.assertNotIn(ajeno, texto)

    def test_portabilidad_entrega_el_mismo_contenido_estructurado_sin_la_parte_informativa(self):
        datos, texto = self.descarga(T.PORTABILIDAD)
        self.assertEqual(datos['identidad']['email'], self.ana.email)
        self.assertEqual(datos['diagnosticos'][0]['codigo_cie10'], 'K29.7')
        self.assertNotIn('informacion_sobre_el_tratamiento', datos)
        self.assertNotIn(self.beto.codigo, texto)


class Mecanismo4RectificacionTests(EscenarioBase):
    def test_se_corrige_el_telefono_y_queda_el_registro_del_cambio(self):
        antes = self.ana.telefono
        s = self.verificada(T.RECTIFICACION, campo='telefono', valor='+56 9 5555 0000')
        servicio.resolver(s, self.encargado, R.EJECUTADA)
        self.ana.refresh_from_db()
        self.assertNotEqual(self.ana.telefono, antes)
        self.assertEqual(self.ana.telefono, '+56955550000')
        evento = EventoAuditoria.objects.get(operacion=Operacion.RECTIFICACION)
        self.assertEqual((evento.recurso_ref, evento.actor_id, evento.detalle['campo'], evento.detalle['codigo_solicitud']),
                         (self.ana.codigo, self.encargado.pk, 'telefono', s.codigo))
        self.assertNotIn('5555', str(evento.detalle))  # el registro dice qué campo y por qué solicitud, no copia el dato
        self.assertEqual(list(s.historial.values_list('estado_nuevo', flat=True))[-1], 'RESUELTA')


class Mecanismo5SupresionTests(EscenarioBase):
    def test_informa_que_se_elimina_que_se_bloquea_por_ley_y_como_se_propaga(self):
        s = self.verificada(T.SUPRESION)
        servicio.resolver(s, self.encargado, R.EJECUTADA)
        self.assertEqual((s.resolucion, s.fundamento), (R.PARCIAL, F.CONSERVACION_LEGAL))
        for parte in ('Se eliminó:', 'Se bloqueó por obligación legal:', 'Cómo se propagó:',
                      'tu cuenta del portal', 'tu ficha clínica', 'Sesiones abiertas', 'Respaldos de la base de datos'):
            self.assertIn(parte, s.respuesta)
        self.assertIn('conservarse por ley hasta el', s.respuesta)

    def test_lo_que_se_elimina_se_elimina_y_lo_que_se_bloquea_se_conserva(self):
        s = self.verificada(T.SUPRESION)
        servicio.resolver(s, self.encargado, R.EJECUTADA)
        self.ana.refresh_from_db()
        self.u_ana.refresh_from_db()
        self.assertFalse(self.u_ana.is_active)  # eliminado: la cuenta
        self.assertEqual(Consentimiento.objects.get(paciente=self.ana).estado, 'REVOCADO')  # eliminado: la autorización
        self.assertEqual(Diagnostico.objects.filter(paciente=self.ana).count(), 1)  # bloqueado: la ficha se conserva
        self.assertIsNotNone(self.ana.datos_bloqueados_desde)

    def test_se_propaga_a_los_procesos_que_dependian_de_lo_eliminado(self):
        from apps.notificaciones import recordatorios
        s = self.verificada(T.SUPRESION)
        servicio.resolver(s, self.encargado, R.EJECUTADA)
        self.ana.refresh_from_db()
        self.assertEqual(recordatorios.generar(), 0)  # ya no se programan recordatorios para Ana
        with self.assertRaises(consentimientos.ConsentimientoError):
            consentimientos.otorgar(self.ana, CORREO, self.u_ana)
        with self.assertRaises(servicio.DerechosError):
            servicio.crear(self.ana, self.ana, T.ACCESO, self.u_ana)


class Mecanismo6OposicionTests(EscenarioBase):
    def test_ana_se_opone_a_los_recordatorios_por_correo_y_deja_de_recibirlos(self):
        from apps.notificaciones import recordatorios
        s = self.oponer(TR.RECORDATORIOS_CORREO)
        self.assertEqual(s.estado, E.RESUELTA)
        self.assertTrue(oposiciones.hay_oposicion(self.ana, TR.RECORDATORIOS_CORREO))
        self.assertEqual(recordatorios.generar(), 0)
        self.assertEqual(len([m for m in mail.outbox if 'Recordatorio' in m.subject]), 0)


class Mecanismo7SolicitanteNoVerificadoTests(EscenarioBase):
    """Para cada mecanismo: una solicitud real que no pasó la verificación no cambia ni entrega nada."""

    def test_ningun_derecho_se_ejecuta_sin_verificar_la_identidad(self):
        casos = [
            (T.ACCESO, {}),
            (T.PORTABILIDAD, {}),
            (T.RECTIFICACION, {'campo': 'telefono', 'valor': '+56 9 5555 0000'}),
            (T.SUPRESION, {}),
            (T.OPOSICION, {'tratamiento': TR.RECORDATORIOS_CORREO}),
        ]
        telefono = self.ana.telefono
        for tipo, extra in casos:
            with self.subTest(tipo=tipo):
                s = self.crear(tipo, **extra)
                for resolucion in (R.EJECUTADA, R.PARCIAL):
                    with self.assertRaises(servicio.DerechosError):
                        servicio.resolver(s, self.encargado, resolucion)
                s.refresh_from_db()
                self.assertEqual((s.estado, s.resolucion, s.verificada_en), (E.EN_VERIFICACION, '', None))
                self.assertFalse(servicio.puede_descargar(s))
                servicio.resolver(s, self.encargado, R.RECHAZADA, F.IDENTIDAD_NO_VERIFICADA)  # lo único posible
                s.refresh_from_db()
                self.assertEqual((s.estado, s.fundamento), (E.RESUELTA, F.IDENTIDAD_NO_VERIFICADA))
                self.assertFalse(servicio.puede_descargar(s))
                servicio.cerrar(s, self.encargado)
        self.ana.refresh_from_db()
        self.u_ana.refresh_from_db()
        self.assertEqual(self.ana.telefono, telefono)  # nada se rectificó
        self.assertTrue(self.u_ana.is_active)  # nada se suprimió
        self.assertEqual(Consentimiento.objects.get(paciente=self.ana).estado, 'OTORGADO')
        self.assertEqual(Diagnostico.objects.filter(paciente=self.ana).count(), 1)
        self.assertFalse(oposiciones.hay_oposicion(self.ana, TR.RECORDATORIOS_CORREO))  # nada se bloqueó

    def test_la_descarga_de_una_solicitud_sin_verificar_se_niega_por_pantalla(self):
        s = self.crear(T.ACCESO)
        self.client.force_login(self.u_ana)
        r = self.client.post(reverse('derechos:descargar', args=[s.codigo]), follow=True)
        self.assertNotIn('application/json', r['Content-Type'])
        s.refresh_from_db()
        self.assertEqual(s.descargas, 0)

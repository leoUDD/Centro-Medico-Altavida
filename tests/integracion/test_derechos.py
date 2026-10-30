"""Ejercicio de derechos: flujo con estados, verificación proporcional al riesgo, ejecución y control de acceso."""
import json
import re
from datetime import timedelta

from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.auditoria.models import EventoAuditoria, Operacion
from apps.consentimientos import servicio as consentimientos
from apps.consentimientos.models import Consentimiento, Representacion
from apps.derechos import servicio
from apps.derechos.models import HistorialSolicitud, SolicitudDerecho
from apps.fichas_clinicas.models import Diagnostico
from apps.notificaciones.models import Notificacion
from apps.seguridad.indice import indice_correo
from apps.usuarios.models import Usuario

from .test_consentimientos import CLAVE, Base, nacimiento_hace

T = SolicitudDerecho.Tipo
E = SolicitudDerecho.Estado
R = SolicitudDerecho.Resolucion
F = SolicitudDerecho.Fundamento


def codigo_enviado():
    return re.search(r'es (\d{6})\.', mail.outbox[-1].body).group(1)


class Flujo(Base):
    def crear(self, tipo=T.ACCESO, paciente=None, **kw):
        paciente = paciente or self.ana
        return servicio.crear(paciente, paciente, tipo, paciente.usuario, **kw)

    def verificada(self, tipo=T.ACCESO, **kw):
        s = self.crear(tipo, **kw)
        servicio.verificar(s, self.u_ana, True, codigo_enviado() if s.nivel_requerido >= 2 else '')
        s.refresh_from_db()
        return s


class RecepcionYVerificacionTests(Flujo):
    def test_crear_deja_la_solicitud_en_verificacion_con_plazo_y_trazabilidad(self):
        s = self.crear()
        self.assertEqual(s.estado, E.EN_VERIFICACION)
        self.assertEqual(s.plazo_hasta, (s.recibida_en + timedelta(days=30)).date())
        self.assertEqual(list(s.historial.values_list('estado_nuevo', flat=True)), ['RECIBIDA', 'EN_VERIFICACION'])
        self.assertTrue(EventoAuditoria.objects.filter(operacion=Operacion.DERECHO_SOLICITUD, recurso_ref=self.ana.codigo).exists())

    def test_verificacion_proporcional_al_riesgo(self):
        self.assertEqual(self.crear(T.ACCESO).nivel_requerido, 2)
        self.assertEqual(self.crear(T.SUPRESION).nivel_requerido, 2)
        self.assertEqual(self.crear(T.RECTIFICACION, campo='telefono', valor='+56 9 5555 0000').nivel_requerido, 1)
        self.assertEqual(self.crear(T.RECTIFICACION, paciente=self.beto, campo='apellidos', valor='Nuevo').nivel_requerido, 2)

    def test_una_sola_solicitud_abierta_por_tipo(self):
        self.crear()
        with self.assertRaises(servicio.DerechosError):
            self.crear()

    def test_rectificar_exige_dato_y_valor(self):
        with self.assertRaises(servicio.DerechosError):
            self.crear(T.RECTIFICACION)
        with self.assertRaises(servicio.DerechosError):
            self.crear(T.RECTIFICACION, campo='email', valor='  ')
        with self.assertRaises(servicio.DerechosError):
            self.crear(T.RECTIFICACION, campo='rut', valor='1-9')

    def test_el_codigo_llega_por_correo_y_no_se_guarda_ni_se_audita_en_claro(self):
        s = self.crear()
        codigo = codigo_enviado()
        self.assertEqual(mail.outbox[-1].to, [self.ana.email])
        self.assertNotIn(codigo, s.codigo_huella)
        volcado = str(list(EventoAuditoria.objects.values_list('detalle', flat=True)))
        self.assertNotIn(codigo, volcado)

    def test_clave_incorrecta_no_verifica_y_queda_registrado(self):
        s = self.crear()
        with self.assertRaises(servicio.DerechosError):
            servicio.verificar(s, self.u_ana, False, codigo_enviado())
        s.refresh_from_db()
        self.assertEqual((s.estado, s.verificada_en), (E.EN_VERIFICACION, None))
        self.assertTrue(EventoAuditoria.objects.filter(operacion=Operacion.DERECHO_VERIFICACION, resultado='DENEGADO').exists())

    def test_codigo_incorrecto_y_limite_de_intentos(self):
        s = self.crear()
        buena = codigo_enviado()
        mala = '000000' if buena != '000000' else '111111'
        for _ in range(servicio.INTENTOS_CODIGO):
            with self.assertRaises(servicio.DerechosError):
                servicio.verificar(s, self.u_ana, True, mala)
        with self.assertRaises(servicio.DerechosError):  # ni siquiera el código bueno sirve tras agotar intentos
            servicio.verificar(s, self.u_ana, True, buena)
        servicio.enviar_codigo(s, self.u_ana)
        servicio.verificar(s, self.u_ana, True, codigo_enviado())
        s.refresh_from_db()
        self.assertEqual(s.estado, E.EN_EVALUACION)

    def test_codigo_vencido_y_de_un_solo_uso(self):
        s = self.crear()
        codigo = codigo_enviado()
        SolicitudDerecho.objects.filter(pk=s.pk).update(codigo_expira=timezone.now() - timedelta(minutes=1))
        s.refresh_from_db()
        with self.assertRaises(servicio.DerechosError):
            servicio.verificar(s, self.u_ana, True, codigo)
        servicio.enviar_codigo(s, self.u_ana)
        servicio.verificar(s, self.u_ana, True, codigo_enviado())
        self.assertEqual(s.codigo_huella, '')

    def test_limite_de_envios_de_codigo(self):
        s = self.crear()
        for _ in range(servicio.ENVIOS_CODIGO - 1):
            servicio.enviar_codigo(s, self.u_ana)
        with self.assertRaises(servicio.DerechosError):
            servicio.enviar_codigo(s, self.u_ana)

    def test_verificacion_basica_solo_con_clave(self):
        s = self.crear(T.RECTIFICACION, campo='telefono', valor='+56 9 5555 0000')
        servicio.verificar(s, self.u_ana, True)
        s.refresh_from_db()
        self.assertEqual(s.estado, E.EN_EVALUACION)
        self.assertEqual(len(mail.outbox), 0)


class ControlDeEstadosTests(Flujo):
    def test_no_se_puede_resolver_sin_verificar_identidad(self):
        s = self.crear()
        with self.assertRaises(servicio.DerechosError):
            servicio.resolver(s, self.encargado, R.EJECUTADA)
        # lo único posible es rechazar por identidad no verificada
        servicio.resolver(s, self.encargado, R.RECHAZADA, F.IDENTIDAD_NO_VERIFICADA, 'No pudimos verificarte.')
        self.assertEqual(s.estado, E.RESUELTA)

    def test_un_rechazo_exige_fundamento(self):
        s = self.verificada()
        with self.assertRaises(servicio.DerechosError):
            servicio.resolver(s, self.encargado, R.RECHAZADA)

    def test_no_se_resuelve_dos_veces_ni_se_cierra_antes_de_tiempo(self):
        s = self.verificada()
        with self.assertRaises(servicio.DerechosError):
            servicio.cerrar(s, self.encargado)
        servicio.resolver(s, self.encargado, R.EJECUTADA)
        with self.assertRaises(servicio.DerechosError):
            servicio.resolver(s, self.encargado, R.EJECUTADA)
        servicio.cerrar(s, self.encargado)
        self.assertEqual(s.estado, E.CERRADA)
        self.assertIsNone(s.descarga_hasta)
        with self.assertRaises(servicio.DerechosError):
            servicio.verificar(s, self.u_ana, True)

    def test_el_historial_es_inalterable(self):
        h = self.crear().historial.first()
        with self.assertRaises(PermissionError):
            h.save()
        with self.assertRaises(PermissionError):
            h.delete()

    def test_cerrada_se_puede_pedir_de_nuevo(self):
        s = self.verificada()
        servicio.resolver(s, self.encargado, R.EJECUTADA)
        servicio.cerrar(s, self.encargado)
        self.crear()  # no choca con la restricción de una abierta por tipo


class AccesoYPortabilidadTests(Flujo):
    def descargar(self, s, usuario=None):
        self.client.force_login(usuario or self.u_ana)
        return self.client.post(reverse('derechos:descargar', args=[s.codigo]))

    def test_descarga_entrega_los_datos_propios_y_cuenta_cada_vez(self):
        Diagnostico.objects.create(paciente=self.ana, medico=self.medico, diagnostico='Gastritis')
        Diagnostico.objects.create(paciente=self.beto, medico=self.medico, diagnostico='Asma de otra persona')
        s = self.verificada(T.ACCESO)
        servicio.resolver(s, self.encargado, R.EJECUTADA)
        r = self.descargar(s)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Cache-Control'], 'no-store')
        datos = json.loads(r.content)
        self.assertEqual(datos['paciente'], self.ana.codigo)
        self.assertEqual(datos['diagnosticos'][0]['diagnostico'], 'Gastritis')
        self.assertNotIn('Asma de otra persona', r.content.decode())
        self.assertIn('informacion_sobre_el_tratamiento', datos)
        s.refresh_from_db()
        self.assertEqual(s.descargas, 1)
        evento = EventoAuditoria.objects.filter(operacion=Operacion.EXPORTACION_DATOS).get()
        self.assertEqual(evento.detalle['cantidad'], 1)
        self.assertNotIn('Gastritis', str(evento.detalle))

    def test_portabilidad_no_incluye_la_seccion_informativa(self):
        s = self.verificada(T.PORTABILIDAD)
        servicio.resolver(s, self.encargado, R.EJECUTADA)
        self.assertNotIn('informacion_sobre_el_tratamiento', json.loads(self.descargar(s).content))

    def test_limite_de_descargas_y_vencimiento(self):
        s = self.verificada()
        servicio.resolver(s, self.encargado, R.EJECUTADA)
        for _ in range(3):
            self.assertEqual(self.descargar(s).status_code, 200)
        self.assertEqual(self.descargar(s).status_code, 302)  # cuarta: rechazada
        s2 = self.verificada(T.PORTABILIDAD)
        servicio.resolver(s2, self.encargado, R.EJECUTADA)
        SolicitudDerecho.objects.filter(pk=s2.pk).update(descarga_hasta=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.descargar(s2).status_code, 302)

    def test_no_hay_descarga_si_fue_rechazada_o_no_esta_resuelta(self):
        s = self.verificada()
        self.assertEqual(self.descargar(s).status_code, 302)
        servicio.resolver(s, self.encargado, R.RECHAZADA, F.SOLICITUD_INFUNDADA)
        self.assertEqual(self.descargar(s).status_code, 302)
        self.assertFalse(EventoAuditoria.objects.filter(operacion=Operacion.EXPORTACION_DATOS).exists())

    def test_otro_paciente_no_puede_ver_ni_descargar_una_solicitud_ajena(self):
        s = self.verificada()
        servicio.resolver(s, self.encargado, R.EJECUTADA)
        self.assertEqual(self.descargar(s, self.u_beto).status_code, 404)
        self.client.force_login(self.u_beto)
        self.assertEqual(self.client.get(reverse('derechos:detalle', args=[s.codigo])).status_code, 404)
        self.assertEqual(self.client.post(reverse('derechos:verificar', args=[s.codigo])).status_code, 404)


class RectificacionTests(Flujo):
    def test_se_aplica_al_acoger_y_el_login_sigue_al_correo(self):
        s = self.verificada(T.RECTIFICACION, campo='email', valor='nuevo@correo.cl')
        servicio.resolver(s, self.encargado, R.EJECUTADA)
        self.ana.refresh_from_db()
        self.assertEqual(self.ana.email, 'nuevo@correo.cl')
        self.u_ana.refresh_from_db()
        self.assertEqual(self.u_ana.correo_indice, indice_correo('nuevo@correo.cl'))
        self.assertTrue(EventoAuditoria.objects.filter(operacion=Operacion.RECTIFICACION).exists())

    def test_no_se_aplica_si_se_rechaza(self):
        s = self.verificada(T.RECTIFICACION, campo='telefono', valor='+56 9 0000 0000')
        servicio.resolver(s, self.encargado, R.RECHAZADA, F.SOLICITUD_INFUNDADA)
        self.ana.refresh_from_db()
        self.assertEqual(self.ana.telefono, '+56 9 1234 4821')

    def test_un_correo_ya_usado_por_otra_cuenta_se_rechaza_sin_cambios(self):
        self.u_beto.correo_indice = indice_correo(self.beto.email)
        self.u_beto.save()
        s = self.verificada(T.RECTIFICACION, campo='email', valor=self.beto.email)
        with self.assertRaises(servicio.DerechosError):
            servicio.resolver(s, self.encargado, R.EJECUTADA)
        s.refresh_from_db()
        self.assertEqual(s.estado, E.EN_EVALUACION)

    def test_un_dato_clinico_no_se_modifica_se_responde_con_fundamento(self):
        s = self.verificada(T.RECTIFICACION, campo='clinico', valor='Mi alergia está mal anotada')
        with self.assertRaises(servicio.DerechosError):
            servicio.resolver(s, self.encargado, R.EJECUTADA)
        servicio.resolver(s, self.encargado, R.PARCIAL, F.DATO_CLINICO, 'Agregaremos una anotación aclaratoria.')
        self.assertEqual(s.estado, E.RESUELTA)


class SupresionTests(Flujo):
    def test_con_ficha_clinica_es_parcial_bloquea_y_conserva_lo_obligatorio(self):
        consentimientos.otorgar(self.ana, consentimientos.RECORDATORIOS_CORREO, self.u_ana)
        Notificacion.objects.create(paciente=self.ana, titulo='Aviso')
        Diagnostico.objects.create(paciente=self.ana, medico=self.medico, diagnostico='Gastritis')
        s = self.verificada(T.SUPRESION)
        servicio.resolver(s, self.encargado, R.EJECUTADA)
        self.assertEqual((s.resolucion, s.fundamento), (R.PARCIAL, F.CONSERVACION_LEGAL))
        self.assertIn('conservarse por ley', s.respuesta)
        self.ana.refresh_from_db()
        self.assertIsNotNone(self.ana.datos_bloqueados_desde)
        self.assertEqual(Diagnostico.objects.filter(paciente=self.ana).count(), 1)  # la ficha no se borra
        self.assertEqual(Notificacion.objects.filter(paciente=self.ana).count(), 0)
        self.assertEqual(Consentimiento.objects.get(paciente=self.ana).estado, 'REVOCADO')
        self.u_ana.refresh_from_db()
        self.assertFalse(self.u_ana.is_active)
        self.assertFalse(self.client.login(username='ana', password=CLAVE))
        self.assertTrue(EventoAuditoria.objects.filter(operacion=Operacion.SUPRESION).exists())

    def test_sin_datos_clinicos_se_elimina_tambien_la_identidad(self):
        s = self.verificada(T.SUPRESION)
        servicio.resolver(s, self.encargado, R.EJECUTADA)
        self.assertEqual(s.resolucion, R.EJECUTADA)
        self.ana.refresh_from_db()
        self.assertFalse(hasattr(self.ana, 'identidad') and self.ana._identidad())

    def test_un_bloqueado_no_puede_dar_consentimientos_ni_nuevas_solicitudes(self):
        s = self.verificada(T.SUPRESION)
        servicio.resolver(s, self.encargado, R.EJECUTADA)
        self.ana.refresh_from_db()
        with self.assertRaises(consentimientos.ConsentimientoError):
            consentimientos.otorgar(self.ana, consentimientos.RECORDATORIOS_CORREO, self.u_ana)
        with self.assertRaises(servicio.DerechosError):
            servicio.crear(self.ana, self.ana, T.ACCESO, self.u_ana)

    def test_si_falla_la_ejecucion_no_queda_nada_a_medias(self):
        Diagnostico.objects.create(paciente=self.ana, medico=self.medico, diagnostico='x')
        s = self.verificada(T.SUPRESION)
        consentimientos.otorgar(self.ana, consentimientos.RECORDATORIOS_SMS, self.u_ana)
        from unittest import mock
        with mock.patch('apps.derechos.servicio.conservar_hasta', side_effect=RuntimeError('falla')):
            with self.assertRaises(RuntimeError):
                servicio.resolver(s, self.encargado, R.EJECUTADA)
        self.assertEqual(Consentimiento.objects.get(paciente=self.ana).estado, 'OTORGADO')
        self.u_ana.refresh_from_db()
        self.assertTrue(self.u_ana.is_active)


class MenoresYAccesoTests(Flujo):
    def test_un_menor_no_solicita_por_si_mismo_ni_un_tercero_por_el(self):
        with self.assertRaises(servicio.DerechosError):
            servicio.crear(self.nino, self.nino, T.ACCESO, self.u_nino)
        with self.assertRaises(servicio.DerechosError):
            servicio.crear(self.beto, self.nino, T.ACCESO, self.u_beto)

    def test_el_representante_verificado_solicita_y_se_verifica_con_sus_credenciales(self):
        Representacion.objects.create(menor=self.nino, representante=self.ana, parentesco='MADRE', estado='VERIFICADA',
                                      vigente_hasta=timezone.localdate() + timedelta(days=300))
        s = servicio.crear(self.ana, self.nino, T.ACCESO, self.u_ana)
        self.assertEqual(mail.outbox[-1].to, [self.ana.email])  # el código va al representante
        servicio.verificar(s, self.u_ana, True, codigo_enviado())
        self.assertEqual(s.paciente, self.nino)

    def test_representacion_vencida_no_sirve(self):
        Representacion.objects.create(menor=self.nino, representante=self.ana, parentesco='MADRE', estado='VERIFICADA',
                                      vigente_hasta=timezone.localdate() - timedelta(days=1))
        with self.assertRaises(servicio.DerechosError):
            servicio.crear(self.ana, self.nino, T.ACCESO, self.u_ana)

    def test_solo_el_encargado_gestiona_las_solicitudes(self):
        s = self.verificada()
        urls = [reverse('derechos:bandeja'), reverse('derechos:gestionar', args=[s.codigo])]
        for u in (self.u_ana, self.u_beto, self.recepcion, self.medico, self.sysadmin):
            self.client.force_login(u)
            for url in urls:
                self.assertEqual(self.client.get(url).status_code, 403, (u.username, url))
            for nombre in ('resolver', 'cerrar'):
                r = self.client.post(reverse(f'derechos:{nombre}', args=[s.codigo]), {'resolucion': 'EJECUTADA'})
                self.assertEqual(r.status_code, 403, (u.username, nombre))
        s.refresh_from_db()
        self.assertEqual(s.estado, E.EN_EVALUACION)
        self.client.force_login(self.encargado)
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 200)

    def test_el_encargado_ve_codigos_y_no_identidad_ni_valores_propuestos(self):
        s = self.verificada(T.RECTIFICACION, campo='email', valor='secreto@correo.cl')
        self.client.force_login(self.encargado)
        for url in (reverse('derechos:bandeja'), reverse('derechos:gestionar', args=[s.codigo])):
            r = self.client.get(url)
            self.assertContains(r, self.ana.codigo)
            for dato in (self.ana.nombres, self.ana.email, self.ana.rut, 'secreto@correo.cl'):
                self.assertNotContains(r, dato)

    def test_el_flujo_completo_desde_el_portal_y_la_bandeja(self):
        self.client.force_login(self.u_ana)
        r = self.client.post(reverse('derechos:nueva'), {'tipo': T.ACCESO})
        s = SolicitudDerecho.objects.get()
        self.assertRedirects(r, reverse('derechos:detalle', args=[s.codigo]))
        self.client.post(reverse('derechos:verificar', args=[s.codigo]), {'clave': 'mala', 'codigo': codigo_enviado()})
        s.refresh_from_db()
        self.assertEqual(s.estado, E.EN_VERIFICACION)
        self.client.post(reverse('derechos:verificar', args=[s.codigo]), {'clave': CLAVE, 'codigo': codigo_enviado()})
        s.refresh_from_db()
        self.assertEqual(s.estado, E.EN_EVALUACION)
        self.client.force_login(self.encargado)
        self.client.post(reverse('derechos:resolver', args=[s.codigo]), {'resolucion': 'EJECUTADA', 'respuesta': 'Lista tu copia.'})
        self.client.force_login(self.u_ana)
        self.assertContains(self.client.get(reverse('derechos:detalle', args=[s.codigo])), 'Descargar mis datos')
        self.assertEqual(self.client.post(reverse('derechos:descargar', args=[s.codigo])).status_code, 200)
        self.client.force_login(self.encargado)
        self.client.post(reverse('derechos:cerrar', args=[s.codigo]))
        s.refresh_from_db()
        self.assertEqual(s.estado, E.CERRADA)
        self.assertEqual(
            list(HistorialSolicitud.objects.filter(solicitud=s).values_list('estado_nuevo', flat=True)),
            ['RECIBIDA', 'EN_VERIFICACION', 'EN_EVALUACION', 'RESUELTA', 'CERRADA'],
        )

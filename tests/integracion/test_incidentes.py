"""Plan de respuesta a incidentes: fases, plazos de notificación, autorización y condiciones de cierre."""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.auditoria import incidentes as plan
from apps.auditoria.models import AlertaSeguridad, EstadoAlerta, EventoAuditoria, IncidenteSeguridad, Operacion
from apps.usuarios.models import Usuario

CLAVE = 'Clave-Muy-Segura-123'
HUELLA = 'a' * 64
LECCIONES = 'Causa: contraseña reutilizada. Falló la detección tardía. Mejora: bloqueo por país (responsable: sistemas).'


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.encargado = Usuario.objects.create_user('priv', email='p@c.cl', password=CLAVE, rol=Usuario.Rol.PRIVACIDAD)
        cls.sysadmin = Usuario.objects.create_user('sys', email='s@c.cl', password=CLAVE, rol=Usuario.Rol.ADMIN_SISTEMA)
        cls.medico = Usuario.objects.create_user('med', email='m@c.cl', password=CLAVE, rol=Usuario.Rol.MEDICO)
        cls.recepcion = Usuario.objects.create_user('rec', email='r@c.cl', password=CLAVE, rol=Usuario.Rol.ADMINISTRATIVO)
        cls.paciente = Usuario.objects.create_user('pac', email='pa@c.cl', password=CLAVE, rol=Usuario.Rol.PACIENTE)

    def abrir(self, **criterios):
        i = plan.abrir('Posible acceso masivo a fichas por una cuenta médica', 'ALTA', self.encargado)
        if criterios:
            plan.clasificar(i, 'CONFIRMADO', self.encargado, **criterios)
        return i

    def completo(self, **criterios):
        """Un caso confirmado que ya recorrió todas las fases."""
        i = self.abrir()
        plan.clasificar(i, 'CONFIRMADO', self.encargado, **criterios)
        plan.avanzar(i, self.encargado, HUELLA)
        plan.avanzar(i, self.encargado)
        plan.avanzar(i, self.encargado)
        return i


class FasesTests(Base):
    def test_abrir_lleva_la_alerta_a_revision_y_audita(self):
        alerta = AlertaSeguridad.objects.create(regla='x', severidad='ALTA', resumen='r', clave='k1')
        i = plan.abrir('Acceso inusual a fichas de varios pacientes', 'ALTA', self.encargado, [alerta])
        alerta.refresh_from_db()
        self.assertEqual(alerta.estado, EstadoAlerta.EN_REVISION)
        self.assertEqual((i.clasificacion, i.fase), ('SOSPECHOSO', 'ANALISIS'))
        self.assertTrue(i.codigo.startswith('IN-'))
        self.assertTrue(EventoAuditoria.objects.filter(operacion=Operacion.INCIDENTE_CAMBIO, recurso_ref=i.codigo).exists())

    def test_no_se_contiene_sin_clasificar_ni_sin_evidencia(self):
        i = self.abrir()
        with self.assertRaises(plan.IncidenteError):
            plan.avanzar(i, self.encargado, HUELLA)
        plan.clasificar(i, 'CONFIRMADO', self.encargado, afecta_datos_personales=True)
        with self.assertRaises(plan.IncidenteError):  # sin evidencia preservada
            plan.avanzar(i, self.encargado)
        plan.avanzar(i, self.encargado, HUELLA)
        self.assertEqual(i.fase, 'CONTENCION')
        self.assertIsNotNone(i.contenido_en)

    def test_las_fases_van_en_orden_y_terminan_en_recuperacion(self):
        i = self.completo()
        self.assertEqual(i.fase, 'RECUPERACION')
        self.assertTrue(i.contenido_en and i.erradicado_en and i.recuperado_en)
        with self.assertRaises(plan.IncidenteError):
            plan.avanzar(i, self.encargado)

    def test_la_evidencia_de_la_alerta_sirve_para_contener(self):
        alerta = AlertaSeguridad.objects.create(regla='x', severidad='ALTA', resumen='r', clave='k2', evidencia_sha256=HUELLA)
        i = plan.abrir('Acceso inusual a fichas de varios pacientes', 'ALTA', self.encargado, [alerta])
        plan.clasificar(i, 'CONFIRMADO', self.encargado)
        plan.avanzar(i, self.encargado)
        self.assertEqual(i.evidencia_sha256, HUELLA)

    def test_un_falso_positivo_no_recorre_fases_y_exige_explicacion_para_cerrar(self):
        i = self.abrir()
        plan.clasificar(i, 'FALSO_POSITIVO', self.encargado)
        with self.assertRaises(plan.IncidenteError):
            plan.avanzar(i, self.encargado, HUELLA)
        with self.assertRaises(plan.IncidenteError):
            plan.cerrar(i, self.encargado)
        plan.registrar_lecciones(i, self.encargado, 'Era una prueba del equipo de sistemas; ajustar el umbral de la regla.')
        plan.cerrar(i, self.encargado)
        self.assertEqual(i.fase, 'CERRADO')


class PlazosTests(Base):
    def test_sin_efectos_significativos_no_hay_plazos(self):
        self.assertEqual(self.abrir().plazos, {})

    def test_efectos_significativos_activan_los_plazos_del_csirt(self):
        i = self.abrir(afecta_continuidad=True)
        self.assertEqual(set(i.plazos), {'csirt_alerta', 'csirt_actualizacion'})
        self.assertEqual(i.plazos['csirt_alerta'][1], i.conocido_en + timedelta(hours=3))
        self.assertEqual(i.plazos['csirt_actualizacion'][1], i.conocido_en + timedelta(hours=72))

    def test_datos_personales_con_riesgo_suman_agencia_y_titulares_si_son_sensibles(self):
        i = self.abrir(afecta_datos_personales=True, riesgo_razonable=True)
        self.assertIn('agencia', i.plazos)
        self.assertNotIn('titulares', i.plazos)  # sin datos sensibles ni de menores
        plan.clasificar(i, 'CONFIRMADO', self.encargado, hay_datos_sensibles=True)
        self.assertIn('titulares', i.plazos)

    def test_el_informe_final_corre_15_dias_desde_la_alerta_temprana(self):
        i = self.abrir(afecta_datos_personales=True)
        self.assertNotIn('csirt_informe', i.plazos)
        enviada = timezone.now() - timedelta(hours=2)
        i.csirt_alerta_en = enviada
        self.assertEqual(i.plazos['csirt_informe'][1], enviada + timedelta(days=15))

    def test_los_plazos_vencidos_se_detectan(self):
        i = self.abrir(afecta_datos_personales=True)
        IncidenteSeguridad.objects.filter(pk=i.pk).update(conocido_en=timezone.now() - timedelta(hours=5))
        i.refresh_from_db()
        self.assertEqual([c for c, *_ in plan.vencidos(i)], ['csirt_alerta'])


class NotificacionTests(Base):
    def test_exige_propuesta_y_autorizacion_de_otra_persona(self):
        i = self.abrir(afecta_datos_personales=True)
        with self.assertRaises(plan.IncidenteError):
            plan.registrar_notificacion(i, self.encargado, 'csirt_alerta')
        with self.assertRaises(plan.IncidenteError):
            plan.autorizar_notificacion(i, self.sysadmin)  # nadie propuso
        plan.proponer_notificacion(i, self.encargado)
        with self.assertRaises(plan.IncidenteError):
            plan.autorizar_notificacion(i, self.encargado)  # quien propone no autoriza
        plan.autorizar_notificacion(i, self.sysadmin)
        plan.registrar_notificacion(i, self.encargado, 'csirt_alerta')
        self.assertIsNotNone(i.csirt_alerta_en)
        with self.assertRaises(plan.IncidenteError):
            plan.registrar_notificacion(i, self.encargado, 'csirt_alerta')  # ya registrada

    def test_no_se_registra_una_notificacion_que_no_corresponde(self):
        i = self.abrir(afecta_continuidad=True)
        plan.proponer_notificacion(i, self.encargado)
        plan.autorizar_notificacion(i, self.sysadmin)
        with self.assertRaises(plan.IncidenteError):
            plan.registrar_notificacion(i, self.encargado, 'titulares')

    def test_proponer_de_nuevo_invalida_la_autorizacion_previa(self):
        i = self.abrir(afecta_datos_personales=True)
        plan.proponer_notificacion(i, self.encargado)
        plan.autorizar_notificacion(i, self.sysadmin)
        plan.proponer_notificacion(i, self.encargado)
        self.assertIsNone(i.notificacion_autorizada_por)


class CierreTests(Base):
    def test_no_cierra_con_pendientes(self):
        i = self.completo(afecta_datos_personales=True, riesgo_razonable=True, hay_datos_sensibles=True)
        faltan = plan.pendientes_de_cierre(i)
        self.assertTrue(any('CSIRT' in f or 'Alerta temprana' in f for f in faltan))
        self.assertTrue(any('lecciones' in f for f in faltan))
        with self.assertRaises(plan.IncidenteError):
            plan.cerrar(i, self.encargado)

    def test_cierra_cuando_todo_se_cumplio_y_cierra_las_alertas(self):
        alerta = AlertaSeguridad.objects.create(regla='x', severidad='ALTA', resumen='r', clave='k3')
        i = plan.abrir('Acceso inusual a fichas de varios pacientes', 'ALTA', self.encargado, [alerta])
        plan.clasificar(i, 'CONFIRMADO', self.encargado, afecta_datos_personales=True, riesgo_razonable=True,
                        hay_datos_sensibles=True, titulares_aprox=12)
        plan.avanzar(i, self.encargado, HUELLA)
        plan.avanzar(i, self.encargado)
        plan.avanzar(i, self.encargado)
        plan.proponer_notificacion(i, self.encargado)
        plan.autorizar_notificacion(i, self.sysadmin)
        for cual in ('csirt_alerta', 'csirt_actualizacion', 'csirt_informe', 'agencia', 'titulares'):
            plan.registrar_notificacion(i, self.encargado, cual)
        plan.registrar_lecciones(i, self.encargado, LECCIONES)
        self.assertEqual(plan.pendientes_de_cierre(i), [])
        plan.cerrar(i, self.encargado)
        alerta.refresh_from_db()
        self.assertEqual((i.fase, alerta.estado), ('CERRADO', 'CERRADA'))
        self.assertIsNotNone(i.cerrado_en)

    def test_se_puede_cerrar_sin_notificar_si_se_justifica(self):
        i = self.completo(afecta_datos_personales=True, riesgo_razonable=True)
        plan.registrar_lecciones(i, self.encargado, LECCIONES)
        with self.assertRaises(plan.IncidenteError):
            plan.justificar_sin_notificar(i, self.encargado, 'no')
        plan.justificar_sin_notificar(i, self.encargado, 'Los datos estaban cifrados y la llave no se expuso; sin riesgo real.')
        plan.cerrar(i, self.encargado)
        self.assertEqual(i.fase, 'CERRADO')

    def test_un_caso_cerrado_no_se_reclasifica(self):
        i = self.completo()
        plan.registrar_lecciones(i, self.encargado, LECCIONES)
        plan.cerrar(i, self.encargado)
        with self.assertRaises(plan.IncidenteError):
            plan.clasificar(i, 'SOSPECHOSO', self.encargado)


class AccesoTests(Base):
    def test_solo_seguridad_ve_los_casos(self):
        i = self.abrir()
        url = reverse('auditoria:incidente', args=[i.codigo])
        for u in (self.paciente, self.medico, self.recepcion):
            self.client.force_login(u)
            self.assertEqual(self.client.get(url).status_code, 403, u.username)
            self.assertEqual(self.client.get(reverse('auditoria:incidentes')).status_code, 403, u.username)
            self.assertEqual(self.client.post(reverse('auditoria:incidente_cerrar', args=[i.codigo])).status_code, 403)
        for u in (self.encargado, self.sysadmin):
            self.client.force_login(u)
            self.assertEqual(self.client.get(url).status_code, 200, u.username)

    def test_el_flujo_por_pantalla_con_dos_personas(self):
        self.client.force_login(self.encargado)
        self.client.post(reverse('auditoria:incidente_abrir'), {'resumen': 'Cuenta médica con consultas masivas', 'severidad': 'ALTA'})
        i = IncidenteSeguridad.objects.get()
        self.client.post(reverse('auditoria:incidente_clasificar', args=[i.codigo]), {
            'clasificacion': 'CONFIRMADO', 'afecta_datos_personales': 'on', 'riesgo_razonable': 'on', 'hay_datos_sensibles': 'on',
            'titulares_aprox': '30', 'categorias_datos': 'clínicos'})
        i.refresh_from_db()
        self.assertEqual((i.clasificacion, i.titulares_aprox, i.hay_datos_sensibles), ('CONFIRMADO', 30, True))
        self.client.post(reverse('auditoria:incidente_proponer', args=[i.codigo]))
        self.client.post(reverse('auditoria:incidente_autorizar', args=[i.codigo]))  # el mismo: rechazado
        i.refresh_from_db()
        self.assertIsNone(i.notificacion_autorizada_por)
        self.client.force_login(self.sysadmin)
        self.client.post(reverse('auditoria:incidente_autorizar', args=[i.codigo]))
        i.refresh_from_db()
        self.assertEqual(i.notificacion_autorizada_por, self.sysadmin.pk)
        self.assertContains(self.client.get(reverse('auditoria:incidente', args=[i.codigo])), 'Alerta temprana al CSIRT Nacional')

    def test_nadie_mas_autoriza(self):
        i = self.abrir(afecta_datos_personales=True)
        plan.proponer_notificacion(i, self.encargado)
        for u in (self.medico, self.recepcion, self.paciente):
            self.client.force_login(u)
            self.assertEqual(self.client.post(reverse('auditoria:incidente_autorizar', args=[i.codigo])).status_code, 403)
        i.refresh_from_db()
        self.assertIsNone(i.notificacion_autorizada_por)

    def test_el_registro_del_caso_no_lleva_datos_personales(self):
        i = self.abrir(afecta_datos_personales=True)
        detalle = str(list(EventoAuditoria.objects.filter(recurso_ref=i.codigo).values_list('detalle', flat=True)))
        self.assertIn(i.codigo, detalle)
        self.assertNotIn('@', detalle)

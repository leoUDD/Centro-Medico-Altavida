"""Gestión del consentimiento: estado, historial, revocación efectiva, menores y control de acceso."""
from datetime import timedelta
from unittest import mock

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.agenda.models import Cita
from apps.auditoria.models import EventoAuditoria, Operacion
from apps.consentimientos import servicio
from apps.consentimientos.models import (
    Consentimiento, Finalidad, RegistroConsentimiento, Representacion, TextoConsentimiento,
)
from apps.notificaciones import recordatorios
from apps.notificaciones.models import PreferenciasNotificacion, Recordatorio
from apps.pacientes.models import Paciente
from apps.profesionales.models import Especialidad, Profesional
from apps.seguridad.indice import indice_rut
from apps.seguridad.rut import _digito_verificador
from apps.sucursales.models import Sucursal
from apps.usuarios.models import Usuario

CLAVE = 'Clave-Muy-Segura-123'
CORREO, SMS = servicio.RECORDATORIOS_CORREO, servicio.RECORDATORIOS_SMS


def rut(cuerpo):
    return f'{cuerpo}{_digito_verificador(str(cuerpo))}'


def crear(nombre, cuerpo, nacimiento='1985-03-12', rol=None):
    usuario = Usuario.objects.create_user(nombre, email=f'{nombre}@c.cl', password=CLAVE, rol=rol or Usuario.Rol.PACIENTE)
    paciente = Paciente.objects.create(
        usuario=usuario, rut=rut(cuerpo), nombres=nombre.title(), apellidos='Prueba', fecha_nacimiento=nacimiento,
        email=f'{nombre}@correo.cl', telefono='+56 9 1234 4821',
    )
    return usuario, paciente


def nacimiento_hace(anios):
    hoy = timezone.localdate()
    return hoy.replace(year=hoy.year - anios, day=1).isoformat()


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.u_ana, cls.ana = crear('ana', 11111111)
        cls.u_beto, cls.beto = crear('beto', 22222222)
        cls.u_nino, cls.nino = crear('nino', 33333333, nacimiento=nacimiento_hace(9))
        cls.recepcion = Usuario.objects.create_user('recep', email='r@c.cl', password=CLAVE, rol=Usuario.Rol.ADMINISTRATIVO)
        cls.encargado = Usuario.objects.create_user('priv', email='p@c.cl', password=CLAVE, rol=Usuario.Rol.PRIVACIDAD)
        cls.medico = Usuario.objects.create_user('med', email='m@c.cl', password=CLAVE, rol=Usuario.Rol.MEDICO)
        cls.sysadmin = Usuario.objects.create_user('sys', email='s@c.cl', password=CLAVE, rol=Usuario.Rol.ADMIN_SISTEMA)


class EstadoEHistorialTests(Base):
    def test_finalidades_iniciales_con_texto_versionado(self):
        self.assertEqual(set(Finalidad.objects.values_list('codigo', flat=True)), {CORREO, SMS})
        for f in Finalidad.objects.all():
            texto = f.textos.get()
            self.assertEqual(texto.version, 1)
            self.assertEqual(len(texto.huella), 64)

    def test_otorgar_registra_estado_fecha_version_y_historial(self):
        c = servicio.otorgar(self.ana, CORREO, self.u_ana)
        self.assertEqual((c.estado, c.texto.version, c.otorgante), ('OTORGADO', 1, 'TITULAR'))
        self.assertIsNotNone(c.otorgado_en)
        self.assertTrue(servicio.vigente(self.ana, CORREO))
        r = RegistroConsentimiento.objects.get()
        self.assertEqual((r.accion, r.canal, r.registrado_por), ('OTORGADO', 'PORTAL', self.u_ana.pk))

    def test_revocar_deja_fecha_y_ambos_movimientos_en_el_historial(self):
        servicio.otorgar(self.ana, CORREO, self.u_ana)
        c = servicio.revocar(self.ana, CORREO, self.u_ana)
        self.assertEqual(c.estado, 'REVOCADO')
        self.assertIsNotNone(c.revocado_en)
        self.assertFalse(servicio.vigente(self.ana, CORREO))
        self.assertEqual(list(RegistroConsentimiento.objects.values_list('accion', flat=True)), ['OTORGADO', 'REVOCADO'])

    def test_repetir_la_misma_accion_no_ensucia_el_historial(self):
        servicio.otorgar(self.ana, CORREO, self.u_ana)
        servicio.otorgar(self.ana, CORREO, self.u_ana)
        servicio.revocar(self.ana, SMS, self.u_ana)  # nunca otorgado: nada que revocar
        self.assertEqual(RegistroConsentimiento.objects.count(), 1)

    def test_otorgar_una_finalidad_no_habilita_otra(self):
        servicio.otorgar(self.ana, CORREO, self.u_ana)
        self.assertTrue(servicio.vigente(self.ana, CORREO))
        self.assertFalse(servicio.vigente(self.ana, SMS))
        self.assertFalse(servicio.vigente(self.beto, CORREO))

    def test_un_consentimiento_por_paciente_y_finalidad(self):
        servicio.otorgar(self.ana, CORREO, self.u_ana)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Consentimiento.objects.create(
                paciente=self.ana, finalidad=Finalidad.objects.get(codigo=CORREO),
                texto=TextoConsentimiento.objects.first(), estado='OTORGADO', otorgado_en=timezone.now(),
            )

    def test_historial_y_textos_son_inalterables(self):
        servicio.otorgar(self.ana, CORREO, self.u_ana)
        registro = RegistroConsentimiento.objects.get()
        with self.assertRaises(PermissionError):
            registro.save()
        with self.assertRaises(PermissionError):
            registro.delete()
        texto = TextoConsentimiento.objects.first()
        texto.texto = 'otro'
        with self.assertRaises(PermissionError):
            texto.save()
        with self.assertRaises(PermissionError):
            texto.delete()

    def test_texto_nuevo_con_cambio_de_alcance_exige_reconfirmar(self):
        servicio.otorgar(self.ana, CORREO, self.u_ana)
        finalidad = Finalidad.objects.get(codigo=CORREO)
        TextoConsentimiento.objects.create(finalidad=finalidad, version=2, texto='Texto ampliado', cambia_alcance=True)
        finalidad.version_minima_valida = 2
        finalidad.save()
        self.assertFalse(servicio.vigente(self.ana, CORREO))
        fila = next(f for f in servicio.estado_por_finalidad(self.ana) if f['finalidad'].codigo == CORREO)
        self.assertTrue(fila['requiere_reconfirmar'])
        servicio.otorgar(self.ana, CORREO, self.u_ana)
        self.assertTrue(servicio.vigente(self.ana, CORREO))
        self.assertEqual(Consentimiento.objects.get(paciente=self.ana).texto.version, 2)

    def test_el_cambio_queda_en_la_auditoria_sin_datos_personales(self):
        servicio.otorgar(self.ana, CORREO, self.u_ana)
        servicio.revocar(self.ana, CORREO, self.u_ana)
        eventos = list(EventoAuditoria.objects.filter(operacion=Operacion.CONSENTIMIENTO_CAMBIO).order_by('id'))
        self.assertEqual([e.detalle['estado_nuevo'] for e in eventos], ['OTORGADO', 'REVOCADO'])
        self.assertEqual(eventos[0].detalle['estado_anterior'], 'NINGUNO')
        self.assertEqual(eventos[1].recurso_ref, self.ana.codigo)
        volcado = str([e.detalle for e in eventos]) + ''.join(e.recurso_ref for e in eventos)
        for dato in (self.ana.email, self.ana.telefono, self.ana.rut, self.ana.nombres):
            self.assertNotIn(dato, volcado)

    def test_no_se_guardan_ip_ni_agente_en_el_historial(self):
        campos = {f.name for f in RegistroConsentimiento._meta.get_fields()}
        self.assertFalse(campos & {'ip', 'ip_hash', 'user_agent', 'email', 'telefono'})


class RevocacionEnProcesosTests(Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.sede = Sucursal.objects.create(nombre='Sede Central')
        medico = Usuario.objects.create_user('dra', email='d@c.cl', password=CLAVE, rol='MEDICO', first_name='C', last_name='R')
        cls.profesional = Profesional.objects.create(usuario=medico, titulo='Dra.', especialidad=Especialidad.objects.create(nombre='General'))

    def cita(self):
        inicio = timezone.now() + timedelta(hours=24)
        cita = Cita.objects.create(
            paciente=self.ana, tipo='CONSULTA', profesional=self.profesional, sucursal=self.sede, modalidad='PRESENCIAL',
            inicio=inicio, fin=inicio + timedelta(minutes=30), estado='AGENDADA',
        )
        Cita.objects.filter(pk=cita.pk).update(creada=timezone.now() - timedelta(hours=72))
        return cita

    def test_sin_consentimiento_no_se_generan_recordatorios(self):
        PreferenciasNotificacion.objects.create(paciente=self.ana, canal_correo=True, canal_sms=True)
        self.cita()
        self.assertEqual(recordatorios.generar(), 0)

    def test_solo_sale_el_canal_consentido(self):
        PreferenciasNotificacion.objects.create(paciente=self.ana, canal_correo=True, canal_sms=True)
        servicio.otorgar(self.ana, SMS, self.u_ana)
        self.cita()
        recordatorios.generar()
        self.assertEqual(set(Recordatorio.objects.values_list('canal', flat=True)), {'SMS'})

    def test_revocar_cancela_lo_pendiente_y_no_envia(self):
        PreferenciasNotificacion.objects.create(paciente=self.ana, canal_correo=True, canal_sms=False)
        servicio.otorgar(self.ana, CORREO, self.u_ana)
        self.cita()
        recordatorios.generar()
        self.assertEqual(Recordatorio.objects.filter(estado='PENDIENTE').count(), 1)
        servicio.revocar(self.ana, CORREO, self.u_ana)
        with mock.patch('apps.notificaciones.recordatorios.send_mail') as enviar:
            enviados, fallidos = recordatorios.enviar_pendientes()
        enviar.assert_not_called()
        self.assertEqual((enviados, fallidos), (0, 0))
        r = Recordatorio.objects.get()
        self.assertEqual((r.estado, r.error), ('CANCELADO', 'Sin consentimiento vigente'))

    def test_el_portal_no_deja_activar_un_canal_sin_consentimiento(self):
        self.client.force_login(self.u_ana)
        self.client.post(reverse('notificaciones:preferencias'), {'canal_correo': 'on', 'canal_sms': 'on'})
        p = PreferenciasNotificacion.objects.get(paciente=self.ana)
        self.assertEqual((p.canal_correo, p.canal_sms), (False, False))

    def test_preferencias_iniciales_siguen_a_los_consentimientos(self):
        servicio.otorgar(self.ana, CORREO, self.u_ana)
        p = PreferenciasNotificacion.para(self.ana)
        self.assertEqual((p.canal_correo, p.canal_sms), (True, False))


class MenoresTests(Base):
    def representacion(self, **kw):
        valores = dict(menor=self.nino, representante=self.ana, parentesco='MADRE', estado='VERIFICADA',
                       vigente_hasta=timezone.localdate() + timedelta(days=365))
        valores.update(kw)
        return Representacion.objects.create(**valores)

    def test_un_menor_no_puede_consentir_por_si_mismo(self):
        with self.assertRaises(servicio.ConsentimientoError):
            servicio.otorgar(self.nino, CORREO, self.u_nino)
        self.assertFalse(Consentimiento.objects.exists())

    def test_un_tercero_sin_representacion_no_puede_decidir(self):
        with self.assertRaises(servicio.ConsentimientoError):
            servicio.otorgar(self.nino, CORREO, self.u_beto, actor_paciente=self.beto)
        self.representacion(estado='PENDIENTE')
        with self.assertRaises(servicio.ConsentimientoError):
            servicio.otorgar(self.nino, CORREO, self.u_ana, actor_paciente=self.ana)

    def test_el_representante_verificado_otorga_y_queda_constancia(self):
        r = self.representacion()
        c = servicio.otorgar(self.nino, CORREO, self.u_ana, actor_paciente=self.ana)
        self.assertEqual((c.otorgante, c.representacion), ('REPRESENTANTE', r))
        self.assertTrue(servicio.vigente(self.nino, CORREO))
        self.assertEqual(RegistroConsentimiento.objects.get().representacion, r)

    def test_al_terminar_la_representacion_el_consentimiento_deja_de_valer(self):
        r = self.representacion()
        servicio.otorgar(self.nino, CORREO, self.u_ana, actor_paciente=self.ana)
        r.estado = 'TERMINADA'
        r.save()
        self.assertFalse(servicio.vigente(self.nino, CORREO))
        self.assertEqual(servicio.cerrar_vencidos(self.nino, self.recepcion), 1)
        self.assertEqual(Consentimiento.objects.get().estado, 'REVOCADO')

    def test_representacion_vencida_no_vale(self):
        self.representacion(vigente_hasta=timezone.localdate() - timedelta(days=1))
        with self.assertRaises(servicio.ConsentimientoError):
            servicio.otorgar(self.nino, CORREO, self.u_ana, actor_paciente=self.ana)

    def test_recepcion_registra_y_termina_la_representacion(self):
        self.client.force_login(self.recepcion)
        datos = {'rut_menor': self.nino.rut, 'rut_representante': self.ana.rut, 'parentesco': 'MADRE',
                 'acreditacion': 'CERTIFICADO_NACIMIENTO'}
        self.client.post(reverse('consentimientos:registrar_representacion'), datos)
        r = Representacion.objects.get()
        self.assertEqual((r.estado, r.verificada_por, r.acreditacion), ('VERIFICADA', self.recepcion.pk, 'CERTIFICADO_NACIMIENTO'))
        self.assertGreater(r.vigente_hasta, timezone.localdate())
        servicio.otorgar(self.nino, CORREO, self.u_ana, actor_paciente=self.ana)
        self.client.post(reverse('consentimientos:terminar_representacion', args=[r.pk]))
        self.assertFalse(servicio.vigente(self.nino, CORREO))

    def test_recepcion_rechaza_representar_a_un_adulto_o_a_uno_mismo(self):
        self.client.force_login(self.recepcion)
        base = {'parentesco': 'PADRE', 'acreditacion': 'OTRO'}
        self.client.post(reverse('consentimientos:registrar_representacion'), {**base, 'rut_menor': self.beto.rut, 'rut_representante': self.ana.rut})
        self.client.post(reverse('consentimientos:registrar_representacion'), {**base, 'rut_menor': self.nino.rut, 'rut_representante': self.nino.rut})
        self.assertFalse(Representacion.objects.exists())

    def test_el_representante_gestiona_desde_su_portal_y_otro_paciente_no(self):
        self.representacion()
        url = reverse('consentimientos:cambiar', args=[CORREO, 'otorgar'])
        self.client.force_login(self.u_beto)
        self.client.post(url, {'paciente': self.nino.codigo})
        self.assertFalse(Consentimiento.objects.exists())
        self.assertTrue(EventoAuditoria.objects.filter(operacion=Operacion.CONSENTIMIENTO_CAMBIO, resultado='DENEGADO').exists())
        self.client.force_login(self.u_ana)
        self.client.post(url, {'paciente': self.nino.codigo})
        self.assertTrue(servicio.vigente(self.nino, CORREO))
        pagina = self.client.get(reverse('consentimientos:mis'))
        self.assertEqual(len(pagina.context['representados']), 1)

    def test_el_registro_publico_rechaza_menores(self):
        from apps.usuarios.forms import RegistroPacienteForm
        form = RegistroPacienteForm({
            'nombres': 'Ñ', 'apellidos': 'P', 'rut': rut(44444444), 'fecha_nacimiento': nacimiento_hace(12),
            'email': 'x@c.cl', 'telefono': '+56 9 1111 2222', 'clave': CLAVE, 'clave2': CLAVE, 'aviso_privacidad': 'on',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('fecha_nacimiento', form.errors)


class PantallasYAccesoTests(Base):
    def test_el_aviso_de_privacidad_es_publico(self):
        r = self.client.get(reverse('consentimientos:aviso'))
        self.assertContains(r, 'Aviso de privacidad')
        self.assertContains(r, 'Recordatorios de citas por correo')

    def test_registro_con_consentimientos_opcionales_por_canal(self):
        datos = {
            'nombres': 'Eva', 'apellidos': 'Lira', 'rut': rut(55555555), 'fecha_nacimiento': '1990-05-01',
            'email': 'eva@c.cl', 'telefono': '+56 9 1111 2222', 'clave': CLAVE, 'clave2': CLAVE,
            'aviso_privacidad': 'on', 'recordatorios_sms': 'on',
        }
        self.client.post(reverse('registro'), datos)
        eva = Paciente.objects.get(identidad__rut_indice=indice_rut(datos['rut']))
        self.assertTrue(servicio.vigente(eva, SMS))
        self.assertFalse(servicio.vigente(eva, CORREO))
        self.assertEqual(eva.aviso_privacidad_version, 1)

    def test_el_paciente_otorga_y_retira_desde_su_portal(self):
        self.client.force_login(self.u_ana)
        self.assertContains(self.client.get(reverse('consentimientos:mis')), 'Sin autorizar')
        self.client.post(reverse('consentimientos:cambiar', args=[CORREO, 'otorgar']), {'paciente': self.ana.codigo})
        self.assertTrue(servicio.vigente(self.ana, CORREO))
        self.client.post(reverse('consentimientos:cambiar', args=[CORREO, 'revocar']), {'paciente': self.ana.codigo})
        self.assertFalse(servicio.vigente(self.ana, CORREO))
        self.assertEqual(self.client.get(reverse('consentimientos:cambiar', args=[CORREO, 'otorgar'])).status_code, 405)

    def test_acciones_desconocidas_no_cambian_nada(self):
        self.client.force_login(self.u_ana)
        self.client.post(reverse('consentimientos:cambiar', args=[CORREO, 'borrar']))
        self.client.post(reverse('consentimientos:cambiar', args=['INVENTADA', 'otorgar']))
        self.assertFalse(Consentimiento.objects.exists())

    def test_el_panel_es_solo_del_encargado_y_no_muestra_identidad(self):
        servicio.otorgar(self.ana, CORREO, self.u_ana)
        url = reverse('consentimientos:panel')
        for u in (self.u_ana, self.recepcion, self.medico, self.sysadmin):
            self.client.force_login(u)
            self.assertEqual(self.client.get(url).status_code, 403, u.username)
        self.client.force_login(self.encargado)
        r = self.client.get(url)
        self.assertContains(r, self.ana.codigo)
        for dato in (self.ana.nombres, self.ana.email, self.ana.rut, self.ana.telefono):
            self.assertNotContains(r, dato)

    def test_las_representaciones_son_solo_de_recepcion(self):
        url = reverse('consentimientos:representaciones')
        for u in (self.u_ana, self.encargado, self.medico):
            self.client.force_login(u)
            self.assertEqual(self.client.get(url).status_code, 403, u.username)
        self.client.force_login(self.recepcion)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_el_portal_de_consentimientos_exige_ser_paciente(self):
        self.client.force_login(self.recepcion)
        self.assertEqual(self.client.get(reverse('consentimientos:mis')).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('consentimientos:mis')).status_code, 302)

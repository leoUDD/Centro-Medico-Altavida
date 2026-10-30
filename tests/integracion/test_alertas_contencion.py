import hashlib
import io
import json
import tempfile
from datetime import datetime, time, timedelta
from importlib import import_module

from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.auditoria import alertas, contencion, servicio
from apps.auditoria.alertas import TransicionInvalida
from apps.auditoria.models import (AlertaSeguridad, EstadoAlerta, EstadoSistema, EventoAuditoria, ModoSistema, Operacion,
                                   Severidad)
from apps.pacientes.acceso import abrir_emergencia, tipo_de_acceso
from apps.pacientes.models import Paciente
from apps.usuarios.models import Usuario

CLAVE = 'Clave-Muy-Segura-123'
TRIGGERS = import_module('apps.auditoria.migrations.0002_proteger_con_triggers')


def crear_evento(operacion, minutos_atras=0, fecha=None, **campos):
    """Agrega un evento a la cadena con la fecha indicada (para probar ventanas de tiempo)."""
    evento = EventoAuditoria(
        fecha=fecha or timezone.now() - timedelta(minutes=minutos_atras), operacion=operacion, **campos,
    )
    evento.hash_anterior = servicio._ultimo_hash()
    evento.hash = servicio.calcular_hash(evento)
    evento.save(force_insert=True)
    return evento


def varios(operacion, cantidad, **campos):
    return [crear_evento(operacion, **campos) for _ in range(cantidad)]


def reglas(creadas):
    return sorted(a.regla for a in creadas)


class DeteccionTests(TestCase):
    def test_fuerza_bruta_contra_una_cuenta(self):
        varios(Operacion.SESION_FALLO, 4, actor_ref='abc123', ip_hash='ip1')
        self.assertEqual(alertas.detectar(), [])
        crear_evento(Operacion.SESION_FALLO, actor_ref='abc123', ip_hash='ip1')
        (alerta,) = alertas.detectar()
        self.assertEqual((alerta.regla, alerta.severidad, alerta.recurso_ref, alerta.cantidad), ('fuerza_bruta_cuenta', Severidad.MEDIA, 'abc123', 5))

    def test_los_intentos_fuera_de_la_ventana_no_cuentan(self):
        varios(Operacion.SESION_FALLO, 6, actor_ref='abc123', minutos_atras=60)
        self.assertEqual(alertas.detectar(), [])

    def test_no_repite_la_alerta_por_el_mismo_hecho_y_la_registra_en_auditoria(self):
        varios(Operacion.SESION_FALLO, 5, actor_ref='abc123')
        self.assertEqual(len(alertas.detectar()), 1)
        self.assertEqual(alertas.detectar(), [])
        self.assertEqual(AlertaSeguridad.objects.count(), 1)
        evento = EventoAuditoria.objects.get(operacion=Operacion.ALERTA_GENERADA)
        self.assertEqual(evento.detalle, {'regla': 'fuerza_bruta_cuenta', 'cantidad': 5})

    def test_rociado_de_contrasenas_desde_un_mismo_origen(self):
        for i in range(8):
            crear_evento(Operacion.SESION_FALLO, actor_ref=f'cuenta{i}', ip_hash='ipX')
        alerta = [a for a in alertas.detectar() if a.regla == 'rociado_contrasenas'][0]
        self.assertEqual((alerta.severidad, alerta.recurso_ref, alerta.cantidad), (Severidad.ALTA, 'ipX', 8))

    def test_acceso_masivo_a_fichas_cuenta_pacientes_distintos(self):
        for i in range(14):
            crear_evento(Operacion.FICHA_CONSULTA, actor_id=7, actor_rol='MEDICO', recurso_ref=f'P{i}')
        self.assertEqual(alertas.detectar(), [])
        crear_evento(Operacion.FICHA_CONSULTA, actor_id=7, actor_rol='MEDICO', recurso_ref='P14')
        (alerta,) = alertas.detectar()
        self.assertEqual((alerta.regla, alerta.severidad, alerta.actor_id), ('acceso_masivo_fichas', Severidad.ALTA, 7))

    def test_repetir_la_misma_ficha_no_es_acceso_masivo(self):
        varios(Operacion.FICHA_CONSULTA, 30, actor_id=7, actor_rol='MEDICO', recurso_ref='P1')
        self.assertEqual(alertas.detectar(), [])

    def test_otras_reglas_por_conteo(self):
        varios(Operacion.BUSQUEDA_PACIENTES, 30, actor_id=1)
        varios(Operacion.EMERGENCIA_ACCESO, 3, actor_id=2, minutos_atras=600)
        varios(Operacion.ACCESO_DENEGADO, 5, actor_id=3)
        varios(Operacion.EXPORTACION_DATOS, 3, actor_id=4)
        self.assertEqual(
            reglas(alertas.detectar()),
            ['busquedas_excesivas', 'denegaciones_repetidas', 'emergencias_repetidas', 'exportacion_masiva'],
        )

    def test_las_emergencias_se_miden_en_24_horas(self):
        varios(Operacion.EMERGENCIA_ACCESO, 2, actor_id=2)
        crear_evento(Operacion.EMERGENCIA_ACCESO, actor_id=2, minutos_atras=60 * 30)
        self.assertEqual(alertas.detectar(), [])

    def test_las_denegaciones_sin_cuenta_no_generan_alerta_por_actor(self):
        varios(Operacion.ACCESO_DENEGADO, 9)
        self.assertEqual(alertas.detectar(), [])

    @override_settings(ALERTAS_UMBRALES={'denegaciones_repetidas': {'eventos': 2}})
    def test_los_umbrales_se_pueden_ajustar(self):
        varios(Operacion.ACCESO_DENEGADO, 2, actor_id=3)
        self.assertEqual(reglas(alertas.detectar()), ['denegaciones_repetidas'])

    def test_cambio_a_un_rol_sensible(self):
        usuario = Usuario.objects.create_user('x', email='x@c.cl', password=CLAVE, rol='ADMINISTRATIVO')
        usuario.rol = 'ADMINISTRATIVO'
        usuario.save()
        self.assertEqual(alertas.detectar(), [])
        usuario.rol = 'MEDICO'
        usuario.save()
        (alerta,) = alertas.detectar()
        self.assertEqual((alerta.regla, alerta.recurso_ref), ('cambio_rol_sensible', str(usuario.pk)))
        usuario.rol = 'PACIENTE'
        usuario.save()
        self.assertEqual(alertas.detectar(), [])

    def test_acceso_nocturno_de_un_medico(self):
        hoy = timezone.localdate()
        noche = timezone.make_aware(datetime.combine(hoy, time(3, 10)))
        crear_evento(Operacion.FICHA_CONSULTA, fecha=noche, actor_id=9, actor_rol='MEDICO', recurso_ref='P1')
        self.assertEqual(alertas.detectar(ahora=timezone.make_aware(datetime.combine(hoy, time(15, 0)))), [])
        (alerta,) = alertas.detectar(ahora=noche + timedelta(minutes=20))
        self.assertEqual((alerta.regla, alerta.severidad), ('acceso_nocturno', Severidad.BAJA))

    def test_cadena_rota_es_critica(self):
        evento = crear_evento(Operacion.SESION_INICIO, actor_id=1)
        self.assertEqual(alertas.detectar(), [])
        with connection.cursor() as cursor:
            for sentencia in TRIGGERS.SQLITE_REVERSA:
                cursor.execute(sentencia)
            cursor.execute('UPDATE auditoria_eventoauditoria SET resultado = %s WHERE id = %s', ['DENEGADO', evento.id])
        (alerta,) = alertas.detectar()
        self.assertEqual((alerta.regla, alerta.severidad), ('cadena_rota', Severidad.CRITICA))

    def test_el_comando(self):
        varios(Operacion.ACCESO_DENEGADO, 5, actor_id=3)
        salida = io.StringIO()
        call_command('detectar_alertas', stdout=salida)
        self.assertIn('1 alertas nuevas', salida.getvalue())
        self.assertIn('denegaciones_repetidas', salida.getvalue())

    def test_las_alertas_no_contienen_datos_personales(self):
        varios(Operacion.SESION_FALLO, 5, actor_ref='abc123', ip_hash='ip1')
        alertas.detectar()
        fila = json.dumps(list(AlertaSeguridad.objects.values()), default=str)
        self.assertNotIn('@', fila)


class CicloDeVidaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.encargado = Usuario.objects.create_user('priv', email='priv@c.cl', password=CLAVE, rol='PRIVACIDAD')

    def alerta(self, **kw):
        return AlertaSeguridad.objects.create(
            regla='acceso_masivo_fichas', severidad=Severidad.ALTA, resumen='r', clave=f'k{AlertaSeguridad.objects.count()}', **kw,
        )

    def test_flujo_completo_hasta_cerrar_un_incidente(self):
        a = self.alerta()
        alertas.cambiar_estado(a, EstadoAlerta.EN_REVISION, self.encargado)
        alertas.cambiar_estado(a, EstadoAlerta.SOSPECHOSO, self.encargado, 'actividad rara')
        alertas.cambiar_estado(a, EstadoAlerta.INCIDENTE, self.encargado)
        with self.assertRaisesRegex(TransicionInvalida, 'preservar la evidencia'):
            alertas.cambiar_estado(a, EstadoAlerta.CERRADA, self.encargado, 'Se contuvo la cuenta y se rotaron credenciales.')
        a.evidencia_sha256 = 'a' * 64
        with self.assertRaisesRegex(TransicionInvalida, 'preservar la evidencia'):
            alertas.cambiar_estado(a, EstadoAlerta.CERRADA, self.encargado, 'corto')
        alertas.cambiar_estado(a, EstadoAlerta.CERRADA, self.encargado, 'Se contuvo la cuenta y se rotaron credenciales.')
        a.refresh_from_db()
        self.assertEqual((a.estado, a.atendida_por), (EstadoAlerta.CERRADA, self.encargado.pk))
        self.assertIsNotNone(a.cerrada_en)
        pasos = [(e.detalle['estado_anterior'], e.detalle['estado_nuevo']) for e in EventoAuditoria.objects.filter(operacion=Operacion.ALERTA_REVISADA)]
        self.assertEqual(pasos, [('ABIERTA', 'EN_REVISION'), ('EN_REVISION', 'SOSPECHOSO'), ('SOSPECHOSO', 'INCIDENTE'), ('INCIDENTE', 'CERRADA')])

    def test_una_falsa_alarma_se_descarta_y_queda_cerrada(self):
        a = self.alerta()
        alertas.cambiar_estado(a, EstadoAlerta.DESCARTADA, self.encargado, 'prueba interna')
        self.assertIsNotNone(a.cerrada_en)
        self.assertFalse(a.abierta)

    def test_no_se_permiten_saltos_ni_reabrir(self):
        a = self.alerta()
        with self.assertRaises(TransicionInvalida):
            alertas.cambiar_estado(a, EstadoAlerta.INCIDENTE, self.encargado)  # sin pasar por revisión
        alertas.cambiar_estado(a, EstadoAlerta.DESCARTADA, self.encargado)
        with self.assertRaises(TransicionInvalida):
            alertas.cambiar_estado(a, EstadoAlerta.EN_REVISION, self.encargado)

    def test_la_nota_enmascara_datos_personales(self):
        a = self.alerta()
        alertas.cambiar_estado(a, EstadoAlerta.EN_REVISION, self.encargado, 'Revisar a 15.482.331-K ana@correo.cl')
        a.refresh_from_db()
        self.assertNotIn('15.482.331', a.nota)
        self.assertNotIn('ana@correo.cl', a.nota)


@override_settings(EVIDENCIAS_DIR=tempfile.mkdtemp())
class VistasDeAlertasTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.encargado = Usuario.objects.create_user('priv', email='priv@c.cl', password=CLAVE, rol='PRIVACIDAD')
        cls.sistema = Usuario.objects.create_superuser('sis', 'sis@c.cl', CLAVE)
        cls.medico = Usuario.objects.create_user('med', email='med@c.cl', password=CLAVE, rol='MEDICO')
        cls.admin = Usuario.objects.create_user('adm', email='adm@c.cl', password=CLAVE, rol='ADMINISTRATIVO')
        cls.paciente = Usuario.objects.create_user('pac', password=CLAVE)

    def setUp(self):
        cache.clear()
        self.alerta = AlertaSeguridad.objects.create(
            regla='acceso_masivo_fichas', severidad=Severidad.ALTA, resumen='r', clave='k1', actor_id=self.medico.pk,
        )
        crear_evento(Operacion.FICHA_CONSULTA, actor_id=self.medico.pk, actor_rol='MEDICO', recurso_ref='Pabc')
        crear_evento(Operacion.FICHA_CONSULTA, actor_id=999, actor_rol='MEDICO', recurso_ref='Pajeno')

    def estado(self, usuario, nombre, *args, metodo='get', **datos):
        self.client.force_login(usuario)
        return getattr(self.client, metodo)(reverse(nombre, args=args), datos).status_code

    def test_quien_puede_ver_y_gestionar_alertas(self):
        for usuario in (self.encargado, self.sistema):
            self.assertEqual(self.estado(usuario, 'auditoria:alertas'), 200, usuario.rol)
            self.assertEqual(self.estado(usuario, 'auditoria:alerta', self.alerta.pk), 200, usuario.rol)
        for usuario in (self.medico, self.admin, self.paciente):
            self.assertEqual(self.estado(usuario, 'auditoria:alertas'), 403, usuario.rol)
            self.assertEqual(self.estado(usuario, 'auditoria:alerta', self.alerta.pk), 403, usuario.rol)
            self.assertEqual(self.estado(usuario, 'auditoria:alerta_estado', self.alerta.pk, metodo='post', estado='EN_REVISION'), 403)
            self.assertEqual(self.estado(usuario, 'auditoria:detectar', metodo='post'), 403)
            self.assertEqual(self.estado(usuario, 'auditoria:modo'), 403)

    def test_el_administrador_del_sistema_no_ve_eventos_ni_descarga_evidencia(self):
        self.client.force_login(self.sistema)
        r = self.client.get(reverse('auditoria:alerta', args=[self.alerta.pk]))
        self.assertFalse(r.context['puede_ver_eventos'])
        self.assertEqual(list(r.context['eventos']), [])
        self.assertEqual(self.client.post(reverse('auditoria:alerta_evidencia', args=[self.alerta.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse('auditoria:eventos')).status_code, 403)

    def test_las_acciones_solo_aceptan_post(self):
        self.client.force_login(self.encargado)
        for nombre in ('auditoria:detectar', 'auditoria:alerta_estado', 'auditoria:alerta_evidencia', 'auditoria:alerta_contener'):
            args = [self.alerta.pk] if nombre != 'auditoria:detectar' else []
            self.assertEqual(self.client.get(reverse(nombre, args=args)).status_code, 405, nombre)

    def test_detectar_desde_la_pantalla(self):
        varios(Operacion.ACCESO_DENEGADO, 5, actor_id=3)
        self.client.force_login(self.encargado)
        r = self.client.post(reverse('auditoria:detectar'), follow=True)
        self.assertContains(r, '1 alerta nueva')

    def test_clasificar_y_mensaje_de_error(self):
        self.client.force_login(self.encargado)
        self.client.post(reverse('auditoria:alerta_estado', args=[self.alerta.pk]), {'estado': 'EN_REVISION'})
        self.alerta.refresh_from_db()
        self.assertEqual(self.alerta.estado, EstadoAlerta.EN_REVISION)
        r = self.client.post(reverse('auditoria:alerta_estado', args=[self.alerta.pk]), {'estado': 'CERRADA'}, follow=True)
        self.assertContains(r, 'No se puede pasar')
        r = self.client.post(reverse('auditoria:alerta_estado', args=[self.alerta.pk]), {'estado': 'inventado'}, follow=True)
        self.assertContains(r, 'Estado no válido')

    def test_el_paquete_de_evidencia_es_verificable(self):
        self.client.force_login(self.encargado)
        r = self.client.post(reverse('auditoria:alerta_evidencia', args=[self.alerta.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['X-Evidencia-SHA256'], hashlib.sha256(r.content).hexdigest())
        paquete = json.loads(r.content)
        self.assertTrue(paquete['cadena']['integra'])
        self.assertTrue(all(e['actor_id'] == self.medico.pk for e in paquete['eventos']))
        self.assertIn('Pabc', r.content.decode())
        self.assertNotIn('Pajeno', r.content.decode())
        self.alerta.refresh_from_db()
        self.assertEqual(self.alerta.evidencia_sha256, r['X-Evidencia-SHA256'])
        self.assertTrue(EventoAuditoria.objects.filter(operacion=Operacion.CONTENCION, detalle__accion='preservar_evidencia').exists())

    def test_con_evidencia_preservada_se_puede_cerrar_el_incidente(self):
        self.client.force_login(self.encargado)
        for estado in ('EN_REVISION', 'INCIDENTE'):
            self.client.post(reverse('auditoria:alerta_estado', args=[self.alerta.pk]), {'estado': estado})
        self.client.post(reverse('auditoria:alerta_evidencia', args=[self.alerta.pk]))
        self.client.post(reverse('auditoria:alerta_estado', args=[self.alerta.pk]), {'estado': 'CERRADA', 'nota': 'Cuenta contenida y credenciales rotadas.'})
        self.alerta.refresh_from_db()
        self.assertEqual(self.alerta.estado, EstadoAlerta.CERRADA)

    def test_contener_desde_la_alerta(self):
        self.client.force_login(self.sistema)
        r = self.client.post(reverse('auditoria:alerta_contener', args=[self.alerta.pk]), {'accion': 'desactivar'}, follow=True)
        self.assertContains(r, 'Hecho')
        self.medico.refresh_from_db()
        self.assertFalse(self.medico.is_active)
        r = self.client.post(reverse('auditoria:alerta_contener', args=[self.alerta.pk]), {'accion': 'inventada'}, follow=True)
        self.assertContains(r, 'Acción no válida')

    def test_quien_no_tiene_el_permiso_no_puede_contener(self):
        for usuario in (self.medico, self.admin, self.paciente):
            self.assertEqual(self.estado(usuario, 'auditoria:alerta_contener', self.alerta.pk, metodo='post', accion='desactivar'), 403)
        self.medico.refresh_from_db()
        self.assertTrue(self.medico.is_active)


class ContencionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.sistema = Usuario.objects.create_superuser('sis', 'sis@c.cl', CLAVE)
        cls.otro_sistema = Usuario.objects.create_superuser('sis2', 'sis2@c.cl', CLAVE)
        cls.encargado = Usuario.objects.create_user('priv', email='priv@c.cl', password=CLAVE, rol='PRIVACIDAD')
        cls.medico = Usuario.objects.create_user('med', email='med@c.cl', password=CLAVE, rol='MEDICO')
        cls.otro_medico = Usuario.objects.create_user('med2', email='med2@c.cl', password=CLAVE, rol='MEDICO')
        cls.paciente = Paciente.objects.create(rut='15482331K', nombres='María', apellidos='Fuentes', creado_por=cls.medico)

    def setUp(self):
        cache.clear()

    def test_desactivar_cierra_las_sesiones_y_cuenta_en_la_auditoria(self):
        self.client.force_login(self.medico)
        self.assertEqual(self.client.get(reverse('fichas:buscar')).status_code, 200)
        contencion.desactivar_cuenta(self.medico, self.sistema)
        self.assertEqual(self.client.get(reverse('fichas:buscar')).status_code, 302)  # su sesión ya no existe
        self.assertEqual(self.client.post(reverse('login'), {'usuario': 'med@c.cl', 'clave': CLAVE}).status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)
        acciones = [e.detalle.get('accion') for e in EventoAuditoria.objects.filter(operacion=Operacion.CONTENCION)]
        self.assertEqual(acciones, ['revocar_sesiones', 'desactivar_cuenta'])
        self.assertTrue(EventoAuditoria.objects.filter(operacion=Operacion.CUENTA_ESTADO_CAMBIO).exists())
        self.assertEqual(EventoAuditoria.objects.filter(operacion=Operacion.CONTENCION).first().actor_id, self.sistema.pk)

    def test_revocar_sesiones_solo_afecta_a_esa_cuenta(self):
        propio, ajeno = self.client_class(), self.client_class()
        propio.force_login(self.medico)
        ajeno.force_login(self.otro_medico)
        self.assertEqual(contencion.revocar_sesiones(self.medico, self.sistema), 1)
        self.assertEqual(propio.get(reverse('fichas:buscar')).status_code, 302)
        self.assertEqual(ajeno.get(reverse('fichas:buscar')).status_code, 200)

    def test_restringir_quita_todos_los_permisos_y_restaurar_los_devuelve(self):
        self.client.force_login(self.medico)
        contencion.restringir_cuenta(self.medico, self.sistema)
        self.medico.refresh_from_db()
        self.assertTrue(self.medico.acceso_restringido)
        self.client.force_login(self.medico)  # puede iniciar sesión, pero no hacer nada
        self.assertEqual(self.client.get(reverse('fichas:buscar')).status_code, 403)
        contencion.restaurar_cuenta(self.medico, self.sistema)
        self.client.force_login(Usuario.objects.get(pk=self.medico.pk))
        self.assertEqual(self.client.get(reverse('fichas:buscar')).status_code, 200)

    def test_invalidar_credenciales(self):
        contencion.invalidar_credenciales(self.medico, self.sistema)
        self.medico.refresh_from_db()
        self.assertFalse(self.medico.has_usable_password())
        self.client.post(reverse('login'), {'usuario': 'med@c.cl', 'clave': CLAVE})
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertTrue(self.medico.is_active)  # la cuenta sigue existiendo: se recupera asignando otra contraseña

    def test_cerrar_emergencias_vence_los_accesos_sin_borrar_el_registro(self):
        abrir_emergencia(self.otro_medico, self.paciente, 'Urgencia de prueba en guardia')
        self.assertEqual(tipo_de_acceso(self.otro_medico, self.paciente), 'emergencia')
        self.assertEqual(contencion.cerrar_emergencias(self.otro_medico, self.sistema), 1)
        self.assertIsNone(tipo_de_acceso(self.otro_medico, self.paciente))
        self.assertEqual(self.otro_medico.accesos_emergencia.count(), 1)

    def test_salvaguardas(self):
        with self.assertRaisesRegex(contencion.ContencionError, 'a ti mismo'):
            contencion.desactivar_cuenta(self.sistema, self.sistema)
        contencion.desactivar_cuenta(self.otro_sistema, self.sistema)
        with self.assertRaisesRegex(contencion.ContencionError, 'único administrador'):
            contencion.restringir_cuenta(self.sistema, self.encargado)
        contencion.restringir_cuenta(self.sistema, None, 'comando', forzar=True)  # el servidor puede forzarlo
        self.sistema.refresh_from_db()
        self.assertTrue(self.sistema.acceso_restringido)

    def test_modo_solo_lectura(self):
        contencion.cambiar_modo(ModoSistema.SOLO_LECTURA, self.encargado, motivo_codigo='incidente-1')
        self.client.force_login(self.medico)
        self.assertEqual(self.client.get(reverse('fichas:buscar')).status_code, 200)
        self.assertEqual(self.client.post(reverse('fichas:nueva'), {}).status_code, 503)
        self.assertContains(self.client.post(reverse('fichas:nueva'), {}), 'solo lectura', status_code=503)
        self.client.force_login(self.encargado)  # el personal de seguridad sí puede operar
        self.assertEqual(self.client.post(reverse('auditoria:modo'), {'modo': 'NORMAL'}).status_code, 302)
        self.client.force_login(self.medico)
        self.assertNotEqual(self.client.post(reverse('fichas:nueva'), {}).status_code, 503)

    def test_modo_bloqueado(self):
        contencion.cambiar_modo(ModoSistema.BLOQUEADO, self.sistema)
        self.client.force_login(self.medico)
        self.assertEqual(self.client.get(reverse('fichas:buscar')).status_code, 503)
        self.assertEqual(self.client.get(reverse('login')).status_code, 302)  # el inicio de sesión sigue disponible
        self.client.force_login(self.sistema)
        self.assertEqual(self.client.get('/admin/').status_code, 200)
        self.client.force_login(self.encargado)
        self.assertEqual(self.client.get(reverse('auditoria:eventos')).status_code, 200)

    def test_el_cambio_de_modo_queda_registrado(self):
        contencion.cambiar_modo(ModoSistema.SOLO_LECTURA, self.encargado, motivo_codigo='incidente-1')
        evento = EventoAuditoria.objects.get(operacion=Operacion.CONTENCION)
        self.assertEqual(evento.detalle, {'accion': 'cambiar_modo', 'estado_anterior': 'NORMAL', 'estado_nuevo': 'SOLO_LECTURA', 'metodo': 'interfaz'})
        self.assertEqual(EstadoSistema.actual().motivo_codigo, 'incidente-1')

    def test_comandos(self):
        call_command('contener', 'cuenta', 'desactivar', '--usuario', 'med', stdout=io.StringIO())
        self.assertFalse(Usuario.objects.get(username='med').is_active)
        call_command('contener', 'cuenta', 'restaurar', '--usuario', str(self.medico.pk), stdout=io.StringIO())
        self.assertTrue(Usuario.objects.get(username='med').is_active)
        call_command('contener', 'modo', 'SOLO_LECTURA', '--motivo', 'caso-9', stdout=io.StringIO())
        self.assertEqual(contencion.modo_actual(), 'SOLO_LECTURA')
        with self.assertRaisesRegex(CommandError, 'No existe'):
            call_command('contener', 'cuenta', 'desactivar', '--usuario', 'nadie', stdout=io.StringIO())
        call_command('contener', 'cuenta', 'desactivar', '--usuario', 'sis2', stdout=io.StringIO())
        with self.assertRaisesRegex(CommandError, 'único administrador'):
            call_command('contener', 'cuenta', 'desactivar', '--usuario', 'sis', stdout=io.StringIO())
        call_command('contener', 'cuenta', 'desactivar', '--usuario', 'sis', '--forzar', stdout=io.StringIO())
        self.assertTrue(all(e.actor_id is None for e in EventoAuditoria.objects.filter(operacion=Operacion.CONTENCION)))

    @override_settings(EVIDENCIAS_DIR=tempfile.mkdtemp())
    def test_comando_de_evidencia(self):
        alerta = AlertaSeguridad.objects.create(regla='r', severidad=Severidad.ALTA, resumen='r', clave='k', actor_id=self.medico.pk)
        salida = io.StringIO()
        call_command('contener', 'evidencia', '--alerta', str(alerta.pk), stdout=salida)
        alerta.refresh_from_db()
        self.assertIn(alerta.evidencia_sha256, salida.getvalue())

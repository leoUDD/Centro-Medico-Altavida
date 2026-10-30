import io
import json
from datetime import timedelta
from importlib import import_module
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, OperationalError, connection
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.auditoria import servicio
from apps.auditoria.models import EventoAuditoria, Operacion, PuntoControlAuditoria, Resultado
from apps.pacientes.acceso import abrir_emergencia
from apps.pacientes.models import Paciente
from apps.usuarios import roles
from apps.usuarios.models import Usuario

CLAVE = 'Clave-Muy-Segura-123'
TRIGGERS = import_module('apps.auditoria.migrations.0002_proteger_con_triggers')


def quitar_triggers():
    with connection.cursor() as cursor:
        for sentencia in TRIGGERS.SQLITE_REVERSA:
            cursor.execute(sentencia)


def poner_triggers():
    with connection.cursor() as cursor:
        for sentencia in TRIGGERS.SQLITE:
            cursor.execute(sentencia)


def evento_antiguo(meses):
    """Evento viejo, agregado a la cadena como lo haría servicio.registrar pero con una fecha del pasado."""
    evento = EventoAuditoria(
        fecha=timezone.now() - timedelta(days=30 * meses + 5), operacion=Operacion.SESION_INICIO, recurso_tipo='cuenta',
    )
    evento.hash_anterior = servicio._ultimo_hash()
    evento.hash = servicio.calcular_hash(evento)
    evento.save(force_insert=True)
    return evento


def todo_el_registro():
    return json.dumps(list(EventoAuditoria.objects.values()), default=str, ensure_ascii=False)


class CadenaTests(TestCase):
    def test_los_eventos_se_encadenan(self):
        a = servicio.registrar(Operacion.SESION_INICIO, 'cuenta', 1)
        b = servicio.registrar(Operacion.SESION_CIERRE, 'cuenta', 1)
        self.assertEqual(a.hash_anterior, servicio.GENESIS)
        self.assertEqual(b.hash_anterior, a.hash)
        self.assertNotEqual(a.hash, b.hash)
        self.assertEqual(servicio.verificar(), (True, None, 2))

    def test_el_hash_no_depende_de_la_zona_horaria_con_que_se_cree_el_evento(self):
        from datetime import datetime, time
        local = timezone.make_aware(datetime.combine(timezone.localdate(), time(3, 10)))
        evento = EventoAuditoria(fecha=local, operacion=Operacion.SESION_INICIO)
        evento.hash_anterior = servicio._ultimo_hash()
        evento.hash = servicio.calcular_hash(evento)
        evento.save(force_insert=True)
        self.assertEqual(servicio.verificar(), (True, None, 1))

    def test_el_hash_depende_de_la_llave_de_auditoria(self):
        evento = servicio.registrar(Operacion.SESION_INICIO, 'cuenta', 1)
        with self.settings(CLAVE_AUDITORIA='AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA='):
            self.assertNotEqual(servicio.calcular_hash(evento), evento.hash)

    def test_alterar_un_evento_rompe_la_cadena(self):
        servicio.registrar(Operacion.SESION_INICIO, 'cuenta', 1)
        medio = servicio.registrar(Operacion.FICHA_CONSULTA, 'paciente', 'Pabc')
        servicio.registrar(Operacion.SESION_CIERRE, 'cuenta', 1)
        quitar_triggers()  # simula a alguien con acceso total a la base que desactiva las protecciones
        with connection.cursor() as cursor:
            cursor.execute('UPDATE auditoria_eventoauditoria SET resultado = %s WHERE id = %s', ['DENEGADO', medio.id])
        self.assertEqual(servicio.verificar(), (False, medio.id, 1))

    def test_borrar_un_evento_del_medio_rompe_la_cadena(self):
        servicio.registrar(Operacion.SESION_INICIO, 'cuenta', 1)
        medio = servicio.registrar(Operacion.FICHA_CONSULTA, 'paciente', 'Pabc')
        ultimo = servicio.registrar(Operacion.SESION_CIERRE, 'cuenta', 1)
        quitar_triggers()
        with connection.cursor() as cursor:
            cursor.execute('DELETE FROM auditoria_eventoauditoria WHERE id = %s', [medio.id])
        self.assertEqual(servicio.verificar(), (False, ultimo.id, 1))

    def test_un_evento_falsificado_sin_la_llave_no_pasa(self):
        servicio.registrar(Operacion.SESION_INICIO, 'cuenta', 1)
        falso = EventoAuditoria(operacion=Operacion.SESION_CIERRE, hash_anterior=servicio._ultimo_hash(), hash='f' * 64)
        falso.save(force_insert=True)
        self.assertFalse(servicio.verificar()[0])

    def test_el_comando_verificar_falla_si_la_cadena_esta_rota(self):
        evento = servicio.registrar(Operacion.SESION_INICIO, 'cuenta', 1)
        salida = io.StringIO()
        call_command('verificar_auditoria', stdout=salida)
        self.assertIn('íntegra', salida.getvalue())
        quitar_triggers()
        with connection.cursor() as cursor:
            cursor.execute('UPDATE auditoria_eventoauditoria SET operacion = %s WHERE id = %s', ['FICHA_CONSULTA', evento.id])
        with self.assertRaisesRegex(CommandError, 'Cadena rota'):
            call_command('verificar_auditoria', stdout=io.StringIO())


class InmutabilidadTests(TestCase):
    def setUp(self):
        self.evento = servicio.registrar(Operacion.SESION_INICIO, 'cuenta', 1)

    def test_la_aplicacion_no_modifica_ni_borra(self):
        with self.assertRaises(PermissionError):
            self.evento.save()
        with self.assertRaises(PermissionError):
            self.evento.delete()
        consulta = EventoAuditoria.objects.all()
        for operacion in (lambda: consulta.update(resultado='OK'), consulta.delete,
                          lambda: consulta.bulk_update([self.evento], ['resultado']),
                          lambda: EventoAuditoria.objects.bulk_create([EventoAuditoria()])):
            with self.assertRaises(PermissionError):
                operacion()

    def test_la_base_rechaza_update_con_sql_directo(self):
        with self.assertRaises(IntegrityError), connection.cursor() as cursor:
            cursor.execute('UPDATE auditoria_eventoauditoria SET resultado = %s', ['DENEGADO'])
        self.assertEqual(servicio.verificar()[0], True)

    def test_la_base_rechaza_borrar_eventos_recientes_con_sql_directo(self):
        with self.assertRaises(IntegrityError), connection.cursor() as cursor:
            cursor.execute('DELETE FROM auditoria_eventoauditoria')
        self.assertEqual(EventoAuditoria.objects.count(), 1)

    def test_la_base_permite_borrar_solo_eventos_de_mas_de_24_meses(self):
        viejo = evento_antiguo(25)
        with connection.cursor() as cursor:
            cursor.execute('DELETE FROM auditoria_eventoauditoria WHERE id = %s', [viejo.id])
        self.assertFalse(EventoAuditoria.objects.filter(id=viejo.id).exists())
        reciente = evento_antiguo(12)
        with self.assertRaises(IntegrityError), connection.cursor() as cursor:
            cursor.execute('DELETE FROM auditoria_eventoauditoria WHERE id = %s', [reciente.id])

    def test_los_puntos_de_control_tampoco_se_tocan(self):
        punto = PuntoControlAuditoria.objects.create(eliminado_hasta_id=1, hash_ultimo='a' * 64, cantidad=1)
        with self.assertRaises(PermissionError):
            punto.save()
        with self.assertRaises(PermissionError):
            punto.delete()
        with self.assertRaises(IntegrityError), connection.cursor() as cursor:
            cursor.execute('DELETE FROM auditoria_puntocontrolauditoria')
        with self.assertRaises(IntegrityError), connection.cursor() as cursor:
            cursor.execute('UPDATE auditoria_puntocontrolauditoria SET cantidad = 9')

    def test_con_las_protecciones_activas_el_sql_directo_no_puede_reescribir_la_historia(self):
        quitar_triggers()
        poner_triggers()  # volver a instalarlas deja el estado normal
        with self.assertRaises(IntegrityError), connection.cursor() as cursor:
            cursor.execute('UPDATE auditoria_eventoauditoria SET hash = %s', ['0' * 64])


class DepuracionTests(TestCase):
    def test_purgar_elimina_lo_vencido_deja_punto_de_control_y_la_cadena_sigue_valida(self):
        evento_antiguo(30)
        evento_antiguo(26)
        nuevo = servicio.registrar(Operacion.SESION_INICIO, 'cuenta', 1)
        self.assertEqual(servicio.verificar(), (True, None, 3))
        self.assertEqual(servicio.purgar(), 2)
        self.assertEqual(list(EventoAuditoria.objects.values_list('operacion', flat=True)),
                         [Operacion.SESION_INICIO, Operacion.AUDITORIA_PURGA])
        self.assertEqual(PuntoControlAuditoria.objects.get().cantidad, 2)
        self.assertEqual(servicio.verificar(), (True, None, 2))
        self.assertTrue(EventoAuditoria.objects.filter(pk=nuevo.pk).exists())

    def test_purgar_no_toca_eventos_dentro_del_plazo(self):
        servicio.registrar(Operacion.SESION_INICIO, 'cuenta', 1)
        evento_antiguo(10)
        self.assertEqual(servicio.purgar(), 0)
        self.assertEqual(EventoAuditoria.objects.count(), 2)

    def test_se_puede_seguir_registrando_despues_de_purgar_todo(self):
        evento_antiguo(40)
        servicio.purgar()
        servicio.registrar(Operacion.SESION_INICIO, 'cuenta', 1)
        self.assertTrue(servicio.verificar()[0])

    def test_el_comando_de_purga(self):
        evento_antiguo(30)
        salida = io.StringIO()
        call_command('purgar_auditoria', stdout=salida)
        self.assertIn('1 eventos eliminados', salida.getvalue())


class ContenidoSeguroTests(TestCase):
    def test_el_detalle_solo_admite_claves_de_la_lista_y_descarta_credenciales(self):
        evento = servicio.registrar(Operacion.SESION_INICIO, 'cuenta', 1, detalle={
            'cantidad': 3, 'password': 'secreta', 'token_sesion': 'abc', 'clave': 'x', 'inventada': 'x', 'finalidad': 'ok',
        })
        self.assertEqual(evento.detalle, {'cantidad': 3, 'finalidad': 'ok'})

    def test_enmascara_rut_correo_y_telefono_que_se_cuelen_en_un_texto(self):
        evento = servicio.registrar(Operacion.BUSQUEDA_PACIENTES, detalle={
            'finalidad': 'busca 15.482.331-K ana@correo.cl +56 9 1234 4821',
        })
        for dato in ('15.482.331', 'ana@correo.cl', '1234 4821'):
            self.assertNotIn(dato, evento.detalle['finalidad'])

    def test_los_textos_largos_se_truncan(self):
        evento = servicio.registrar(Operacion.BUSQUEDA_PACIENTES, detalle={'finalidad': 'x' * 500})
        self.assertEqual(len(evento.detalle['finalidad']), servicio.LARGO_MAXIMO)

    def test_la_direccion_ip_solo_se_guarda_como_huella(self):
        peticion = RequestFactory().get('/', REMOTE_ADDR='203.0.113.77')
        evento = servicio.registrar(Operacion.ACCESO_DENEGADO, 'vista', 'x', Resultado.DENEGADO, peticion=peticion)
        self.assertEqual(len(evento.ip_hash), 16)
        self.assertNotIn('203.0.113.77', todo_el_registro())
        otro = servicio.registrar(Operacion.ACCESO_DENEGADO, peticion=peticion)
        self.assertEqual(evento.ip_hash, otro.ip_hash)  # permite correlacionar sin guardar la IP

    def test_la_huella_del_identificador_no_revela_el_dato(self):
        huella = servicio.huella_identificador('15.482.331-K')
        self.assertEqual(len(huella), 16)
        self.assertNotIn('15482331', huella)
        self.assertEqual(huella, servicio.huella_identificador(' 15.482.331-k '))

    def test_un_fallo_de_auditoria_no_interrumpe_la_operacion(self):
        with self.assertLogs('apps.auditoria', 'ERROR'), mock.patch.object(EventoAuditoria, 'save', side_effect=RuntimeError('base caída')):
            self.assertIsNone(servicio.registrar(Operacion.SESION_INICIO, 'cuenta', 1))
        usuario = Usuario.objects.create_user('p_a', password=CLAVE, rol='PACIENTE')
        with self.assertLogs('apps.auditoria', 'ERROR'), mock.patch.object(EventoAuditoria, 'save', side_effect=RuntimeError('base caída')):
            self.client.post(reverse('login'), {'usuario': 'p_a', 'clave': CLAVE})
        self.assertIn('_auth_user_id', self.client.session)
        self.assertEqual(int(self.client.session['_auth_user_id']), usuario.pk)


class IntegracionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.medico = Usuario.objects.create_user('med', email='med@c.cl', password=CLAVE, rol='MEDICO')
        cls.otro_medico = Usuario.objects.create_user('med2', email='med2@c.cl', password=CLAVE, rol='MEDICO')
        cls.usuario = Usuario.objects.create_user('pac', password=CLAVE)
        cls.paciente = Paciente.objects.create(
            usuario=cls.usuario, rut='15482331K', nombres='María José', apellidos='Fuentes Soto',
            fecha_nacimiento='1985-03-12', email='maria@correo.cl', telefono='+56 9 1234 4821', creado_por=cls.medico,
        )

    def setUp(self):
        cache.clear()

    def operaciones(self, **filtro):
        return list(EventoAuditoria.objects.filter(**filtro).values_list('operacion', flat=True))

    def test_inicio_de_sesion_correcto_fallido_y_cierre(self):
        self.client.post(reverse('login'), {'usuario': 'med@c.cl', 'clave': 'mala'})
        self.client.post(reverse('login'), {'usuario': 'med@c.cl', 'clave': CLAVE})
        self.client.post(reverse('logout'))
        fallo, inicio, cierre = (EventoAuditoria.objects.get(operacion=o) for o in
                                 (Operacion.SESION_FALLO, Operacion.SESION_INICIO, Operacion.SESION_CIERRE))
        self.assertEqual((fallo.resultado, fallo.actor_id), (Resultado.FALLIDO, None))
        self.assertEqual(len(fallo.actor_ref), 16)
        self.assertEqual((inicio.actor_id, inicio.actor_rol), (self.medico.pk, 'MEDICO'))
        self.assertEqual(cierre.actor_id, self.medico.pk)
        self.assertNotIn('med@c.cl', todo_el_registro())
        self.assertNotIn(CLAVE, todo_el_registro())
        self.assertNotIn('mala', todo_el_registro())

    def test_el_bloqueo_por_intentos_queda_registrado(self):
        for _ in range(6):
            self.client.post(reverse('login'), {'usuario': 'med@c.cl', 'clave': 'mala'})
        self.assertEqual(self.operaciones(operacion=Operacion.SESION_FALLO).__len__(), 5)
        bloqueo = EventoAuditoria.objects.get(operacion=Operacion.SESION_BLOQUEO)
        self.assertEqual(bloqueo.resultado, Resultado.DENEGADO)

    def test_consulta_de_ficha_usa_el_codigo_seudonimo_y_no_datos_personales(self):
        self.client.force_login(self.medico)
        self.client.get(reverse('fichas:detalle', args=[self.paciente.pk]))
        evento = EventoAuditoria.objects.get(operacion=Operacion.FICHA_CONSULTA)
        self.assertEqual((evento.recurso_tipo, evento.recurso_ref, evento.actor_id), ('paciente', self.paciente.codigo, self.medico.pk))
        registro = todo_el_registro()
        for dato in ('María', 'Fuentes', '15482331', '15.482.331', 'maria@correo.cl', '1234 4821'):
            self.assertNotIn(dato, registro)

    def test_busqueda_y_emergencia(self):
        self.client.force_login(self.medico)
        self.client.get(reverse('fichas:buscar'), {'q': 'fuentes'})
        busqueda = EventoAuditoria.objects.get(operacion=Operacion.BUSQUEDA_PACIENTES)
        self.assertEqual(busqueda.detalle, {'cantidad': 1, 'finalidad': 'Búsqueda de pacientes'})
        self.assertNotIn('fuentes', todo_el_registro().lower())
        self.client.force_login(self.otro_medico)
        self.client.post(reverse('fichas:emergencia', args=[self.paciente.pk]), {'motivo': 'Paciente inconsciente en urgencias'})
        emergencia = EventoAuditoria.objects.get(operacion=Operacion.EMERGENCIA_ACCESO)
        self.assertEqual((emergencia.actor_id, emergencia.recurso_ref), (self.otro_medico.pk, self.paciente.codigo))
        self.assertNotIn('inconsciente', todo_el_registro())

    def test_un_acceso_denegado_registra_la_vista_y_quien_lo_intento(self):
        self.client.force_login(self.usuario)
        self.assertEqual(self.client.get(reverse('fichas:buscar')).status_code, 403)
        denegado = EventoAuditoria.objects.get(operacion=Operacion.ACCESO_DENEGADO)
        self.assertEqual((denegado.resultado, denegado.actor_id, denegado.recurso_ref), (Resultado.DENEGADO, self.usuario.pk, 'fichas:buscar'))

    def test_registro_de_citas(self):
        from apps.agenda.models import Cita
        from apps.agenda.servicios import cancelar_cita, confirmar_asistencia
        inicio = timezone.now() + timedelta(days=3)
        cita = Cita.objects.create(paciente=self.paciente, tipo='CONSULTA', inicio=inicio, fin=inicio + timedelta(minutes=30))
        confirmar_asistencia(cita)
        cancelar_cita(cita)
        self.assertEqual(self.operaciones(operacion__in=[Operacion.CITA_CAMBIO]), [Operacion.CITA_CAMBIO] * 2)
        self.assertEqual([e.detalle['accion'] for e in EventoAuditoria.objects.filter(operacion=Operacion.CITA_CAMBIO)], ['confirmar', 'cancelar'])

    def test_cambios_de_cuenta(self):
        self.assertTrue(EventoAuditoria.objects.filter(operacion=Operacion.CUENTA_CREADA, recurso_ref=str(self.usuario.pk)).exists())
        self.otro_medico.rol = 'ADMINISTRATIVO'
        self.otro_medico.save()
        cambio = EventoAuditoria.objects.get(operacion=Operacion.CUENTA_ROL_CAMBIO)
        self.assertEqual(cambio.detalle, {'rol_anterior': 'MEDICO', 'rol_nuevo': 'ADMINISTRATIVO'})
        self.otro_medico.is_active = False
        self.otro_medico.save()
        self.assertTrue(EventoAuditoria.objects.filter(operacion=Operacion.CUENTA_ESTADO_CAMBIO).exists())
        for dato in ('med2@c.cl', CLAVE, 'argon2'):
            self.assertNotIn(dato, todo_el_registro())

    def test_la_cuenta_creada_por_un_administrador_queda_con_su_actor(self):
        sistema = Usuario.objects.create_superuser('sis', 'sis@c.cl', CLAVE)
        peticion = RequestFactory().get('/')
        peticion.user = sistema
        from apps.auditoria import contexto
        token = contexto.fijar(peticion)
        try:
            nuevo = Usuario.objects.create_user('nuevo', email='n@c.cl', password=CLAVE, rol='MEDICO')
        finally:
            contexto.restablecer(token)
        evento = EventoAuditoria.objects.get(operacion=Operacion.CUENTA_CREADA, recurso_ref=str(nuevo.pk))
        self.assertEqual((evento.actor_id, evento.actor_rol), (sistema.pk, 'ADMIN_SISTEMA'))

    def test_procesos_del_sistema(self):
        call_command('purgar_datos', stdout=io.StringIO())
        call_command('rotar_llaves', stdout=io.StringIO())
        self.assertTrue(EventoAuditoria.objects.filter(operacion=Operacion.RETENCION_APLICADA, actor_id=None).exists())
        self.assertTrue(EventoAuditoria.objects.filter(operacion=Operacion.LLAVES_ROTADAS, actor_id=None).exists())


class ConsultaYPermisosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.encargado = Usuario.objects.create_user('priv', email='priv@c.cl', password=CLAVE, rol='PRIVACIDAD')
        cls.medico = Usuario.objects.create_user('med', email='med@c.cl', password=CLAVE, rol='MEDICO')
        cls.admin = Usuario.objects.create_user('adm', email='adm@c.cl', password=CLAVE, rol='ADMINISTRATIVO')
        cls.paciente = Usuario.objects.create_user('pac', password=CLAVE)
        cls.sistema = Usuario.objects.create_superuser('sis', 'sis@c.cl', CLAVE)

    def test_el_encargado_de_privacidad_tiene_exactamente_sus_permisos(self):
        grupo = self.encargado.groups.get()
        self.assertEqual(grupo.name, 'Encargado de privacidad')
        self.assertEqual({p.codename for p in grupo.permissions.all()}, set(roles.ROLES['PRIVACIDAD']['permisos']))

    def test_solo_el_encargado_ve_la_auditoria(self):
        url = reverse('auditoria:eventos')
        for usuario in (self.medico, self.admin, self.paciente, self.sistema):
            self.client.force_login(usuario)
            self.assertEqual(self.client.get(url).status_code, 403, usuario.rol)
            self.assertEqual(self.client.post(reverse('auditoria:verificar')).status_code, 403, usuario.rol)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.encargado)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_el_administrador_del_sistema_no_puede_leer_ni_por_el_sitio_de_administracion(self):
        self.assertFalse(self.sistema.has_perm('usuarios.ver_auditoria'))
        self.assertFalse(self.sistema.has_perm('auditoria.view_eventoauditoria'))
        self.client.force_login(self.sistema)
        self.assertNotContains(self.client.get('/admin/'), 'Auditoría')

    def test_el_encargado_no_accede_a_datos_clinicos_ni_a_la_agenda(self):
        self.client.force_login(self.encargado)
        for url in (reverse('fichas:buscar'), reverse('recepcion:dashboard'), reverse('pacientes:resultados')):
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_inicio_del_encargado(self):
        self.client.force_login(self.encargado)
        self.assertRedirects(self.client.get(reverse('inicio')), reverse('auditoria:eventos'), fetch_redirect_response=False)

    def test_la_lista_filtra_y_la_propia_consulta_queda_registrada(self):
        servicio.registrar(Operacion.FICHA_CONSULTA, 'paciente', 'Pabc', actor=self.medico)
        servicio.registrar(Operacion.ACCESO_DENEGADO, 'vista', 'x', Resultado.DENEGADO, actor=self.paciente)
        self.client.force_login(self.encargado)
        r = self.client.get(reverse('auditoria:eventos'), {'resultado': 'DENEGADO'})
        self.assertTrue(all(e.resultado == 'DENEGADO' for e in r.context['pagina']))
        r = self.client.get(reverse('auditoria:eventos'), {'recurso': 'Pabc'})
        self.assertEqual([e.operacion for e in r.context['pagina']], [Operacion.FICHA_CONSULTA])
        self.assertTrue(EventoAuditoria.objects.filter(operacion=Operacion.AUDITORIA_CONSULTA, actor_id=self.encargado.pk).exists())

    def test_verificar_desde_la_pantalla(self):
        servicio.registrar(Operacion.SESION_INICIO, 'cuenta', 1)
        self.client.force_login(self.encargado)
        r = self.client.post(reverse('auditoria:verificar'), follow=True)
        self.assertContains(r, 'Cadena íntegra')
        self.assertEqual(self.client.get(reverse('auditoria:verificar')).status_code, 405)
        quitar_triggers()
        with connection.cursor() as cursor:
            cursor.execute("UPDATE auditoria_eventoauditoria SET resultado = 'DENEGADO' WHERE id = (SELECT MIN(id) FROM auditoria_eventoauditoria)")
        r = self.client.post(reverse('auditoria:verificar'), follow=True)
        self.assertContains(r, '¡La cadena está rota!')
        self.assertTrue(EventoAuditoria.objects.filter(operacion=Operacion.AUDITORIA_VERIFICACION, resultado=Resultado.FALLIDO).exists())

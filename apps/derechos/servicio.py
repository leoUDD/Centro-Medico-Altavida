"""Reglas del ejercicio de derechos. Las vistas solo llaman a estas funciones: ninguna transición ni ejecución ocurre fuera de aquí."""
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from apps.agenda.models import Cita
from apps.auditoria import contencion
from apps.auditoria import servicio as auditoria
from apps.auditoria.models import Operacion, Resultado
from apps.consentimientos import servicio as consentimientos
from apps.consentimientos.models import Consentimiento, Representacion
from apps.notificaciones.models import Notificacion, PreferenciasNotificacion, Recordatorio
from apps.seguridad.indice import indice_ciego, indice_correo

from .models import HistorialSolicitud, SolicitudDerecho

Estado = SolicitudDerecho.Estado
Tipo = SolicitudDerecho.Tipo
Resolucion = SolicitudDerecho.Resolucion
Fundamento = SolicitudDerecho.Fundamento

# Transiciones permitidas: cualquier otra se rechaza, aunque alguien fabrique la petición a mano.
TRANSICIONES = {
    Estado.RECIBIDA: {Estado.EN_VERIFICACION},
    Estado.EN_VERIFICACION: {Estado.EN_EVALUACION, Estado.RESUELTA},
    Estado.EN_EVALUACION: {Estado.RESUELTA},
    Estado.RESUELTA: {Estado.CERRADA},
    Estado.CERRADA: set(),
}
VIGENCIA_CODIGO = timedelta(minutes=15)
INTENTOS_CODIGO = 5
ENVIOS_CODIGO = 3


class DerechosError(Exception):
    """Operación no permitida; el mensaje es apto para mostrar al usuario."""


def _transicion(solicitud, nuevo, actor=None, detalle=''):
    if nuevo not in TRANSICIONES[solicitud.estado]:
        raise DerechosError('Ese paso no corresponde al estado actual de la solicitud.')
    anterior = solicitud.estado
    solicitud.estado = nuevo
    solicitud.save()
    HistorialSolicitud.objects.create(
        solicitud=solicitud, estado_anterior=anterior, estado_nuevo=nuevo,
        actor_id=getattr(actor, 'pk', None), detalle=detalle[:40],
    )
    return anterior


def _auditar(operacion, solicitud, actor, resultado=Resultado.OK, **detalle):
    auditoria.registrar(
        operacion, 'solicitud_derechos', solicitud.paciente.codigo, resultado=resultado, actor=actor,
        detalle={'codigo_solicitud': solicitud.codigo, 'tipo': solicitud.tipo, **detalle},
    )


# ---------------------------------------------------------------- recepción

def _validar_representacion(solicitante, paciente):
    if solicitante.pk == paciente.pk:
        if consentimientos.es_menor(paciente):
            raise DerechosError('Por ser menor de edad, la solicitud la debe hacer su representante legal.')
        return
    representacion = Representacion.objects.filter(menor=paciente, representante=solicitante).first()
    if representacion is None or not representacion.vigente:
        raise DerechosError('No tienes una representación legal verificada para esta persona.')


@transaction.atomic
def crear(solicitante, paciente, tipo, usuario, campo='', valor=''):
    if tipo not in Tipo.values:
        raise DerechosError('Tipo de solicitud desconocido.')
    _validar_representacion(solicitante, paciente)
    if paciente.datos_bloqueados_desde:
        raise DerechosError('Tus datos ya fueron suprimidos o bloqueados; no hay más que solicitar por este medio.')
    if tipo == Tipo.RECTIFICACION:
        if campo not in SolicitudDerecho.Campo.values or (campo != SolicitudDerecho.Campo.CLINICO and not valor.strip()):
            raise DerechosError('Indica qué dato quieres corregir y cuál es el valor correcto.')
        if campo == SolicitudDerecho.Campo.CLINICO and not valor.strip():
            raise DerechosError('Describe qué dato clínico crees que está equivocado.')
    else:
        campo, valor = '', ''
    nivel = 1 if (tipo == Tipo.RECTIFICACION and campo not in SolicitudDerecho.CAMPOS_SENSIBLES
                  and campo != SolicitudDerecho.Campo.CLINICO) else 2
    ahora = timezone.now()
    try:
        solicitud = SolicitudDerecho.objects.create(
            paciente=paciente, solicitante=solicitante, tipo=tipo, campo=campo, valor_propuesto=valor.strip(),
            recibida_en=ahora, plazo_hasta=(ahora + timedelta(days=settings.DERECHOS_PLAZO_DIAS)).date(),
            nivel_requerido=nivel,
        )
    except IntegrityError:
        raise DerechosError('Ya tienes una solicitud de este tipo en curso.')
    HistorialSolicitud.objects.create(solicitud=solicitud, estado_nuevo=Estado.RECIBIDA, actor_id=getattr(usuario, 'pk', None))
    _auditar(Operacion.DERECHO_SOLICITUD, solicitud, usuario, campo=campo, estado_nuevo=Estado.RECIBIDA)
    _transicion(solicitud, Estado.EN_VERIFICACION, usuario)
    if nivel == 2:
        enviar_codigo(solicitud, usuario)
    return solicitud


# ------------------------------------------------------------ verificación

@sensitive_variables()
def enviar_codigo(solicitud, usuario):
    """Envía un código de 6 dígitos al correo registrado de quien solicita. Nunca queda en logs ni en la base en claro."""
    if solicitud.estado != Estado.EN_VERIFICACION or solicitud.nivel_requerido < 2:
        raise DerechosError('Esta solicitud no necesita código.')
    if solicitud.codigos_enviados >= ENVIOS_CODIGO:
        raise DerechosError('Ya se enviaron los códigos permitidos. Acércate a recepción para verificar tu identidad.')
    correo = solicitud.solicitante.email
    if not correo:
        raise DerechosError('No tenemos un correo registrado para enviarte el código. Acércate a recepción.')
    codigo = f'{secrets.randbelow(10 ** 6):06d}'
    solicitud.codigo_huella = indice_ciego(f'{solicitud.codigo}:{codigo}', 'derechos')
    solicitud.codigo_expira = timezone.now() + VIGENCIA_CODIGO
    solicitud.codigo_intentos = 0
    solicitud.codigos_enviados += 1
    solicitud.save()
    send_mail(
        'Tu código de verificación en Centro Médico Altavida',
        f'Tu código para continuar con la solicitud {solicitud.codigo} es {codigo}. Vence en 15 minutos. '
        'Si no fuiste tú, ignora este mensaje.',
        getattr(settings, 'DEFAULT_FROM_EMAIL', None), [correo],
    )
    _auditar(Operacion.DERECHO_VERIFICACION, solicitud, usuario, metodo='codigo_enviado')


@sensitive_variables()
def verificar(solicitud, usuario, clave_correcta, codigo=''):
    """Verifica a quien solicita. `clave_correcta` es el resultado de pedir su contraseña de nuevo en esta misma petición."""
    if solicitud.estado != Estado.EN_VERIFICACION:
        raise DerechosError('La identidad de esta solicitud ya fue revisada.')
    if not clave_correcta:
        _auditar(Operacion.DERECHO_VERIFICACION, solicitud, usuario, Resultado.DENEGADO, metodo='clave')
        raise DerechosError('La contraseña no es correcta.')
    if solicitud.nivel_requerido >= 2:
        valido = False
        if solicitud.codigo_intentos >= INTENTOS_CODIGO:
            raise DerechosError('Superaste los intentos con ese código. Pide uno nuevo.')
        solicitud.codigo_intentos += 1
        solicitud.save(update_fields=['codigo_intentos'])
        if solicitud.codigo_huella and solicitud.codigo_expira and solicitud.codigo_expira > timezone.now():
            esperado = indice_ciego(f'{solicitud.codigo}:{codigo.strip()}', 'derechos')
            valido = hmac.compare_digest(esperado, solicitud.codigo_huella)
        if not valido:
            _auditar(Operacion.DERECHO_VERIFICACION, solicitud, usuario, Resultado.DENEGADO, metodo='codigo')
            raise DerechosError('El código no es correcto o ya venció.')
        solicitud.codigo_huella = ''  # un código sirve una sola vez
    solicitud.verificada_en = timezone.now()
    _transicion(solicitud, Estado.EN_EVALUACION, usuario, 'identidad_verificada')
    _auditar(Operacion.DERECHO_VERIFICACION, solicitud, usuario, metodo='clave+codigo' if solicitud.nivel_requerido >= 2 else 'clave',
             estado_nuevo=Estado.EN_EVALUACION)


# -------------------------------------------------------------- resolución

def _fecha_ultima_atencion(paciente):
    fechas = [
        paciente.citas.order_by('-inicio').values_list('inicio', flat=True).first(),
        paciente.diagnosticos.order_by('-fecha').values_list('fecha', flat=True).first(),
        paciente.recetas.order_by('-creada').values_list('creada', flat=True).first(),
        paciente.resultados.order_by('-fecha').values_list('fecha', flat=True).first(),
    ]
    fechas = [f for f in fechas if f]
    return max(fechas) if fechas else None


def tiene_datos_clinicos(paciente):
    return bool(
        paciente.citas.exists() or paciente.diagnosticos.exists() or paciente.recetas.exists()
        or paciente.resultados.exists() or hasattr(paciente, 'historial')
    )


def conservar_hasta(paciente):
    ultima = _fecha_ultima_atencion(paciente)
    if ultima is None:
        return None
    ultima = timezone.localtime(ultima)
    return ultima.replace(year=ultima.year + settings.FICHA_CONSERVACION_ANIOS).date()


def _suprimir(paciente, ejecutor):
    """Elimina lo que no hay obligación de conservar y bloquea el resto. Devuelve (hubo_datos_que_se_conservan, cantidad)."""
    cantidad = 0
    for consentimiento in Consentimiento.objects.filter(paciente=paciente, estado=Consentimiento.Estado.OTORGADO).select_related('finalidad', 'texto'):
        consentimiento.estado, consentimiento.revocado_en = Consentimiento.Estado.REVOCADO, timezone.now()
        consentimiento.save()
        paciente.registros_consentimiento.create(
            finalidad=consentimiento.finalidad, texto=consentimiento.texto, accion='REVOCADO',
            otorgante=consentimiento.otorgante, representacion=consentimiento.representacion, canal='DERECHOS',
            registrado_por=getattr(ejecutor, 'pk', None),
        )
        cantidad += 1
    cantidad += Notificacion.objects.filter(paciente=paciente).delete()[0]
    cantidad += Recordatorio.objects.filter(cita__paciente=paciente).delete()[0]
    cantidad += PreferenciasNotificacion.objects.filter(paciente=paciente).delete()[0]
    Cita.objects.filter(paciente=paciente).exclude(orden_externa='').update(
        orden_externa='', orden_externa_nombre='', orden_externa_tipo='')
    cuenta = paciente.usuario
    if cuenta is not None:
        contencion.revocar_sesiones(cuenta, ejecutor)
        cuenta.is_active = False
        cuenta.set_unusable_password()
        cuenta.rut_indice = cuenta.correo_indice = None
        cuenta.save()
        cantidad += 1
    conserva = tiene_datos_clinicos(paciente)
    if not conserva:
        # Sin ficha ni atenciones no hay nada que conservar: se elimina también el diccionario de identidad.
        cantidad += paciente.identidad.delete()[0] if hasattr(paciente, 'identidad') else 0
    paciente.datos_bloqueados_desde = timezone.now()
    paciente.save(update_fields=['datos_bloqueados_desde'])
    return conserva, cantidad


def _rectificar(solicitud, ejecutor):
    paciente, campo, valor = solicitud.paciente, solicitud.campo, solicitud.valor_propuesto
    if campo == 'email':
        from django.contrib.auth import get_user_model
        if get_user_model().objects.filter(correo_indice=indice_correo(valor)).exclude(pk=paciente.usuario_id).exists():
            raise DerechosError('Ese correo ya está en uso en otra cuenta.')
    paciente.actualizar_identidad(**{campo: valor})
    auditoria.registrar(Operacion.RECTIFICACION, 'paciente', paciente.codigo, actor=ejecutor,
                        detalle={'campo': campo, 'codigo_solicitud': solicitud.codigo})


@transaction.atomic
def resolver(solicitud, ejecutor, resolucion, fundamento='', respuesta=''):
    """Evalúa y resuelve. Solo el Encargado de privacidad llega aquí (la vista exige el permiso)."""
    if resolucion not in Resolucion.values:
        raise DerechosError('Resolución desconocida.')
    if fundamento and fundamento not in Fundamento.values:
        raise DerechosError('Fundamento desconocido.')
    sin_identidad = solicitud.verificada_en is None
    if sin_identidad and not (resolucion == Resolucion.RECHAZADA and fundamento == Fundamento.IDENTIDAD_NO_VERIFICADA):
        raise DerechosError('No se puede ejecutar nada mientras no se verifique la identidad de quien solicita.')
    if resolucion == Resolucion.RECHAZADA and not fundamento:
        raise DerechosError('Un rechazo debe indicar su fundamento.')
    tipo, paciente = solicitud.tipo, solicitud.paciente
    extra = {}
    if resolucion != Resolucion.RECHAZADA:
        if tipo in (Tipo.ACCESO, Tipo.PORTABILIDAD):
            solicitud.descarga_hasta = timezone.now() + timedelta(days=settings.DERECHOS_DESCARGA_DIAS)
        elif tipo == Tipo.RECTIFICACION:
            if solicitud.campo != SolicitudDerecho.Campo.CLINICO:
                _rectificar(solicitud, ejecutor)
            elif resolucion == Resolucion.EJECUTADA:
                raise DerechosError('Un dato clínico no se modifica: resuélvelo como parcial (anotación aclaratoria) o rechazado.')
        elif tipo == Tipo.SUPRESION:
            conserva, cantidad = _suprimir(paciente, ejecutor)
            extra['cantidad'] = cantidad
            if conserva:
                resolucion, fundamento = Resolucion.PARCIAL, Fundamento.CONSERVACION_LEGAL
                hasta = conservar_hasta(paciente)
                respuesta = (respuesta + ' ' if respuesta else '') + (
                    f'Eliminamos tu cuenta, tus recordatorios y tus autorizaciones. Tu ficha clínica debe conservarse por ley '
                    f'hasta el {hasta:%d-%m-%Y} y queda bloqueada: solo se usa para esa conservación y para tu atención.')
            auditoria.registrar(Operacion.SUPRESION, 'paciente', paciente.codigo, actor=ejecutor,
                                detalle={'codigo_solicitud': solicitud.codigo, 'estado_nuevo': 'PARCIAL' if conserva else 'TOTAL', **extra})
    solicitud.resolucion, solicitud.fundamento = resolucion, fundamento
    solicitud.respuesta = respuesta.strip()
    solicitud.resuelta_en, solicitud.resuelta_por = timezone.now(), ejecutor.pk
    _transicion(solicitud, Estado.RESUELTA, ejecutor, resolucion.lower())
    _auditar(Operacion.DERECHO_RESOLUCION, solicitud, ejecutor, estado_nuevo=Estado.RESUELTA, motivo_codigo=fundamento or resolucion)
    return solicitud


def cerrar(solicitud, ejecutor):
    _transicion(solicitud, Estado.CERRADA, ejecutor)
    solicitud.cerrada_en = timezone.now()
    solicitud.descarga_hasta = None  # cerrada la solicitud, el archivo ya no se puede bajar
    solicitud.save()
    _auditar(Operacion.DERECHO_RESOLUCION, solicitud, ejecutor, estado_nuevo=Estado.CERRADA)


# -------------------------------------------------------------- exportación

def puede_descargar(solicitud):
    return (
        solicitud.estado == Estado.RESUELTA and solicitud.tipo in (Tipo.ACCESO, Tipo.PORTABILIDAD)
        and solicitud.resolucion in (Resolucion.EJECUTADA, Resolucion.PARCIAL) and solicitud.descarga_hasta is not None
        and solicitud.descarga_hasta > timezone.now() and solicitud.descargas < settings.DERECHOS_DESCARGAS_MAX
    )


def _t(valor):
    return None if valor is None else (valor.isoformat() if hasattr(valor, 'isoformat') else str(valor))


def armar_exportacion(paciente, con_informacion=False):
    """Todo lo que el centro guarda del paciente, en estructura. No incluye datos de otras personas ni de funcionarios."""
    identidad = {c: getattr(paciente, c) for c in (
        'rut_formateado', 'nombres', 'apellidos', 'fecha_nacimiento', 'email', 'telefono',
        'contacto_emergencia_nombre', 'contacto_emergencia_parentesco', 'contacto_emergencia_telefono')}
    historial = getattr(paciente, 'historial', None)
    datos = {
        'paciente': paciente.codigo,
        'generado_en': _t(timezone.now()),
        'identidad': identidad,
        'datos_de_contexto': {'sexo': paciente.sexo, 'grupo_sanguineo': paciente.grupo_sanguineo,
                              'peso': paciente.peso, 'estatura': paciente.estatura},
        'historial_medico': None if historial is None else {
            'enfermedades': historial.enfermedades, 'medicamentos_activos': historial.medicamentos_activos,
            'operaciones': historial.operaciones, 'alergias': historial.alergias},
        'diagnosticos': [
            {'fecha': _t(d.fecha), 'codigo_cie10': d.codigo_cie10, 'diagnostico': d.diagnostico,
             'tratamiento': d.tratamiento, 'estado': d.estado} for d in paciente.diagnosticos.all()],
        'recetas': [
            {'fecha': _t(r.creada), 'estado': r.estado, 'indicaciones': r.indicaciones,
             'medicamentos': [{'medicamento': i.medicamento, 'dosis': i.dosis, 'frecuencia': i.frecuencia,
                               'duracion': i.duracion, 'via': i.via} for i in r.items.all()]}
            for r in paciente.recetas.all()],
        'resultados_de_examenes': [
            {'examen': e.tipo_examen, 'estado': e.estado, 'fecha_toma': _t(e.fecha_toma), 'resultado': e.resultado,
             'observacion_medica': e.observacion_medico} for e in paciente.resultados.all()],
        'citas': [{'tipo': c.tipo, 'estado': c.estado, 'inicio': _t(c.inicio), 'modalidad': c.modalidad}
                  for c in paciente.citas.all()],
        'consentimientos': [
            {'finalidad': r.finalidad.codigo, 'accion': r.accion, 'fecha': _t(r.fecha), 'version_texto': r.texto.version}
            for r in paciente.registros_consentimiento.select_related('finalidad', 'texto')],
        'solicitudes_de_derechos': [
            {'codigo': s.codigo, 'tipo': s.tipo, 'estado': s.estado, 'recibida_en': _t(s.recibida_en)}
            for s in paciente.solicitudes_derechos.all()],
    }
    if con_informacion:
        datos['informacion_sobre_el_tratamiento'] = {
            'responsable': 'Centro Médico Altavida',
            'finalidades': ['Prestarte atención médica y mantener tu ficha clínica (obligación legal y contrato)',
                            'Gestionar tus citas', 'Recordatorios por correo o SMS, solo si los autorizaste'],
            'conservacion': f'Ficha clínica: al menos {settings.FICHA_CONSERVACION_ANIOS} años desde la última atención. '
                            'Datos de gestión: 24 meses desde la última atención.',
            'destinatarios': 'No se ceden a terceros salvo obligación legal.',
            'derechos': ['acceso', 'rectificación', 'supresión', 'portabilidad'],
        }
    return datos


@transaction.atomic
def registrar_descarga(solicitud, usuario):
    """Cuenta y audita cada descarga. Devuelve el contenido a entregar."""
    solicitud.refresh_from_db()
    if not puede_descargar(solicitud):
        raise DerechosError('Esta descarga ya no está disponible.')
    solicitud.descargas += 1
    solicitud.save(update_fields=['descargas'])
    _auditar(Operacion.EXPORTACION_DATOS, solicitud, usuario, formato='json', cantidad=solicitud.descargas)
    return armar_exportacion(solicitud.paciente, con_informacion=solicitud.tipo == Tipo.ACCESO)

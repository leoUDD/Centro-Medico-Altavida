"""Modelo de roles y permisos (RBAC).

Un permiso describe una capacidad ("ver datos clínicos"); un rol agrupa permisos; cada usuario tiene un rol y,
por tanto, un grupo de Django con esos permisos. Las vistas piden permisos, no roles (ver permisos.py).
"""
from django.contrib.auth.models import Group, Permission

# (código, descripción). Se crean como permisos de Django en la app "usuarios".
PERMISOS = (
    ('portal_paciente', 'Usar el portal del paciente (solo sus propios datos)'),
    ('ver_identidad', 'Ver datos identificadores de pacientes (nombre, RUT, contacto)'),
    ('ver_datos_clinicos', 'Ver fichas, diagnósticos, resultados y recetas de pacientes con relación'),
    ('editar_datos_clinicos', 'Registrar fichas, diagnósticos y observaciones clínicas'),
    ('emitir_recetas', 'Emitir y firmar recetas'),
    ('acceso_emergencia', 'Abrir un acceso de emergencia a un paciente sin relación (con motivo)'),
    ('gestionar_agenda', 'Confirmar y cancelar citas, y gestionar recordatorios'),
    ('editar_contacto_paciente', 'Corregir correo y teléfono de un paciente'),
    ('ver_bitacora', 'Consultar las bitácoras de acceso'),
    ('ver_auditoria', 'Consultar y verificar el registro de auditoría (referencias seudónimas, sin datos personales)'),
    ('gestionar_alertas', 'Revisar alertas de seguridad y registrar su resolución'),
    ('ejecutar_contencion', 'Ejecutar acciones de contención: desactivar cuentas y revocar sesiones'),
    ('gestionar_derechos', 'Evaluar y resolver solicitudes de ejercicio de derechos de los titulares'),
    ('ver_consentimientos', 'Consultar el estado e historial de consentimientos de los pacientes'),
)

ROLES = {
    'PACIENTE': {'grupo': 'Paciente', 'permisos': ['portal_paciente']},
    'MEDICO': {
        'grupo': 'Médico',
        'permisos': ['ver_identidad', 'ver_datos_clinicos', 'editar_datos_clinicos', 'emitir_recetas', 'acceso_emergencia'],
    },
    'ADMINISTRATIVO': {
        'grupo': 'Personal administrativo',
        'permisos': ['ver_identidad', 'gestionar_agenda', 'editar_contacto_paciente'],
    },
    'ADMIN_SISTEMA': {
        'grupo': 'Administrador del sistema', 'permisos': ['ver_bitacora', 'gestionar_alertas', 'ejecutar_contencion'],
    },
    # Función independiente de quien administra el sistema: supervisa el uso de los datos y atiende a los titulares.
    'PRIVACIDAD': {
        'grupo': 'Encargado de privacidad',
        'permisos': ['ver_auditoria', 'gestionar_alertas', 'ejecutar_contencion', 'gestionar_derechos', 'ver_consentimientos'],
    },
}

# Apps cuyos datos son clínicos o identificadores: el administrador del sistema no entra a ellas.
APPS_CLINICAS = {'pacientes', 'fichas_clinicas', 'recetas', 'laboratorio', 'convenios', 'auditoria', 'consentimientos', 'derechos'}
# Excepciones: las bitácoras sí las puede consultar (solo lectura), para auditar quién accedió a qué.
BITACORAS = {
    'fichas_clinicas.view_accesoficha', 'pacientes.view_accesoidentidad', 'pacientes.view_accesoemergencia',
}
# Permisos de negocio que el administrador del sistema no puede ejercer aunque sea superusuario de Django.
PERMISOS_CLINICOS = {f'usuarios.{codigo}' for codigo in (
    'portal_paciente', 'ver_identidad', 'ver_datos_clinicos', 'editar_datos_clinicos', 'emitir_recetas',
    'acceso_emergencia', 'gestionar_agenda', 'editar_contacto_paciente', 'ver_auditoria', 'gestionar_derechos',
    'ver_consentimientos',
)}


def reservado_para_clinica(perm):
    """True si el permiso da acceso a datos clínicos o identificadores (y no es de una bitácora)."""
    if perm in BITACORAS:
        return False
    return perm in PERMISOS_CLINICOS or perm.split('.')[0] in APPS_CLINICAS


def asegurar_roles(**kwargs):
    """Crea los grupos y les asigna sus permisos. Es idempotente: se ejecuta después de cada migración."""
    permisos = {p.codename: p for p in Permission.objects.filter(content_type__app_label='usuarios')}
    for definicion in ROLES.values():
        grupo, _ = Group.objects.get_or_create(name=definicion['grupo'])
        grupo.permissions.set([permisos[c] for c in definicion['permisos'] if c in permisos])


def sincronizar_grupo(usuario):
    """Deja al usuario en el grupo de su rol y en ningún otro: el rol es la única fuente de permisos."""
    nombre = ROLES[usuario.rol]['grupo']
    grupo, _ = Group.objects.get_or_create(name=nombre)
    if list(usuario.groups.values_list('name', flat=True)) != [nombre]:
        usuario.groups.set([grupo])

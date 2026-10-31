from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.auditoria import contencion
from apps.auditoria.models import AlertaSeguridad, ModoSistema

ACCIONES_CUENTA = {
    'revocar-sesiones': contencion.revocar_sesiones,
    'restringir': contencion.restringir_cuenta,
    'desactivar': contencion.desactivar_cuenta,
    'invalidar-credenciales': contencion.invalidar_credenciales,
    'cerrar-emergencias': contencion.cerrar_emergencias,
    'restaurar': contencion.restaurar_cuenta,
}


class Command(BaseCommand):
    help = (
        'Contención y recuperación desde el servidor (último recurso si la interfaz no está disponible; exige acceso al '
        'servidor). Ejemplos:\n'
        '  contener cuenta desactivar --usuario dra.rojas\n'
        '  contener modo SOLO_LECTURA --motivo incidente-12\n'
        '  contener evidencia --alerta 7'
    )

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest='objetivo', required=True)
        cuenta = sub.add_parser('cuenta', help='Acción sobre una cuenta')
        cuenta.add_argument('accion', choices=sorted(ACCIONES_CUENTA))
        cuenta.add_argument('--usuario', required=True, help='Nombre de usuario o id de la cuenta')
        cuenta.add_argument('--forzar', action='store_true', help='Permite contener al único administrador activo')
        modo = sub.add_parser('modo', help='Cambia el modo del sistema')
        modo.add_argument('modo', choices=[m.value for m in ModoSistema])
        modo.add_argument('--motivo', default='', help='Código corto del caso, sin datos personales')
        evidencia = sub.add_parser('evidencia', help='Preserva la evidencia de una alerta')
        evidencia.add_argument('--alerta', type=int, required=True)

    def handle(self, *args, **o):
        if o['objetivo'] == 'modo':
            contencion.cambiar_modo(o['modo'], None, 'comando', o['motivo'])
            self.stdout.write(self.style.SUCCESS(f"Modo del sistema: {o['modo']}."))
        elif o['objetivo'] == 'evidencia':
            try:
                alerta = AlertaSeguridad.objects.get(pk=o['alerta'])
            except AlertaSeguridad.DoesNotExist:
                raise CommandError('No existe esa alerta.')
            _contenido, huella, archivo = contencion.preservar_evidencia(alerta, None, 'comando')
            self.stdout.write(self.style.SUCCESS(f'Evidencia en {archivo}\nSHA-256: {huella}'))
        else:
            Usuario = get_user_model()
            ref = o['usuario']
            usuario = Usuario.objects.filter(pk=int(ref)).first() if ref.isdigit() else Usuario.objects.filter(username=ref).first()
            if usuario is None:
                raise CommandError('No existe esa cuenta.')
            funcion = ACCIONES_CUENTA[o['accion']]
            try:
                if o['accion'] in ('desactivar', 'restringir', 'invalidar-credenciales'):
                    funcion(usuario, None, 'comando', forzar=o['forzar'])
                else:
                    funcion(usuario, None, 'comando')
            except contencion.ContencionError as error:
                raise CommandError(str(error))
            self.stdout.write(self.style.SUCCESS(f"Hecho: {o['accion']} sobre la cuenta #{usuario.pk}."))

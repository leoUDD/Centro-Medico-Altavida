from django.core.management.base import BaseCommand, CommandError

from apps.auditoria import servicio
from apps.auditoria.models import Operacion, Resultado


class Command(BaseCommand):
    help = 'Verifica que la cadena de hashes del registro de auditoría no haya sido alterada. Termina con error si lo fue.'

    def handle(self, *args, **opciones):
        integra, primer_problema, total = servicio.verificar()
        servicio.registrar(
            Operacion.AUDITORIA_VERIFICACION, 'auditoria', primer_problema or '',
            resultado=Resultado.OK if integra else Resultado.FALLIDO, detalle={'eventos': total, 'metodo': 'comando'},
        )
        if not integra:
            raise CommandError(f'Cadena rota en el evento #{primer_problema} (se verificaron {total} eventos antes).')
        self.stdout.write(self.style.SUCCESS(f'Cadena íntegra: {total} eventos verificados.'))

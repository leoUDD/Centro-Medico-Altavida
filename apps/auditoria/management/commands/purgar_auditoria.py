from django.core.management.base import BaseCommand

from apps.auditoria import servicio


class Command(BaseCommand):
    help = 'Elimina los eventos de auditoría que superaron la retención (por defecto 24 meses). Ejecutar una vez al mes.'

    def handle(self, *args, **opciones):
        cantidad = servicio.purgar()
        self.stdout.write(self.style.SUCCESS(
            f'{cantidad} eventos eliminados (retención: {servicio.meses_de_retencion()} meses).'
        ))

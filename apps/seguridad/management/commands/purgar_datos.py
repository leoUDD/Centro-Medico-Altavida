from django.core.management.base import BaseCommand

from apps.seguridad.retencion import purgar


class Command(BaseCommand):
    help = 'Elimina los datos cuyo plazo de retención venció (avisos, órdenes externas, recordatorios). Ejecutar a diario.'

    def handle(self, *args, **opciones):
        resultado = purgar()
        detalle = ', '.join(f'{nombre}: {cantidad}' for nombre, cantidad in resultado.items())
        self.stdout.write(self.style.SUCCESS(f'Retención aplicada ({detalle}).'))

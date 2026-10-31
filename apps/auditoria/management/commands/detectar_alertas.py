from django.core.management.base import BaseCommand

from apps.auditoria import alertas


class Command(BaseCommand):
    help = 'Ejecuta las reglas de detección sobre el registro de auditoría y crea alertas. Programar cada 5 a 10 minutos.'

    def handle(self, *args, **opciones):
        nuevas = alertas.detectar()
        for alerta in nuevas:
            self.stdout.write(f'  #{alerta.pk} [{alerta.severidad}] {alerta.regla}: {alerta.resumen}')
        self.stdout.write(self.style.SUCCESS(f'{len(nuevas)} alertas nuevas.'))

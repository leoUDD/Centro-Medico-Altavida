from django.core.management.base import BaseCommand

from apps.notificaciones.recordatorios import ejecutar


class Command(BaseCommand):
    help = 'Genera y envía los recordatorios de citas que corresponden ahora. Programar cada hora (cron o Programador de tareas).'

    def handle(self, *args, **opciones):
        ejecucion = ejecutar()
        self.stdout.write(self.style.SUCCESS(
            f'{ejecucion.creados} generados, {ejecucion.enviados} enviados, {ejecucion.fallidos} fallidos.'
        ))

import csv

from django.core.management.base import BaseCommand

from apps.seguridad.anonimizacion import COLUMNAS, K_MINIMO, reporte_diagnosticos


class Command(BaseCommand):
    help = 'Genera un CSV de diagnósticos anonimizado (tramos de edad, categoría CIE-10, sin grupos pequeños).'

    def add_arguments(self, parser):
        parser.add_argument('--salida', default='reporte_anonimo.csv', help='Archivo CSV de salida.')
        parser.add_argument('--k', type=int, default=K_MINIMO, help='Mínimo de personas por grupo (k-anonimato).')

    def handle(self, *args, **opciones):
        filas = reporte_diagnosticos(k=opciones['k'])
        with open(opciones['salida'], 'w', newline='', encoding='utf-8') as archivo:
            escritor = csv.writer(archivo)
            escritor.writerow(COLUMNAS)
            escritor.writerows(filas)
        self.stdout.write(self.style.SUCCESS(
            f'{len(filas)} grupos escritos en {opciones["salida"]} (k = {opciones["k"]}).'
        ))

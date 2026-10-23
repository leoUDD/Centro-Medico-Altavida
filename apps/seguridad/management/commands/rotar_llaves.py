from django.apps import apps
from django.core.management.base import BaseCommand

from apps.seguridad.campos import CampoCifrado
from apps.seguridad.cifrado import identificador_de
from apps.seguridad.llaves import llave_actual


class Command(BaseCommand):
    help = (
        'Reescribe con la llave actual los datos cifrados con una llave anterior o en el formato anterior. '
        'Rotación: definir la llave nueva como CLAVE_* y la vieja como CLAVE_*_ANTERIOR, ejecutar este comando y, '
        'cuando no queden datos antiguos, quitar la variable *_ANTERIOR. '
        'Migración desde el formato anterior: ejecutarlo con CIFRADO_FORMATO_ANTERIOR=1.'
    )

    def handle(self, *args, **opciones):
        reescritos = ilegibles = 0
        for modelo in apps.get_models():
            campos = [f for f in modelo._meta.concrete_fields if isinstance(f, CampoCifrado)]
            if not campos:
                continue
            actuales = {f.proposito: llave_actual(f.proposito)[0] for f in campos}
            for pk in list(modelo._base_manager.values_list('pk', flat=True)):
                crudo = modelo._base_manager.filter(pk=pk).values(*(f.attname for f in campos)).first()
                viejos = [f for f in campos if crudo[f.attname] and identificador_de(crudo[f.attname]) != actuales[f.proposito]]
                if not viejos:
                    continue
                try:
                    objeto = modelo._base_manager.get(pk=pk)  # al leer se descifra con la llave o el formato anterior
                    nuevos = {f.attname: getattr(objeto, f.attname) for f in viejos}
                except Exception as error:  # dato ilegible: se informa y se deja intacto
                    ilegibles += 1
                    self.stderr.write(f'{modelo._meta.label} #{pk}: no se pudo leer ({type(error).__name__}).')
                    continue
                modelo._base_manager.filter(pk=pk).update(**nuevos)  # al guardar se cifra con la llave actual
                reescritos += 1
        self.stdout.write(self.style.SUCCESS(f'{reescritos} registros reescritos con la llave actual.'))
        if ilegibles:
            self.stdout.write(self.style.WARNING(f'{ilegibles} registros no se pudieron leer y quedaron sin cambios.'))

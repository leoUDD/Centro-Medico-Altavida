from django.apps import apps
from django.core.management.base import BaseCommand

from apps.seguridad.campos import CampoCifrado
from apps.seguridad.cifrado import identificador_de
from apps.seguridad.llaves import llave_actual


class Command(BaseCommand):
    help = (
        'Reescribe con la llave actual los datos cifrados con la llave anterior. '
        'Uso: definir la llave nueva como CLAVE_* y la vieja como CLAVE_*_ANTERIOR, ejecutar este comando y, '
        'cuando no queden datos antiguos, quitar la variable *_ANTERIOR.'
    )

    def handle(self, *args, **opciones):
        total = 0
        for modelo in apps.get_models():
            campos = [f for f in modelo._meta.concrete_fields if isinstance(f, CampoCifrado)]
            if not campos:
                continue
            actuales = {f.proposito: llave_actual(f.proposito)[0] for f in campos}
            for objeto in modelo._default_manager.all().iterator():
                crudo = modelo._base_manager.filter(pk=objeto.pk).values(*(f.attname for f in campos)).first()
                viejos = [f for f in campos if crudo[f.attname] and identificador_de(crudo[f.attname]) != actuales[f.proposito]]
                if viejos:
                    # Al guardar, cada campo se descifra con la llave anterior (ya cargado en memoria) y se cifra con la actual.
                    modelo._base_manager.filter(pk=objeto.pk).update(**{f.attname: getattr(objeto, f.attname) for f in viejos})
                    total += 1
        self.stdout.write(self.style.SUCCESS(f'{total} registros reescritos con la llave actual.'))

from django.db import models

from .cifrado import cifrar, descifrar


class CampoCifrado(models.TextField):
    """Columna de texto cifrada con AES-GCM.

    `proposito` elige la llave: "clinica" (por defecto) o "identidad". El contexto autenticado es el nombre de
    la columna (app.modelo.campo), de modo que el valor no sirve si se copia a otra columna.
    """

    def __init__(self, *args, proposito='clinica', **kwargs):
        self.proposito = proposito
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        nombre, ruta, args, kwargs = super().deconstruct()
        if self.proposito != 'clinica':
            kwargs['proposito'] = self.proposito
        return nombre, ruta, args, kwargs

    def contribute_to_class(self, cls, name, private_only=False):
        super().contribute_to_class(cls, name, private_only=private_only)
        self.contexto = f'{cls._meta.label_lower}.{name}'

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None or value == '':
            return value
        return cifrar(str(value), self.contexto, self.proposito)

    def from_db_value(self, value, expression, connection):
        if value is None or value == '':
            return value
        return descifrar(value, self.contexto, self.proposito)

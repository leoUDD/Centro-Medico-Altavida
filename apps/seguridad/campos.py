from django.db import models

from .cifrado import cifrar, descifrar


class CampoCifrado(models.TextField):
    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None or value == '':
            return value
        return cifrar(str(value))

    def from_db_value(self, value, expression, connection):
        if value is None or value == '':
            return value
        return descifrar(value)

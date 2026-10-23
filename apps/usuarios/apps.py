from django.apps import AppConfig
from django.db.models.signals import post_migrate


class UsuariosConfig(AppConfig):
    name = 'apps.usuarios'

    def ready(self):
        from .roles import asegurar_roles
        post_migrate.connect(asegurar_roles, dispatch_uid='altavida.asegurar_roles')

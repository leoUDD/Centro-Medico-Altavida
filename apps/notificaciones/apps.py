from django.apps import AppConfig


class NotificacionesConfig(AppConfig):
    name = 'apps.notificaciones'

    def ready(self):
        from . import signals  # noqa: F401

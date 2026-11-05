from django.apps import AppConfig


class SparesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'spares'
    verbose_name = 'Запчасти'

    def ready(self):
        from . import signals  # noqa: F401

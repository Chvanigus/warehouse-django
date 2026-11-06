"""Конфигурация складского приложения для реестра Django."""

from django.apps import AppConfig


class SparesConfig(AppConfig):
    """Регистрирует приложение и его обработчики складских событий."""
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'spares'
    verbose_name = 'Запчасти'

    def ready(self):
        """Подключает сигналы после загрузки моделей Django."""
        from . import signals  # noqa: F401

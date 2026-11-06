"""Регистрация общих компонентов в реестре Django."""

from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Подключает обработчики ошибок и библиотеку шаблонных фильтров."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

"""Общие проверки складских операций."""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone


def require_operation_actor(actor, error_message):
    """Потребовать аутентифицированного автора с сохранённой учётной записью."""
    if not getattr(actor, 'is_authenticated', False) or actor.pk is None:
        raise ValidationError(error_message)


def load_operation_actor(actor, error_message):
    """Загрузить активного автора в транзакции без сохранённых в объекте прав."""
    require_operation_actor(actor, error_message)
    current_actor = get_user_model()._default_manager.select_for_update().filter(pk=actor.pk, is_active=True).first()
    if current_actor is None:
        raise ValidationError(error_message)
    return current_actor


def validate_posting_date(value):
    """Запретить проведение документа будущей датой по местному времени."""
    if value > timezone.localdate():
        raise ValidationError('Дата проведения не может быть в будущем.')

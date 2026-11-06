"""Общие проверки складских операций."""

from django.core.exceptions import ValidationError
from django.utils import timezone


def require_operation_actor(actor, error_message):
    """Потребовать аутентифицированного автора с сохранённой учётной записью."""
    if not getattr(actor, 'is_authenticated', False) or actor.pk is None:
        raise ValidationError(error_message)


def validate_posting_date(value):
    """Запретить проведение документа будущей датой по местному времени."""
    if value > timezone.localdate():
        raise ValidationError('Дата проведения не может быть в будущем.')

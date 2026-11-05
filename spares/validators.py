from django.core.exceptions import ValidationError
from django.utils import timezone


def validate_posting_date(value):
    if value > timezone.localdate():
        raise ValidationError('Дата проведения не может быть в будущем.')

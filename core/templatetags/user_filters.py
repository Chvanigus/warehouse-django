"""Кастомные теги."""
from django import template

register = template.Library()


@register.filter
def addclass(field, css):
    """Добавляет класс к элементу."""
    return field.as_widget(attrs={'class': css})


@register.filter
def to_str(value):
    """Конвертирует элемент в строку."""
    return str(value)

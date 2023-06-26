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


@register.filter
def round_float(value):
    """Округляет число до 2 десятичных знаков."""
    return round(value, 2)


@register.filter
def get_item(dictionary, key):
    """Возвращает значение по ключу."""
    return dictionary.get(key)

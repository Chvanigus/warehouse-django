"""Шаблонные фильтры для оформления полей Django."""
from django import template


register = template.Library()


@register.filter
def addclass(field, css):
    """Отображает связанное поле с указанным набором CSS-классов."""
    return field.as_widget(attrs={'class': css})

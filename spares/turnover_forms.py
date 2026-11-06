"""Фильтры отчёта об обороте запчастей."""

from django import forms

from .analytics_forms import AnalyticsFilterForm


class TurnoverFilterForm(AnalyticsFilterForm):
    """Дополняет период и складскую область буквальным поиском позиции."""

    q = forms.CharField(
        label='Запчасть или артикул',
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'type': 'search'}),
    )

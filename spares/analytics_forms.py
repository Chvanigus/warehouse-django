"""Фильтры периода и области аналитики склада."""

from calendar import monthrange
from datetime import date

from django import forms
from django.utils import timezone

from spares.analytics_data import month_index, shift_month
from spares.models import Company, Warehouses
from spares.report_forms import MonthField


DEFAULT_MONTHS = 6
MAX_MONTHS = 24


class AnalyticsFilterForm(forms.Form):
    """Проверяет включительный диапазон месяцев и необязательные фирму и склад."""

    start = MonthField(label='Начало периода', required=False)
    end = MonthField(label='Конец периода', required=False)
    company = forms.ModelChoiceField(
        queryset=Company.objects.order_by('name', 'pk'),
        label='Фирма',
        required=False,
        empty_label='Все фирмы',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    warehouse = forms.ModelChoiceField(
        queryset=Warehouses.objects.order_by('name', 'pk'),
        label='Склад',
        required=False,
        empty_label='Все склады',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    def __init__(self, *args, today=None, **kwargs):
        """Показывает по умолчанию текущий и пять предшествующих месяцев."""
        super().__init__(*args, **kwargs)
        self.today = today or timezone.localdate()
        self.initial.setdefault('start', shift_month(self.today, 1 - DEFAULT_MONTHS))
        self.initial.setdefault('end', shift_month(self.today, 0))

    def clean(self):
        """Ограничивает период 24 месяцами и сегодняшней датой включительно."""
        data = super().clean()
        if 'start' not in data or 'end' not in data:
            return data
        end = shift_month(data['end'] or self.today, 0)
        start = shift_month(data['start'], 0) if data['start'] else shift_month(end, 1 - DEFAULT_MONTHS)
        months = month_index(end) - month_index(start) + 1
        if months < 1:
            self.add_error('end', 'Конец периода должен быть не раньше начала.')
        elif month_index(end) > month_index(self.today):
            self.add_error('end', 'Конец периода не может быть в будущем.')
        elif months > MAX_MONTHS:
            self.add_error('end', f'Выберите не более {MAX_MONTHS} месяцев.')
        else:
            end_of_month = date(end.year, end.month, monthrange(end.year, end.month)[1])
            data['date_range'] = (start, min(self.today, end_of_month))
        return data

    def filters(self):
        """Возвращает проверенную область аналитики или начальный период без фильтров."""
        if not self.is_bound:
            return {'date_range': (self.initial['start'], self.today), 'company': None, 'warehouse': None}
        return self.cleaned_data if self.is_valid() else None

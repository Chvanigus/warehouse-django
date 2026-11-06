"""Формы отчётов по периодам и фильтры складских позиций."""

import calendar
from datetime import date
from re import escape

from django import forms
from django.db.models import Q

from spares.models import Company, Contractors, Machines, Trailers, Warehouses


RUSSIAN_MONTHS = (
    'январь', 'февраль', 'март', 'апрель', 'май', 'июнь',
    'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь',
)


class MonthField(forms.DateField):
    """Хранит выбранный месяц как дату для построения границ отчёта."""
    def __init__(self, **kwargs):
        """Настраивает формат месяца и соответствующий элемент HTML-формы."""
        super().__init__(
            input_formats=['%Y-%m'],
            widget=forms.DateInput(
                format='%Y-%m',
                attrs={'type': 'month', 'class': 'form-control', 'placeholder': 'ГГГГ-ММ'},
            ),
            **kwargs,
        )

    def to_python(self, value):
        # Bookmarks created by the previous date picker use «Январь 2025».
        """Преобразует месяц из современного или прежнего русскоязычного формата."""
        if isinstance(value, str):
            parts = value.casefold().split()
            if len(parts) == 2 and parts[0] in RUSSIAN_MONTHS:
                month = RUSSIAN_MONTHS.index(parts[0]) + 1
                value = f'{parts[1]}-{month:02}'
        return super().to_python(value)

    def bound_data(self, data, initial):
        """Нормализует значение для отображения, сохраняя ошибочный ввод."""
        value = super().bound_data(data, initial)
        try:
            month = self.to_python(value)
        except forms.ValidationError:
            return value
        return month.isoformat()[:7] if month else value


class ReportFilterForm(forms.Form):
    """Формирует включительный диапазон от начала первого до конца последнего месяца."""
    start_date = MonthField(label='Начало периода')
    end_date = MonthField(label='Конец периода')

    def add_prefix(self, field_name):
        """Сохраняет имена параметров URL с дефисами."""
        return super().add_prefix(field_name.replace('_', '-'))

    def clean(self):
        """Проверяет порядок месяцев и вычисляет последний день периода."""
        data = super().clean()
        start, end = data.get('start_date'), data.get('end_date')
        if start and end:
            if start > end:
                self.add_error('end_date', 'Конец периода должен быть не раньше начала.')
            else:
                data['date_range'] = (start, date(end.year, end.month, calendar.monthrange(end.year, end.month)[1]))
        return data


class MachineReportForm(ReportFilterForm):
    """Дополняет диапазон отчёта выбором техники."""
    field_order = ['machine']
    machine = forms.ModelChoiceField(
        queryset=Machines.objects.order_by('name', 'pk'),
        label='Техника',
        widget=forms.Select(attrs={'class': 'form-select warehouse-choice'}),
    )


class TrailersReportForm(ReportFilterForm):
    """Дополняет диапазон отчёта выбором прицепа."""
    field_order = ['trailers']
    trailers = forms.ModelChoiceField(
        queryset=Trailers.objects.order_by('name', 'pk'),
        label='Прицеп',
        widget=forms.Select(attrs={'class': 'form-select warehouse-choice'}),
    )


class ContractorsReportForm(ReportFilterForm):
    """Дополняет диапазон отчёта выбором контрагента."""
    field_order = ['contractors']
    contractors = forms.ModelChoiceField(
        queryset=Contractors.objects.order_by('name', 'pk'),
        label='Контрагент',
        widget=forms.Select(attrs={'class': 'form-select warehouse-choice'}),
    )


class AnnualReportFilterForm(forms.Form):
    """Ограничивает годовую сводку фирмой, складом и календарным годом."""

    year = forms.IntegerField(
        label='Год', min_value=1, max_value=9999, required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Все годы'}),
    )
    company = forms.ModelChoiceField(
        queryset=Company.objects.order_by('name', 'pk'), label='Фирма',
        required=False, empty_label='Все фирмы', widget=forms.Select(attrs={'class': 'form-select'}),
    )
    warehouse = forms.ModelChoiceField(
        queryset=Warehouses.objects.order_by('name', 'pk'), label='Склад',
        required=False, empty_label='Все склады', widget=forms.Select(attrs={'class': 'form-select'}),
    )


class StockGroupFilterForm(forms.Form):
    """Фильтрует остатки и правила пополнения по запчасти, складу и фирме."""
    q = forms.CharField(
        label='Запчасть или артикул',
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control', 'type': 'search', 'placeholder': 'Например, масляный фильтр или LF-9009',
        }),
    )
    warehouse = forms.ModelChoiceField(
        queryset=Warehouses.objects.order_by('name', 'pk'),
        label='Склад',
        required=False,
        empty_label='Все склады',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    company = forms.ModelChoiceField(
        queryset=Company.objects.order_by('name', 'pk'),
        label='Фирма',
        required=False,
        empty_label='Все фирмы',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    def filter_groups(self, queryset):
        """Применяет буквальный поиск по названию и артикулу, а также точные фильтры."""
        if not self.is_bound:
            return queryset
        if not self.is_valid():
            return queryset.none()

        filters = self.cleaned_data
        if filters['q']:
            pattern = escape(filters['q'])
            queryset = queryset.filter(Q(spare__name__iregex=pattern) | Q(spare__sku__iregex=pattern))
        if filters['warehouse']:
            queryset = queryset.filter(warehouse=filters['warehouse'])
        if filters['company']:
            queryset = queryset.filter(company=filters['company'])
        return queryset


class StockFilterForm(StockGroupFilterForm):
    """Дополняет фильтры остатков переключателем расхождений."""
    discrepancy = forms.BooleanField(
        label='Только расхождения',
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )


class StockMinimumFilterForm(StockGroupFilterForm):
    """Дополняет фильтры минимума переключателем дефицита."""
    low = forms.BooleanField(
        label='Только к пополнению',
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )

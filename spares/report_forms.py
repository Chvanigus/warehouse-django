"""Validated month and object filters for warehouse reports."""
import calendar
from datetime import date

from django import forms

from spares.models import Contractors, Machines, Trailers


RUSSIAN_MONTHS = (
    'январь', 'февраль', 'март', 'апрель', 'май', 'июнь',
    'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь',
)


class MonthField(forms.DateField):
    def __init__(self, **kwargs):
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
        if isinstance(value, str):
            parts = value.casefold().split()
            if len(parts) == 2 and parts[0] in RUSSIAN_MONTHS:
                month = RUSSIAN_MONTHS.index(parts[0]) + 1
                value = f'{parts[1]}-{month:02}'
        return super().to_python(value)

    def bound_data(self, data, initial):
        value = super().bound_data(data, initial)
        try:
            month = self.to_python(value)
        except forms.ValidationError:
            return value
        return month.isoformat()[:7] if month else value


class ReportFilterForm(forms.Form):
    start_date = MonthField(label='Начало периода')
    end_date = MonthField(label='Конец периода')

    def add_prefix(self, field_name):
        return super().add_prefix(field_name.replace('_', '-'))

    def clean(self):
        data = super().clean()
        start, end = data.get('start_date'), data.get('end_date')
        if start and end:
            if start > end:
                self.add_error('end_date', 'Конец периода должен быть не раньше начала.')
            else:
                data['date_range'] = (start, date(end.year, end.month, calendar.monthrange(end.year, end.month)[1]))
        return data


class MachineReportForm(ReportFilterForm):
    field_order = ['machine']
    machine = forms.ModelChoiceField(
        queryset=Machines.objects.order_by('name', 'pk'),
        label='Техника',
        widget=forms.Select(attrs={'class': 'form-select warehouse-choice'}),
    )


class TrailersReportForm(ReportFilterForm):
    field_order = ['trailers']
    trailers = forms.ModelChoiceField(
        queryset=Trailers.objects.order_by('name', 'pk'),
        label='Прицеп',
        widget=forms.Select(attrs={'class': 'form-select warehouse-choice'}),
    )


class ContractorsReportForm(ReportFilterForm):
    field_order = ['contractors']
    contractors = forms.ModelChoiceField(
        queryset=Contractors.objects.order_by('name', 'pk'),
        label='Контрагент',
        widget=forms.Select(attrs={'class': 'form-select warehouse-choice'}),
    )

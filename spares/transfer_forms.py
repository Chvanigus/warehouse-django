from decimal import Decimal

from django import forms
from django.utils import timezone

from .models import Stock, Warehouses
from .validators import validate_posting_date


class TransferForm(forms.Form):
    source = forms.ModelChoiceField(
        queryset=Stock.objects.filter(actual_balance__gt=0).select_related(
            'spare', 'warehouse', 'company', 'measure',
        ).order_by('spare__name', 'warehouse__name', 'company__name', 'price', 'pk'),
        label='Исходная позиция',
        help_text='Выберите запчасть с нужного склада. В списке указано доступное количество.',
    )
    destination = forms.ModelChoiceField(
        queryset=Warehouses.objects.order_by('name', 'pk'),
        label='Склад назначения',
    )
    quantity = forms.DecimalField(
        label='Перемещаемое количество', max_digits=15, decimal_places=2, min_value=Decimal('0.01'),
    )
    date = forms.DateField(
        label='Дата документа',
        initial=timezone.localdate,
        input_formats=['%Y-%m-%d'],
        validators=[validate_posting_date],
        widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
    )
    note = forms.CharField(
        label='Примечание', max_length=500, required=False, widget=forms.Textarea(attrs={'rows': 3}),
    )

    def clean(self):
        data = super().clean()
        source, destination, quantity = data.get('source'), data.get('destination'), data.get('quantity')
        if source is not None:
            if destination is not None and source.warehouse_id == destination.pk:
                self.add_error('destination', 'Выберите другой склад назначения.')
            if quantity is not None and quantity > source.actual_balance:
                self.add_error('quantity', 'Количество превышает доступный остаток.')
        return data

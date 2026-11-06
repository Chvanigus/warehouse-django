"""Формы составления, проверки и подтверждения инвентаризационных ведомостей."""

from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError

from .inventory_sheet_services import MAX_SHEET_LINES
from .models import Stock, Warehouses


class WarehouseSelectionForm(forms.Form):
    """Выбирает склад, для которого составляется ведомость."""
    warehouse = forms.ModelChoiceField(
        label='Склад', queryset=Warehouses.objects.order_by('name', 'pk'),
    )


class InventorySheetForm(WarehouseSelectionForm):
    """Передаёт склад, подписанный снимок остатков и примечание к ведомости."""
    warehouse = forms.ModelChoiceField(
        label='Склад', queryset=Warehouses.objects.all(), widget=forms.HiddenInput,
    )
    snapshot = forms.CharField(widget=forms.HiddenInput)
    note = forms.CharField(
        label='Примечание', max_length=500, required=False, widget=forms.Textarea(attrs={'rows': 2}),
    )


class InventorySheetLineForm(forms.Form):
    """Принимает позицию склада и фактическое количество по пересчёту."""
    stock = forms.ModelChoiceField(label='Позиция на складе', queryset=Stock.objects.none())
    counted_quantity = forms.DecimalField(
        label='Количество по факту', min_value=Decimal('0.00'), max_digits=15, decimal_places=2,
    )

    def __init__(self, *args, stocks, choices, **kwargs):
        """Ограничивает выбор позициями указанного склада и задаёт подписи вариантов."""
        super().__init__(*args, **kwargs)
        self.fields['stock'].queryset = stocks
        self.fields['stock'].choices = choices


class BaseInventorySheetFormSet(forms.BaseFormSet):
    """Проверяет уникальность позиций в составе ведомости."""
    def clean(self):
        """Отклоняет повторяющиеся позиции после проверки отдельных строк."""
        if any(self.errors):
            return
        stock_ids = [stock.pk for stock, _ in self.entries()]
        if len(stock_ids) != len(set(stock_ids)):
            raise ValidationError('Каждый остаток можно указать только один раз.')

    def entries(self):
        """Собирает заполненные и не удалённые строки для сохранения."""
        return [
            (form.cleaned_data['stock'], form.cleaned_data['counted_quantity'])
            for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get('DELETE')
        ]


InventorySheetFormSet = forms.formset_factory(
    InventorySheetLineForm, formset=BaseInventorySheetFormSet, extra=2, can_delete=True,
    min_num=1, max_num=MAX_SHEET_LINES, absolute_max=MAX_SHEET_LINES, validate_min=True, validate_max=True,
)


class InventorySheetReviewForm(forms.Form):
    """Принимает решение контролёра и его комментарий."""
    decision = forms.ChoiceField(choices=(('approve', 'Подтвердить'), ('reject', 'Отклонить')))
    note = forms.CharField(
        label='Комментарий контролёра', max_length=500, required=False, widget=forms.Textarea(attrs={'rows': 2}),
    )

    def clean(self):
        """Требует объяснение при отклонении ведомости."""
        data = super().clean()
        if data.get('decision') == 'reject' and not data.get('note'):
            self.add_error('note', 'Укажите причину отклонения.')
        return data

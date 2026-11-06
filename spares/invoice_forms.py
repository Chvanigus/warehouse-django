"""Проверка реквизитов, строк, загружаемых файлов и причин отмены накладных."""

from decimal import Decimal, ROUND_HALF_UP

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .invoice_services import MAX_INVOICE_LINES, validate_invoice_lines, validate_invoice_number
from .models import Company, Contractors, MeasureMeasurement, Receipt, Spares, Warehouses


class InvoiceHeaderForm(forms.Form):
    """Принимает номер, дату, фирму, поставщика и склад назначения накладной."""
    number = forms.CharField(label='Номер накладной', max_length=255)
    date = forms.DateField(
        label='Дата накладной', initial=timezone.localdate,
        widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
    )
    company = forms.ModelChoiceField(label='Фирма', queryset=Company.objects.order_by('name', 'pk'))
    contractor = forms.ModelChoiceField(label='Поставщик', queryset=Contractors.objects.order_by('name', 'pk'))
    warehouse = forms.ModelChoiceField(label='Склад', queryset=Warehouses.objects.order_by('name', 'pk'))

    def clean_date(self):
        """Запрещает проводить накладную будущей датой."""
        date = self.cleaned_data['date']
        if date > timezone.localdate():
            raise ValidationError('Нельзя провести накладную будущей датой.')
        return date

    def clean(self):
        """Проверяет уникальность номера для фирмы и поставщика."""
        data = super().clean()
        if all(data.get(field) for field in ('company', 'contractor', 'number')):
            try:
                validate_invoice_number(data['company'], data['contractor'], data['number'])
            except ValidationError as error:
                self.add_error('number', error)
        return data


class InvoiceUploadForm(InvoiceHeaderForm):
    """Дополняет реквизиты накладной загрузкой файла со строками."""
    workbook = forms.FileField(
        label='Файл с позициями', widget=forms.FileInput(attrs={'accept': '.xlsx'}),
    )


class InvoiceLineForm(forms.Form):
    """Проверяет запчасть, количество, цену и допустимую сумму строки."""
    spare = forms.ModelChoiceField(label='Запчасть', queryset=Spares.objects.order_by('name', 'pk'))
    measure = forms.ModelChoiceField(
        label='Единица измерения', queryset=MeasureMeasurement.objects.order_by('name', 'pk'), required=False,
    )
    quantity = forms.DecimalField(
        label='Количество', max_digits=15, decimal_places=2, min_value=Decimal('0.01'),
    )
    price = forms.DecimalField(
        label='Цена за единицу', max_digits=15, decimal_places=2, min_value=Decimal('0.00'),
    )

    def clean(self):
        """Проверяет, что округлённая стоимость строки помещается в поле модели."""
        data = super().clean()
        if 'price' in data and 'quantity' in data:
            amount = (data['price'] * data['quantity']).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            try:
                Receipt._meta.get_field('amount').clean(amount, None)
            except ValidationError:
                raise ValidationError('Сумма строки превышает допустимое значение.') from None
        return data


class BaseInvoiceLineFormSet(forms.BaseFormSet):
    """Проверяет набор строк перед проведением накладной."""
    def clean(self):
        """Проверяет совместимость заполненных строк, когда все отдельные формы валидны."""
        if any(self.errors):
            return
        validate_invoice_lines(self.posted_lines())

    def posted_lines(self):
        """Возвращает данные заполненных строк без помеченных к удалению."""
        return [
            {key: form.cleaned_data[key] for key in InvoiceLineForm.base_fields}
            for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get('DELETE')
        ]


InvoiceLineFormSet = forms.formset_factory(
    InvoiceLineForm, formset=BaseInvoiceLineFormSet, extra=3, can_delete=True,
    min_num=1, max_num=MAX_INVOICE_LINES, absolute_max=MAX_INVOICE_LINES,
    validate_min=True, validate_max=True,
)


class InvoiceCancelForm(forms.Form):
    """Требует текст причины для отмены накладной."""
    reason = forms.CharField(
        label='Причина отмены', max_length=500, widget=forms.Textarea(attrs={'rows': 3}),
    )

from django import forms
from django_select2.forms import Select2Widget

from .models import WriteOff, Stock, MachineWorker, Spares, Receipt


class WriteOffForm(forms.ModelForm):
    spares_list = forms.ModelChoiceField(
        queryset=Stock.objects.all(),
        label='Наименование',
        widget=Select2Widget()
    )
    machine_list = forms.ModelChoiceField(
        queryset=MachineWorker.objects.all(),
        label='Водитель | ТС',
        widget=Select2Widget()
    )

    def save(self, commit=True):
        instance = super().save(commit=False)

        instance.spare = self.cleaned_data['spares_list'].spare
        instance.warehouse = self.cleaned_data['spares_list'].warehouse
        instance.price = self.cleaned_data['spares_list'].price
        instance.worker = self.cleaned_data['machine_list'].worker
        instance.trailer = self.cleaned_data['machine_list'].trailer
        instance.machine = self.cleaned_data['machine_list'].machine
        instance.company = self.cleaned_data['spares_list'].company
        instance.measure = self.cleaned_data['spares_list'].measure

        if commit:
            instance.save()
        return instance

    def clean_quantity(self):
        actual_balance = self.cleaned_data['spares_list'].actual_balance
        quantity = self.cleaned_data['quantity']
        if quantity > actual_balance:
            raise forms.ValidationError('Количество списываемых запчастей превышает доступный баланс.')

        return quantity

    class Meta:
        model = WriteOff
        fields = ['spares_list', 'date', 'quantity']


class ReceiptForm(forms.ModelForm):
    spares_list = forms.ModelChoiceField(
        queryset=Spares.objects.all(),
        label='Наименование',
        widget=Select2Widget(),
    )

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.spare = self.cleaned_data['spares_list']

        if commit:
            instance.save()
        else:
            return instance

    class Meta:
        model = Receipt
        fields = [
            'spares_list',
            'measure',
            'company',
            'date',
            'warehouse',
            'quantity',
            'price',
            'invoice_number',
            'contractor'
        ]
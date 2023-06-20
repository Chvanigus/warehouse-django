from django import forms
from easy_select2 import Select2Mixin
from django_select2.forms import Select2Widget

from .models import WriteOff, Stock, MachineWorker


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
        print(self.cleaned_data['spares_list'].pk)

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


class SpareSelectWidget(Select2Mixin, forms.Select):
    pass

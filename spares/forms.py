from django import forms
from .models import WriteOff, Stock, MachineWorker


class WriteOffForm(forms.ModelForm):
    spares_list = forms.ModelChoiceField(
        queryset=Stock.objects.all(),
        label='Наименование'
    )
    machine_list = forms.ModelChoiceField(
        queryset=MachineWorker.objects.all(),
        label='Техника - Водитель'
    )

    def save(self, commit=True):
        instance = super().save(commit=False)

        instance.spare = self.cleaned_data['spares_list'].spare
        instance.warehouse = self.cleaned_data['spares_list'].warehouse
        instance.price = self.cleaned_data['spares_list'].price
        instance.worker = self.cleaned_data['machine_list'].worker
        instance.machine = self.cleaned_data['machine_list'].machine

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
        fields = ['spares_list', 'company', 'date', 'quantity']

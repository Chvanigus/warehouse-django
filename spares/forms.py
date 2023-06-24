from django import forms
from django_select2.forms import Select2Widget

from .models import WriteOff, Stock, MachineWorker, Receipt, Machines, Trailers, Contractors


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
        if self.cleaned_data.get('spares_list') and self.cleaned_data.get('machine_list'):
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
        else:
            raise forms.ValidationError('Вы не заполнили все поля.')

    def clean_quantity(self):
        if self.cleaned_data.get('spares_list'):
            actual_balance = self.cleaned_data['spares_list'].actual_balance
            quantity = self.cleaned_data['quantity']
            if quantity > actual_balance:
                raise forms.ValidationError('Количество списываемых запчастей превышает доступный баланс.')

            return quantity
        else:
            raise forms.ValidationError('Вы не заполнили все поля.')

    class Meta:
        model = WriteOff
        fields = ['spares_list', 'date', 'quantity']


class ReceiptForm(forms.ModelForm):
    class Meta:
        model = Receipt
        fields = [
            'spare',
            'measure',
            'company',
            'date',
            'warehouse',
            'quantity',
            'price',
            'invoice_number',
            'contractor'
        ]


class MachineReportForm(forms.Form):
    machine = forms.ModelChoiceField(
        queryset=Machines.objects.all(),
        required=True,
        label='Техника',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )


class TrailersReportForm(forms.Form):
    trailers = forms.ModelChoiceField(
        queryset=Trailers.objects.all(),
        required=True,
        label='Прицеп',
        widget=forms.Select(attrs={'class': 'form-control'})
    )


class ContractorsReportForm(forms.Form):
    contractors = forms.ModelChoiceField(
        queryset=Contractors.objects.all(),
        required=True,
        label='Контрагент',
        widget=forms.Select(attrs={'class': 'form-control'})
    )

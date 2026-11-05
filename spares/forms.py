from django import forms

from .models import MachineWorker, Receipt, Stock, WriteOff


class ReceiptForm(forms.ModelForm):
    class Meta:
        model = Receipt
        fields = (
            'spare', 'measure', 'company', 'date', 'warehouse', 'quantity',
            'price', 'invoice_number', 'contractor',
        )
        widgets = {'date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'})}


class StockForm(forms.ModelForm):
    identity_fields = ('spare', 'warehouse', 'company', 'measure', 'price')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance._state.adding:
            for name in self.identity_fields:
                self.fields[name].disabled = True

    class Meta:
        model = Stock
        fields = (
            'spare', 'warehouse', 'company', 'measure', 'price',
            'actual_balance', 'plan', 'inventory',
        )


class WriteOffForm(forms.ModelForm):
    spares_list = forms.ModelChoiceField(
        queryset=Stock.objects.select_related('spare', 'warehouse', 'measure', 'company').order_by(
            'spare__name', 'warehouse__name', 'company__name', 'price', 'pk',
        ),
        label='Остаток на складе',
        help_text='Доступное количество указано в строке остатка.',
        widget=forms.Select(attrs={'class': 'warehouse-choice'}),
    )
    machine_list = forms.ModelChoiceField(
        queryset=MachineWorker.objects.select_related('worker', 'machine', 'trailer').order_by(
            'worker__name', 'machine__name', 'trailer__name', 'pk',
        ),
        label='Работник, техника и прицеп',
        help_text='Назначения создаются в справочнике «Водители-транспорт-прицепы».',
        widget=forms.Select(attrs={'class': 'warehouse-choice'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance._state.adding:
            return

        self.initial.setdefault('spares_list', Stock.matching(self.instance).order_by('pk').first())
        assignment = self.fields['machine_list'].queryset.filter(
            worker_id=self.instance.worker_id,
            machine_id=self.instance.machine_id,
            trailer_id=self.instance.trailer_id,
        ).first()
        self.initial.setdefault('machine_list', assignment)
        if assignment is None:
            # Состав техники мог измениться после списания.
            field = self.fields['machine_list']
            field.required = False
            assignment_parts = (self.instance.worker, self.instance.machine, self.instance.trailer)
            label = ' | '.join(str(part) for part in assignment_parts if part is not None)
            field.empty_label = f'Сохранить прежнее назначение: {label}'

    def clean(self):
        data = super().clean()
        stock = data.get('spares_list')
        if stock is not None:
            self.instance.spare_id = stock.spare_id
            self.instance.warehouse_id = stock.warehouse_id
            self.instance.company_id = stock.company_id
            self.instance.measure_id = stock.measure_id
            self.instance.price = stock.price

        assignment = data.get('machine_list')
        if assignment is not None:
            self.instance.worker_id = assignment.worker_id
            self.instance.machine_id = assignment.machine_id
            self.instance.trailer_id = assignment.trailer_id
        return data

    class Meta:
        model = WriteOff
        fields = ('spares_list', 'machine_list', 'date', 'quantity')
        widgets = {'date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'})}

"""Формы складских операций, ручного ввода остатков и фильтрации журналов."""

from re import escape

from django import forms
from django.db.models import Q
from django.forms.models import ModelChoiceIteratorValue

from .models import MachineWorker, Receipt, Stock, WriteOff


class ReceiptForm(forms.ModelForm):
    """Принимает реквизиты и количество простой строки прихода."""
    class Meta:
        """Определяет модель и редактируемые поля прихода."""
        model = Receipt
        fields = (
            'spare', 'measure', 'company', 'date', 'warehouse', 'quantity',
            'price', 'invoice_number', 'contractor',
        )
        widgets = {'date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'})}


class StockForm(forms.ModelForm):
    """Позволяет вводить новый остаток, сохраняя ключ существующей позиции."""
    identity_fields = ('spare', 'warehouse', 'company', 'measure', 'price')

    def __init__(self, *args, **kwargs):
        """Закрывает редактирование полей ключа для уже сохранённой позиции."""
        super().__init__(*args, **kwargs)
        if not self.instance._state.adding:
            for name in self.identity_fields:
                self.fields[name].disabled = True

    class Meta:
        """Определяет поля складской позиции и ручного остатка."""
        model = Stock
        fields = (
            'spare', 'warehouse', 'company', 'measure', 'price',
            'actual_balance', 'plan',
        )


class WriteOffForm(forms.ModelForm):
    """Связывает списание с существующим остатком и назначением техники."""
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
        """Подставляет исходную позицию и назначение при открытии записи."""
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
        """Переносит реквизиты выбранного остатка и назначения в модель списания."""
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
        """Определяет поля выбора остатка, назначения, даты и количества."""
        model = WriteOff
        fields = ('spares_list', 'machine_list', 'date', 'quantity')
        widgets = {'date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'})}


class OperationReceiptForm(ReceiptForm):
    """Уточняет подписи полей прихода в рабочем интерфейсе."""
    class Meta(ReceiptForm.Meta):
        """Переопределяет подписи запчасти, единицы измерения и цены."""
        labels = {'spare': 'Запчасть', 'measure': 'Единица измерения', 'price': 'Цена за единицу'}


class StockChoiceSelect(forms.Select):
    """Передаёт доступное количество и цену в данных варианта выбора."""

    original_stock_id = None
    original_quantity = 0

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        """Добавляет числовые значения к варианту, сохраняя подпись для пользователя."""
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if isinstance(value, ModelChoiceIteratorValue):
            stock = value.instance
            available = stock.actual_balance
            if stock.pk == self.original_stock_id:
                available += self.original_quantity
            option['attrs'].update({
                'data-balance': format(stock.actual_balance, 'f'),
                'data-available': format(available, 'f'),
                'data-price': format(stock.price, 'f'),
                'data-measure': str(stock.measure) if stock.measure else '',
            })
        return option


class OperationWriteOffForm(WriteOffForm):
    """Настраивает выбор остатка для предпросмотра списания."""
    def __init__(self, *args, **kwargs):
        """Подключает виджет с числовыми данными и учитывает прежнее списание."""
        super().__init__(*args, **kwargs)
        field = self.fields['spares_list']
        widget = StockChoiceSelect()
        widget.choices = field.choices
        field.widget = widget
        stock = self.initial.get('spares_list')
        if stock is not None and not self.instance._state.adding:
            widget.original_stock_id = stock.pk
            widget.original_quantity = self.instance.quantity


class JournalFilterForm(forms.Form):
    """Проверяет текст поиска и включительный диапазон дат журнала."""
    q = forms.CharField(
        label='Поиск',
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={'type': 'search', 'class': 'form-control'}),
    )
    date_from = forms.DateField(
        label='Дата с',
        required=False,
        input_formats=['%Y-%m-%d'],
        widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date', 'class': 'form-control'}),
    )
    date_to = forms.DateField(
        label='Дата по',
        required=False,
        input_formats=['%Y-%m-%d'],
        widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date', 'class': 'form-control'}),
    )

    def __init__(self, *args, search_hint=None, **kwargs):
        """Устанавливает подсказку поиска для конкретного журнала."""
        super().__init__(*args, **kwargs)
        if search_hint is not None:
            self.fields['q'].widget.attrs['placeholder'] = search_hint

    def clean(self):
        """Проверяет, что дата окончания следует за датой начала или совпадает с ней."""
        data = super().clean()
        start, end = data.get('date_from'), data.get('date_to')
        if start and end and start > end:
            self.add_error('date_to', 'Конец периода должен быть не раньше начала.')
        return data

    def filter_queryset(self, queryset, *, search_fields, date_field='date', exact_fields=()):
        """Применяет буквальный поиск, включительные границы дат и точные фильтры."""
        if not self.is_bound:
            return queryset
        if not self.is_valid():
            return queryset.none()

        data = self.cleaned_data
        query = data.get('q')
        if query:
            # iregex ищет кириллицу без учёта регистра, а escape сохраняет буквальный поиск.
            pattern = escape(query)
            search = Q()
            for field in search_fields:
                search |= Q(**{f'{field}__iregex': pattern})
            queryset = queryset.filter(search)
        conditions = {
            lookup: data[field]
            for field, lookup in (('date_from', f'{date_field}__gte'), ('date_to', f'{date_field}__lte'), *exact_fields)
            if data[field]
        }
        return queryset.filter(**conditions) if conditions else queryset


class StockJournalFilterForm(JournalFilterForm):
    """Дополняет фильтры журнала точным идентификатором складской позиции."""
    stock = forms.IntegerField(
        label='Позиция', required=False, min_value=1, max_value=2**63 - 1, widget=forms.HiddenInput,
    )

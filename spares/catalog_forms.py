"""Формы ручного ввода остатков и проверка их версии перед изменением."""

from django import forms
from django.core import signing

from .forms import StockForm
from .stock_adjustments import stock_version

STOCK_REVISION_SALT = 'spares.stock.correction'


def validate_stock_version(token, expected):
    """Проверяет подпись и совпадение снимка остатка с текущим состоянием."""
    try:
        revision = signing.loads(token, salt=STOCK_REVISION_SALT)
    except signing.BadSignature:
        revision = None
    if revision != expected:
        raise forms.ValidationError(
            'Остаток изменился после открытия формы. Откройте актуальную запись и повторите операцию.',
        )
    return token


class ManualStockForm(StockForm):
    """Проверяет причину ручного изменения количества на складе."""
    reason = forms.CharField(
        label='Причина корректировки',
        max_length=500,
        required=False,
        widget=forms.Textarea(attrs={'rows': 3}),
        help_text='Укажите причину, если меняете фактический остаток. Например, «Пересчёт по ведомости № 12».',
    )

    def __init__(self, *args, **kwargs):
        """Запоминает фактический остаток до заполнения формы."""
        super().__init__(*args, **kwargs)
        self.balance_before = self.instance.actual_balance

    def clean(self):
        """Требует причину, когда введённое количество отличается от исходного."""
        data = super().clean()
        balance = data.get('actual_balance')
        if balance is not None and balance != self.balance_before and not data.get('reason'):
            self.add_error('reason', 'Укажите причину изменения остатка.')
        return data


class StockCorrectionForm(ManualStockForm):
    """Защищает корректировку существующего остатка от устаревшей формы."""
    revision = forms.CharField(widget=forms.HiddenInput, required=False)

    def __init__(self, *args, **kwargs):
        """Подписывает текущее состояние остатка для скрытого поля формы."""
        super().__init__(*args, **kwargs)
        self.stock_revision = stock_version(self.instance)
        self.initial['revision'] = signing.dumps(self.stock_revision, salt=STOCK_REVISION_SALT)

    def clean_revision(self):
        """Отклоняет форму, если остаток изменился с момента открытия."""
        return validate_stock_version(self.cleaned_data['revision'], self.stock_revision)

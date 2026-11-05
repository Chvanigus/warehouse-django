from django import forms
from django.core import signing

from .forms import StockForm


class StockCorrectionForm(StockForm):
    revision = forms.CharField(widget=forms.HiddenInput, required=False)
    revision_salt = 'spares.stock.correction'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        stock = self.instance
        self.stock_revision = [
            stock.pk, str(stock.actual_balance), str(stock.input_quantity), str(stock.output_quantity),
            stock.plan, str(stock.inventory),
        ]
        self.initial['revision'] = signing.dumps(self.stock_revision, salt=self.revision_salt)

    def clean_revision(self):
        token = self.cleaned_data['revision']
        try:
            revision = signing.loads(token, salt=self.revision_salt)
        except signing.BadSignature:
            revision = None
        if revision != self.stock_revision:
            raise forms.ValidationError(
                'Остаток изменился после открытия формы. Откройте актуальную запись и повторите корректировку.',
            )
        return token

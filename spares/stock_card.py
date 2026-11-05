"""Read-only movement history for one exact stock position."""

from django import forms
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.paginator import Paginator
from django.db.models import BigIntegerField, DateTimeField, DecimalField, F, Q, Value
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.generic import TemplateView

from .forms import JournalFilterForm
from .models import Movement, Receipt, Stock, StockAdjustment, StockTransfer, WriteOff


POSTING_GROUPS = {
    'receipt': ('Приход', 'spares.view_receipt'),
    'writeoff': ('Расход', 'spares.view_writeoff'),
    'transfer': ('Перемещения', 'spares.view_stocktransfer'),
    'adjustment': ('Корректировки', 'spares.view_stockadjustment'),
}

EVENTS = {
    'receipt': ('Приход', 1, 'receipt'),
    'receipt_cancel': ('Отмена прихода', -1, 'receipt'),
    'writeoff': ('Расход', -1, 'writeoff'),
    'writeoff_cancel': ('Отмена расхода', 1, 'writeoff'),
    'transfer_in': ('Перемещение на склад', 1, 'transfer'),
    'transfer_in_cancel': ('Отмена входящего перемещения', -1, 'transfer'),
    'transfer_out': ('Перемещение со склада', -1, 'transfer'),
    'transfer_out_cancel': ('Отмена исходящего перемещения', 1, 'transfer'),
    'adjustment': ('Корректировка остатка', 1, 'adjustment'),
}


class StockCardFilterForm(JournalFilterForm):
    q = None
    kind = forms.ChoiceField(
        label='Операция', required=False, widget=forms.Select(attrs={'class': 'form-select'}),
    )
    field_order = ('kind', 'date_from', 'date_to')

    def __init__(self, *args, allowed_groups, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [('', 'Все доступные операции')]
        choices.extend((group, POSTING_GROUPS[group][0]) for group in allowed_groups)
        if set(allowed_groups) - {'adjustment'}:
            choices.append(('cancel', 'Отмены документов'))
        self.fields['kind'].choices = choices


def _event_rows(queryset, kind, filters, *, timestamp=None, details=None):
    group = EVENTS[kind][2]
    if timestamp is not None:
        queryset = queryset.filter(**{f'{timestamp}__isnull': False})
    queryset = queryset.order_by().annotate(
        event_date=TruncDate(timestamp) if timestamp else F('date'),
        event_time=F(timestamp) if timestamp else Value(None, output_field=DateTimeField()),
        event_kind=Value(kind),
        event_pk=F('pk'),
        invoice_pk=F('invoice_id') if group == 'receipt' else Value(None, output_field=BigIntegerField()),
        movement_amount=F('after') if group == 'adjustment' else F('quantity'),
        previous_amount=F('before') if group == 'adjustment' else Value(0, output_field=DecimalField()),
        details=F(details) if details else Value(''),
    )
    if filters.get('date_from'):
        queryset = queryset.filter(event_date__gte=filters['date_from'])
    if filters.get('date_to'):
        queryset = queryset.filter(event_date__lte=filters['date_to'])
    return queryset.values(
        'event_date', 'event_time', 'event_kind', 'event_pk', 'invoice_pk',
        'movement_amount', 'previous_amount', 'details',
    )


def _movement_rows(stock, allowed_groups, filters):
    key = Stock.key_for(stock)
    transfer_key = {field: value for field, value in key.items() if field != 'warehouse_id'}
    sources = {
        'receipt': [(Receipt.objects.filter(**key), 'receipt', 'invoice_number')],
        'writeoff': [(WriteOff.objects.filter(**key), 'writeoff', 'worker__name')],
        'transfer': [
            (StockTransfer.objects.filter(to_warehouse_id=stock.warehouse_id, **transfer_key),
             'transfer_in', 'from_warehouse__name'),
            (StockTransfer.objects.filter(from_warehouse_id=stock.warehouse_id, **transfer_key),
             'transfer_out', 'to_warehouse__name'),
        ],
        'adjustment': [(StockAdjustment.objects.filter(stock=stock), 'adjustment', 'reason')],
    }
    rows = []
    selected = filters.get('kind')
    for group in allowed_groups:
        for source, kind, details in sources[group]:
            if selected in (None, '', group):
                timestamp = 'created_at' if group == 'adjustment' else None
                rows.append(_event_rows(source, kind, filters, timestamp=timestamp, details=details))
            if group != 'adjustment' and selected in (None, '', 'cancel'):
                rows.append(_event_rows(
                    source, f'{kind}_cancel', filters, timestamp='cancelled_at', details='cancellation_reason',
                ))
    if not rows:
        return []
    return rows[0].union(*rows[1:], all=True).order_by('-event_date', '-event_time', 'event_kind', '-event_pk')


def _entry_data(row, stock):
    label, sign, group = EVENTS[row['event_kind']]
    pk = row['event_pk']
    if row['invoice_pk']:
        url = reverse('invoices:detail', args=[row['invoice_pk']])
    elif group == 'transfer':
        url = reverse('transfers:detail', args=[pk])
    elif group == 'adjustment':
        url = reverse('spares:stock_adjustments', query={'stock': stock.pk, 'entry': pk})
    else:
        journal = 'operations:receipts' if group == 'receipt' else 'operations:writeoffs'
        url = reverse(journal, query={'entry': pk})
    return {
        **row,
        'label': label,
        'delta': sign * (row['movement_amount'] - row['previous_amount']),
        'url': url,
    }


class StockCardView(LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    permission_required = 'spares.view_stock'
    template_name = 'spares/stock_card.html'
    paginate_by = 30

    def get_context_data(self, **kwargs):
        stock = get_object_or_404(
            Stock.objects.select_related('spare', 'company', 'warehouse', 'measure'),
            pk=self.kwargs['pk'],
        )
        allowed_groups = [
            group for group, (_, permission) in POSTING_GROUPS.items()
            if self.request.user.has_perm(permission)
        ]
        filters = StockCardFilterForm(self.request.GET or None, allowed_groups=allowed_groups)
        rows = []
        if not filters.is_bound or filters.is_valid():
            rows = _movement_rows(stock, allowed_groups, getattr(filters, 'cleaned_data', {}))
        page = Paginator(rows, self.paginate_by).get_page(self.request.GET.get('page'))
        legacy_url = ''
        if self.request.user.has_perm('spares.view_movement') and Movement.objects.filter(
            Q(from_warehouse_id=stock.warehouse_id) | Q(to_warehouse_id=stock.warehouse_id),
            spare_id=stock.spare_id,
        ).exists():
            legacy_url = reverse('operations:movements', query={'q': stock.spare.name[:100]})
        return super().get_context_data(
            stock=stock, filters=filters, page_obj=page, legacy_url=legacy_url,
            entries=[_entry_data(row, stock) for row in page], **kwargs,
        )

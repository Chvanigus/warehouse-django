"""Расчёт оборота по запчастям и единицам измерения за выбранный период."""

from re import escape

from django.db.models import Q, Sum

from .analytics_data import CENT, ZERO, period_operations
from .models import Receipt, WriteOff


def _totals(model, amount_field, filters):
    """Суммирует проведённые строки одного вида по запчасти и единице измерения."""
    start, end = filters['date_range']
    operations = period_operations(model, start, end, filters['company'], filters['warehouse'])
    if query := filters.get('q'):
        pattern = escape(query)
        operations = operations.filter(Q(spare__name__iregex=pattern) | Q(spare__sku__iregex=pattern))
    return operations.values(
        'spare_id', 'spare__name', 'spare__sku', 'measure_id', 'measure__name',
    ).annotate(quantity=Sum('quantity'), amount=Sum(amount_field)).order_by()


def _sort_key(row):
    """Сортирует строки по названиям, оставляя однозначный порядок при совпадениях."""
    return (row['name'].casefold(), row['spare_id'], (row['measure'] or '').casefold(), row['measure_id'] or 0)


def turnover_rows(filters):
    """Объединяет приход и расход по одному ключу, заполняя отсутствующую сторону нулями."""
    rows = {}
    for model, amount_field, kind in ((Receipt, 'amount', 'receipts'), (WriteOff, 'total_amount', 'writeoffs')):
        for total in _totals(model, amount_field, filters):
            key = (total['spare_id'], total['measure_id'])
            row = rows.setdefault(key, {
                'spare_id': total['spare_id'],
                'measure_id': total['measure_id'],
                'name': total['spare__name'],
                'sku': total['spare__sku'],
                'measure': total['measure__name'],
                'receipts_quantity': ZERO,
                'receipts_amount': ZERO,
                'writeoffs_quantity': ZERO,
                'writeoffs_amount': ZERO,
            })
            row[f'{kind}_quantity'] = total['quantity'].quantize(CENT)
            row[f'{kind}_amount'] = total['amount'].quantize(CENT)
    return sorted(rows.values(), key=_sort_key)

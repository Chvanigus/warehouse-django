"""Постраничный расчёт оборота по запчастям и единицам измерения."""

from itertools import islice
from re import escape

from django.db.models import Q, Sum, Value
from django.db.models.functions import Coalesce, Lower

from .analytics_data import CENT, ZERO, period_operations
from .models import Receipt, WriteOff


POSITION_FIELDS = ('spare_id', 'spare__name', 'spare__sku', 'measure_id', 'measure__name')
EXPORT_BATCH_SIZE = 250


class TurnoverReport:
    """Описывает одну выборку, общую для итогов, страницы и выгрузки."""

    def __init__(self, filters):
        """Ограничивает обе стороны оборота проверенным периодом, областью и поиском."""
        start, end = filters['date_range']
        self.sources = []
        for model, amount_field, prefix in ((Receipt, 'amount', 'receipts'), (WriteOff, 'total_amount', 'writeoffs')):
            operations = period_operations(model, start, end, filters['company'], filters['warehouse'])
            if query := filters.get('q'):
                pattern = escape(query)
                operations = operations.filter(Q(spare__name__iregex=pattern) | Q(spare__sku__iregex=pattern))
            self.sources.append((operations, amount_field, prefix))

    def positions(self):
        """Объединяет ключи в базе данных, чтобы ограничить их страницей до расчёта строк."""
        receipts, writeoffs = (
            operations.values(*POSITION_FIELDS).annotate(
                name_order=Lower('spare__name'), measure_order=Coalesce(Lower('measure__name'), Value('')),
            ).order_by()
            for operations, _, _ in self.sources
        )
        return receipts.union(writeoffs).order_by('name_order', 'spare_id', 'measure_order', 'measure_id')

    def totals(self):
        """Считает денежные итоги всей выборки независимо от текущей страницы."""
        return {
            f'{prefix}_total': operations.aggregate(total=Sum(amount_field, default=ZERO))['total'].quantize(CENT)
            for operations, amount_field, prefix in self.sources
        }

    def rows(self, positions):
        """Считает приход и расход только для переданных пар запчасти и единицы."""
        rows = {
            (position['spare_id'], position['measure_id']): {
                'spare_id': position['spare_id'],
                'measure_id': position['measure_id'],
                'name': position['spare__name'],
                'sku': position['spare__sku'],
                'measure': position['measure__name'],
                'receipts_quantity': ZERO,
                'receipts_amount': ZERO,
                'writeoffs_quantity': ZERO,
                'writeoffs_amount': ZERO,
            }
            for position in positions
        }
        if not rows:
            return []

        parts_by_measure = {}
        for part, measure in rows:
            parts_by_measure.setdefault(measure, []).append(part)
        selected = Q()
        for measure, parts in parts_by_measure.items():
            selected |= Q(spare_id__in=parts, measure_id=measure)
        for operations, amount_field, prefix in self.sources:
            totals = operations.filter(selected).values('spare_id', 'measure_id').annotate(
                quantity=Sum('quantity'), amount=Sum(amount_field),
            ).order_by()
            for total in totals:
                row = rows[total['spare_id'], total['measure_id']]
                row[f'{prefix}_quantity'] = total['quantity'].quantize(CENT)
                row[f'{prefix}_amount'] = total['amount'].quantize(CENT)
        return list(rows.values())

    def export_rows(self):
        """Читает полную выборку порциями без накопления всех агрегатов в памяти."""
        positions = self.positions().iterator(chunk_size=EXPORT_BATCH_SIZE)
        while batch := list(islice(positions, EXPORT_BATCH_SIZE)):
            yield from self.rows(batch)

"""Агрегация проведённых операций и текущих складских остатков для аналитики."""

from datetime import date
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth

from spares.models import Receipt, Stock, WriteOff
from spares.threshold_models import StockMinimum


ZERO = Decimal('0.00')
CENT = Decimal('0.01')
AXIS_STEPS = (1, 2, Decimal('2.5'), 3, 4, 5, 6, 8, 10)
MONTH_LABELS = ('Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн', 'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек')
POSITION_COUNTS = {
    'positions': Count('pk'),
    'in_stock': Count('pk', filter=Q(actual_balance__gt=0)),
    'unavailable': Count('pk', filter=Q(actual_balance__lte=0)),
    'discrepancies': Count('pk', filter=Q(inventory__isnull=False, discrepancy=True)),
}


def month_index(day):
    """Преобразует месяц в порядковый номер для сравнения и сдвига границ."""
    return (day.year - 1) * 12 + day.month - 1


def shift_month(day, offset):
    """Возвращает первое число смещённого месяца, не выходя за нижнюю границу календаря."""
    year, month = divmod(max(0, month_index(day) + offset), 12)
    return date(year + 1, month + 1, 1)


def _scope(queryset, company, warehouse):
    """Ограничивает запрос выбранной фирмой и складом, если фильтры заданы."""
    if company is not None:
        queryset = queryset.filter(company=company)
    if warehouse is not None:
        queryset = queryset.filter(warehouse=warehouse)
    return queryset


def period_operations(model, start, end, company, warehouse):
    """Отбирает неотменённые строки документов в заданном периоде и области."""
    return _scope(model.objects.filter(date__range=(start, end), cancelled_at__isnull=True), company, warehouse)


def _month_totals(operations, amount_field):
    """Считает суммы и число строк документов по календарным месяцам."""
    rows = operations.annotate(month=TruncMonth('date')).values('month').annotate(
        amount=Sum(amount_field), count=Count('pk'),
    ).order_by()
    return {
        row['month']: {'amount': row['amount'].quantize(CENT), 'count': row['count']}
        for row in rows
    }


def _summary(series):
    """Сворачивает месячные суммы и число строк, сохраняя признак недоступных данных."""
    if series is None:
        return None
    return {
        'amount': sum((month['amount'] for month in series.values()), ZERO),
        'count': sum(month['count'] for month in series.values()),
    }


def _height(value, maximum):
    """Возвращает долю от масштаба в процентах для серверной отрисовки."""
    if value <= 0 or maximum <= 0:
        return ZERO
    return (Decimal(value) * 100 / maximum).quantize(CENT)


def _trend_scale(peak):
    """Выбирает четыре читаемых шага оси сумм с запасом над максимальным значением."""
    if peak <= 0:
        return ZERO, []
    rough_step = peak / 4
    base = Decimal(10) ** rough_step.adjusted()
    step = max(CENT, next(base * multiple for multiple in AXIS_STEPS if base * multiple >= rough_step))
    return step * 4, [{'amount': step * index, 'height': index * 25} for index in range(5)]


def _month_point(month, series, maximum):
    """Создаёт точку ряда, заполняя отсутствующий месяц нулём."""
    if series is None:
        return None
    point = series.get(month, {'amount': ZERO, 'count': 0})
    return {**point, 'height': _height(point['amount'], maximum)}


def _trend(start, end, receipts, writeoffs):
    """Строит одинаковую ось для доступных рядов и заполняет пропуски месяцев."""
    peak = max(
        (point['amount'] for series in (receipts, writeoffs) if series is not None for point in series.values()),
        default=ZERO,
    )
    maximum, ticks = _trend_scale(peak)
    months = [
        shift_month(start, offset) for offset in range(month_index(end) - month_index(start) + 1)
    ]
    trend = [{
        'month': month,
        'label': f'{MONTH_LABELS[month.month - 1]} {month.year}',
        'receipts': _month_point(month, receipts, maximum),
        'writeoffs': _month_point(month, writeoffs, maximum),
    } for month in months]
    return trend, ticks, maximum


def _top_writeoffs(operations):
    """Ранжирует списания по сумме, оставляя разные единицы измерения в отдельных строках."""
    rows = list(operations.values(
        'spare_id', 'spare__name', 'spare__sku', 'measure_id', 'measure__name',
    ).annotate(amount=Sum('total_amount'), quantity=Sum('quantity')).order_by(
        '-amount', 'spare__name', 'spare_id', 'measure__name', 'measure_id',
    )[:5])
    maximum = rows[0]['amount'].quantize(CENT) if rows else ZERO
    return [{
        'spare_id': row['spare_id'],
        'measure_id': row['measure_id'],
        'name': row['spare__name'],
        'sku': row['spare__sku'],
        'measure': row['measure__name'],
        'amount': row['amount'].quantize(CENT),
        'quantity': row['quantity'].quantize(CENT),
        'height': _height(row['amount'].quantize(CENT), maximum),
    } for row in rows]


def _stock_snapshot(company, warehouse, show_minimums):
    """Считает текущие складские позиции и при наличии права позиции к пополнению."""
    positions = _scope(Stock.objects.all(), company, warehouse)
    rows = list(positions.values('warehouse_id', 'warehouse__name').annotate(
        **POSITION_COUNTS,
    ).order_by('-positions', 'warehouse__name', 'warehouse_id'))
    summary = {field: sum(row[field] for row in rows) for field in POSITION_COUNTS}
    summary['below_minimum'] = (
        _scope(StockMinimum.objects.with_available(), company, warehouse).below_minimum().count()
        if show_minimums else None
    )
    maximum = rows[0]['positions'] if rows else 0
    warehouses = [{
        'id': row['warehouse_id'],
        'name': row['warehouse__name'],
        'positions': row['positions'],
        'in_stock': row['in_stock'],
        'unavailable': row['unavailable'],
        'discrepancies': row['discrepancies'],
        'height': _height(row['positions'], maximum),
        'in_stock_height': _height(row['in_stock'], maximum),
        'unavailable_height': _height(row['unavailable'], maximum),
    } for row in rows]
    return summary, warehouses


def build_analytics(start, end, *, company, warehouse, show_receipts, show_writeoffs, show_stock, show_minimums):
    """Собирает только разрешённые разделы для проверенного периода и выбранной области."""
    receipts = None
    writeoffs = None
    top_writeoffs = []
    if show_receipts:
        receipts = _month_totals(period_operations(Receipt, start, end, company, warehouse), 'amount')
    if show_writeoffs:
        operations = period_operations(WriteOff, start, end, company, warehouse)
        writeoffs = _month_totals(operations, 'total_amount')
        top_writeoffs = _top_writeoffs(operations)
    trend, trend_ticks, trend_max = _trend(start, end, receipts, writeoffs) if (
        show_receipts or show_writeoffs
    ) else ([], [], ZERO)
    stock, warehouses = _stock_snapshot(company, warehouse, show_minimums) if show_stock else (None, [])
    return {
        'period': {'start': start, 'end': end},
        'receipts': _summary(receipts),
        'writeoffs': _summary(writeoffs),
        'trend': trend,
        'trend_ticks': trend_ticks,
        'trend_max': trend_max,
        'top_writeoffs': top_writeoffs,
        'stock': stock,
        'warehouses': warehouses,
    }

"""Представление сохранённых реквизитов заявки в читаемом виде."""

from datetime import date

from .models import Company, Contractors, Machines, MeasureMeasurement, Spares, Stock, Trailers, Warehouses, Workers
from .request_models import StockRequest


def _object_label(model, value):
    """Возвращает название справочной записи или её номер, если запись удалена."""
    if value is None or value == '':
        return '—'
    obj = model.objects.filter(pk=value).first()
    return str(obj) if obj is not None else f'№ {value}'


def _date_label(value):
    """Показывает дату документа в российском формате."""
    if not value:
        return '—'
    try:
        return date.fromisoformat(value).strftime('%d.%m.%Y')
    except (TypeError, ValueError):
        return value


def _receipt_fields(data, number_key):
    """Собирает реквизиты одиночного прихода или шапки накладной."""
    return [
        ('Дата документа', _date_label(data.get('date'))),
        ('Номер накладной', data.get(number_key) or '—'),
        ('Поставщик', _object_label(Contractors, data.get('contractor'))),
        ('Компания', _object_label(Company, data.get('company'))),
        ('Склад', _object_label(Warehouses, data.get('warehouse'))),
    ]


def _receipt_lines(lines):
    """Загружает названия запчастей и единиц одним запросом на справочник."""
    parts = Spares.objects.in_bulk({line['spare'] for line in lines if line.get('spare')})
    measures = MeasureMeasurement.objects.in_bulk({line['measure'] for line in lines if line.get('measure')})
    rows = []
    for line in lines:
        spare_id = line.get('spare')
        measure_id = line.get('measure')
        rows.append({
            'part': parts.get(spare_id, f'№ {spare_id}') if spare_id else '—',
            'measure': measures.get(measure_id, f'№ {measure_id}') if measure_id else '—',
            'quantity': line.get('quantity', '—'),
            'price': line.get('price', '—'),
        })
    return rows


def _stock_fields(pk):
    """Расшифровывает исходный остаток без подстановки его текущего количества."""
    if not pk:
        return []
    stock = Stock.objects.select_related('spare', 'warehouse', 'company', 'measure').filter(pk=pk).first()
    if stock is None:
        return [('Исходный остаток', f'№ {pk}')]
    return [
        ('Запчасть', stock.spare),
        ('Компания', stock.company),
        ('Исходный склад', stock.warehouse),
        ('Единица', stock.measure or '—'),
        ('Цена', stock.price),
    ]


def describe_request(stock_request):
    """Подготавливает реквизиты и строки заявки по сохранённому снимку."""
    data = stock_request.payload
    if stock_request.kind == StockRequest.Kind.RECEIPT:
        return _receipt_fields(data, 'invoice_number'), _receipt_lines([data])
    if stock_request.kind == StockRequest.Kind.RECEIPT_INVOICE:
        return _receipt_fields(data.get('header', {}), 'number'), _receipt_lines(data.get('lines', []))

    fields = [('Дата документа', _date_label(data.get('date'))), ('Количество', data.get('quantity', '—'))]
    if stock_request.kind == StockRequest.Kind.TRANSFER:
        fields.extend(_stock_fields(data.get('source')))
        fields.append(('Склад назначения', _object_label(Warehouses, data.get('destination'))))
        if data.get('note'):
            fields.append(('Примечание', data['note']))
    elif stock_request.kind == StockRequest.Kind.WRITEOFF:
        fields.extend(_stock_fields(data.get('spares_list')))
        assignment = data.get('assignment', {})
        for label, model, key in (('Работник', Workers, 'worker'), ('Техника', Machines, 'machine'), ('Прицеп', Trailers, 'trailer')):
            if assignment.get(key):
                fields.append((label, _object_label(model, assignment[key])))
    return fields, []

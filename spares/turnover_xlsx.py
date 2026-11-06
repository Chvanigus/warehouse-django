"""Выгрузка выбранного оборота и его параметров в XLSX."""

from io import BytesIO

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font

from .xlsx_cells import text_cell


HEADERS = ('Запчасть', 'Артикул', 'Единица', 'Приход, количество', 'Расход, количество', 'Приход, сумма', 'Расход, сумма')
WIDTHS = (34, 22, 16, 23, 23, 20, 20)


def turnover_workbook(rows, filters):
    """Формирует книгу со всеми строками оборота, числами и параметрами отбора."""
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet('Оборот')
    sheet.freeze_panes = 'A2'
    for column, width in zip('ABCDEFG', WIDTHS):
        sheet.column_dimensions[column].width = width
    header = [WriteOnlyCell(sheet, value=label) for label in HEADERS]
    for cell in header:
        cell.font = Font(bold=True)
    sheet.append(header)
    for row in rows:
        sheet.append([text_cell(sheet, row[field] or '') for field in ('name', 'sku', 'measure')] + [
            row['receipts_quantity'], row['writeoffs_quantity'], row['receipts_amount'], row['writeoffs_amount'],
        ])

    parameters = workbook.create_sheet('Параметры')
    parameters.column_dimensions['A'].width = 22
    parameters.column_dimensions['B'].width = 34
    start, end = filters['date_range']
    for label, value in (
        ('Начало периода', start.isoformat()),
        ('Конец периода', end.isoformat()),
        ('Фирма', str(filters['company']) if filters['company'] else 'Все фирмы'),
        ('Склад', str(filters['warehouse']) if filters['warehouse'] else 'Все склады'),
        ('Поиск', filters.get('q') or 'Все запчасти'),
    ):
        parameters.append([label, text_cell(parameters, value)])

    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    stream.seek(0)
    return stream

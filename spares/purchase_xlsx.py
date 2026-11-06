"""Выгрузка потребности в закупках по складам в формате XLSX."""

from io import BytesIO
from itertools import groupby
from operator import attrgetter

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font

from .xlsx_cells import INVALID_XML_TEXT, text_cell


HEADERS = ('Склад', 'Артикул', 'Запчасть', 'Фирма', 'Единица', 'На остатке', 'Минимум', 'К заказу')
WIDTHS = (27, 21, 38, 26, 14, 14, 14, 14)
SHEET_TITLE_TRANSLATION = str.maketrans({char: ' ' for char in '[]:*?/\\'})


def _new_sheet(workbook, title):
    """Создать лист с закреплённой строкой заголовков и шириной столбцов."""
    sheet = workbook.create_sheet(title)
    sheet.freeze_panes = 'A2'
    for column, width in zip('ABCDEFGH', WIDTHS):
        sheet.column_dimensions[column].width = width
    header = [WriteOnlyCell(sheet, value=value) for value in HEADERS]
    for cell in header:
        cell.font = Font(bold=True)
    sheet.append(header)
    return sheet


def _sheet_title(warehouse):
    """Собрать допустимое и уникальное имя листа из названия и номера склада."""
    name = INVALID_XML_TEXT.sub('', warehouse.name).translate(SHEET_TITLE_TRANSLATION).strip(" '")
    suffix = f' {warehouse.pk}'
    return (name[:31 - len(suffix)].rstrip() or 'Склад') + suffix


def make_purchase_workbook(shortages):
    """Сформировать книгу с отдельным листом для каждого склада."""
    workbook = Workbook(write_only=True)
    for warehouse, warehouse_rows in groupby(shortages, key=attrgetter('warehouse')):
        sheet = _new_sheet(workbook, _sheet_title(warehouse))
        for row in warehouse_rows:
            text_fields = (
                warehouse.name, row.spare.sku or '', row.spare.name,
                row.company.name, row.measure.name if row.measure else '',
            )
            sheet.append([text_cell(sheet, value) for value in text_fields] + [
                row.available, row.minimum, row.shortage,
            ])
    if not workbook.sheetnames:
        _new_sheet(workbook, 'Закупки')
    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    stream.seek(0)
    return stream

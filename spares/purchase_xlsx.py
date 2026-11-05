from io import BytesIO
from itertools import groupby
from operator import attrgetter
from re import compile

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font


HEADERS = ('Склад', 'Артикул', 'Запчасть', 'Фирма', 'Единица', 'На остатке', 'Минимум', 'К заказу')
WIDTHS = (27, 21, 38, 26, 14, 14, 14, 14)
INVALID_XML_TEXT = compile(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]')
SHEET_TITLE_TRANSLATION = str.maketrans({char: ' ' for char in '[]:*?/\\'})


def _new_sheet(workbook, title):
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
    name = INVALID_XML_TEXT.sub('', warehouse.name).translate(SHEET_TITLE_TRANSLATION).strip(" '")
    suffix = f' {warehouse.pk}'
    return (name[:31 - len(suffix)].rstrip() or 'Склад') + suffix


def _text_cell(sheet, value):
    cell = WriteOnlyCell(sheet, value=INVALID_XML_TEXT.sub('', value))
    cell.data_type = 's'
    return cell


def make_purchase_workbook(shortages):
    """Write ordered shortages, grouped into one sheet per warehouse."""
    workbook = Workbook(write_only=True)
    for warehouse, warehouse_rows in groupby(shortages, key=attrgetter('warehouse')):
        sheet = _new_sheet(workbook, _sheet_title(warehouse))
        for row in warehouse_rows:
            text_fields = (
                warehouse.name, row.spare.sku or '', row.spare.name,
                row.company.name, row.measure.name if row.measure else '',
            )
            sheet.append([_text_cell(sheet, value) for value in text_fields] + [
                row.available, row.minimum, row.shortage,
            ])
    if not workbook.sheetnames:
        _new_sheet(workbook, 'Закупки')
    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    stream.seek(0)
    return stream

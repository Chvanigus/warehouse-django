"""Безопасная запись пользовательских строк в ячейки XLSX."""

from re import compile

from openpyxl.cell import WriteOnlyCell


INVALID_XML_TEXT = compile(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]')


def text_cell(sheet, value):
    """Удаляет запрещённые символы XML и явно сохраняет значение как текст."""
    cell = WriteOnlyCell(sheet, value=INVALID_XML_TEXT.sub('', value))
    cell.data_type = 's'
    return cell

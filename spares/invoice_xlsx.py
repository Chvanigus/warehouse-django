"""Безопасное чтение и создание шаблона накладной в формате XLSX."""

from io import BytesIO
from pathlib import PurePosixPath
from re import fullmatch
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile, ZipFile

from defusedxml.ElementTree import iterparse
from defusedxml.common import DefusedXmlException
from django.core.exceptions import ValidationError
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.utils.exceptions import InvalidFileException

from .invoice_forms import InvoiceLineForm
from .invoice_services import MAX_INVOICE_LINES, validate_invoice_lines
from .models import MeasureMeasurement, Spares


HEADERS = ('Артикул', 'Запчасть', 'Единица', 'Количество', 'Цена')
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_EXPANDED_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 128


def _inspect_xml(xml, *, worksheet):
    """Проверить содержимое XML на внешние связи, формулы и выход за границы шаблона."""
    for _, node in iterparse(xml, events=('end',), forbid_dtd=True, forbid_entities=True, forbid_external=True):
        tag = node.tag.rsplit('}', 1)[-1]
        if node.get('TargetMode') == 'External':
            raise ValidationError('Удалите внешние связи из файла.')
        if worksheet and tag == 'f':
            raise ValidationError('Замените формулы в файле на значения.')
        if worksheet and tag in ('row', 'c'):
            coordinate = fullmatch(r'([A-E]?)([1-9]\d{0,2})', node.get('r', ''))
            if (
                coordinate is None or bool(coordinate[1]) != (tag == 'c')
                or int(coordinate[2]) > MAX_INVOICE_LINES + 1
            ):
                raise ValidationError(
                    f'Заполните только столбцы шаблона и не более {MAX_INVOICE_LINES} строк.',
                )
        node.clear()


def _inspect_archive(data):
    """Проверить структуру и размеры архива до чтения книги."""
    with ZipFile(BytesIO(data)) as archive:
        members = archive.infolist()
        names = {part.filename for part in members}
        if (
            len(members) > MAX_ARCHIVE_MEMBERS or len(names) != len(members)
            or sum(part.file_size for part in members) > MAX_EXPANDED_BYTES
            or not {'[Content_Types].xml', 'xl/workbook.xml'} <= names
        ):
            raise ValidationError('Структура файла XLSX не соответствует шаблону.')
        for part in members:
            filename = part.filename.casefold()
            location = PurePosixPath(part.filename)
            if (
                location.is_absolute() or '..' in location.parts or '\\' in part.filename or part.flag_bits & 1
                or filename.startswith(('xl/externallinks/', 'xl/embeddings/')) or filename.endswith('.bin')
            ):
                raise ValidationError('Файл должен содержать только данные накладной, без вложений и внешних связей.')
            if not filename.endswith(('.xml', '.rels')):
                continue
            worksheet = filename.startswith('xl/worksheets/') and '/_rels/' not in filename
            with archive.open(part) as xml:
                _inspect_xml(xml, worksheet=worksheet)


def _as_text(value):
    """Привести непустую ячейку к строке и убрать пробелы по краям."""
    return '' if value is None else str(value).strip()


def _names_by_key(model):
    """Собрать список ключей справочника по нормализованным названиям."""
    names = {}
    for pk, name in model.objects.values_list('pk', 'name').iterator():
        names.setdefault(name.strip().casefold(), []).append(pk)
    return names


def _resolve_name(mapping, value, description):
    """Найти единственную запись справочника по названию или сообщить об ошибке."""
    matches = mapping.get(value.casefold(), [])
    if len(matches) != 1:
        raise ValidationError(f'{description} «{value}» отсутствует в справочнике или найдено несколько совпадений.')
    return matches[0]


def _read_values(data):
    """Прочитать непустые строки одного видимого листа с ожидаемыми заголовками."""
    _inspect_archive(data)
    workbook = load_workbook(BytesIO(data), read_only=True, data_only=False, keep_links=False)
    try:
        if len(workbook.worksheets) != 1 or workbook.worksheets[0].sheet_state != 'visible':
            raise ValidationError('Используйте один видимый лист из шаблона.')
        sheet = workbook.worksheets[0]
        sheet.reset_dimensions()
        rows = iter(sheet.iter_rows(max_col=len(HEADERS), values_only=True))
        if next(rows, ()) != HEADERS:
            raise ValidationError('Заголовки столбцов должны совпадать с заголовками скачанного шаблона.')
        return [(number, values) for number, values in enumerate(rows, 2) if any(value is not None for value in values)]
    finally:
        workbook.close()


def read_invoice_workbook(upload):
    """Проверить загруженную книгу и преобразовать строки в данные формы накладной."""
    if not upload.name.lower().endswith('.xlsx') or upload.size > MAX_FILE_BYTES:
        raise ValidationError('Выберите файл XLSX размером до 2 МБ.')
    data = upload.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValidationError('Выберите файл XLSX размером до 2 МБ.')
    try:
        rows = _read_values(data)
    except (
        BadZipFile, DefusedXmlException, ParseError, InvalidFileException, ValueError, TypeError,
        KeyError, IndexError, AttributeError, OSError, EOFError, NotImplementedError, OverflowError,
    ) as error:
        raise ValidationError('Не удалось прочитать файл XLSX. Скачайте шаблон и сохраните новый файл.') from error

    parts = _names_by_key(Spares)
    measures = _names_by_key(MeasureMeasurement)
    codes = dict(Spares.objects.exclude(sku__isnull=True).values_list('sku', 'pk'))
    lines, errors = [], []
    for row, values in rows:
        sku, part, measure, quantity, price = map(_as_text, values)
        try:
            if sku:
                spare = codes.get(Spares.normalize_sku(sku))
                if spare is None:
                    raise ValidationError(f'Артикул «{sku}» отсутствует в справочнике.')
                if part and spare not in parts.get(part.casefold(), []):
                    raise ValidationError('Артикул и название относятся к разным запчастям.')
            else:
                spare = _resolve_name(parts, part, 'Запчасть') if part else None
            form = InvoiceLineForm({
                'spare': spare, 'measure': _resolve_name(measures, measure, 'Единица') if measure else '',
                'quantity': quantity.replace(',', '.'), 'price': price.replace(',', '.'),
            })
            if not form.is_valid():
                raise ValidationError([
                    f'{form.fields[field].label}: {message}' if field in form.fields else message
                    for field, messages in form.errors.items() for message in messages
                ])
            lines.append(form.cleaned_data)
        except ValidationError as error:
            errors.extend(f'Строка {row}. {message}' for message in error.messages)
    if errors:
        raise ValidationError(errors)
    validate_invoice_lines(lines)
    return lines


def make_invoice_workbook():
    """Подготовить пустой шаблон XLSX с заданными заголовками и форматом артикула."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Позиции'
    sheet.append(HEADERS)
    sheet.freeze_panes = 'A2'
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for column, width in zip('ABCDE', (22, 42, 20, 17, 17)):
        sheet.column_dimensions[column].width = width
    sheet.column_dimensions['A'].number_format = '@'
    data = BytesIO()
    workbook.save(data)
    workbook.close()
    return data.getvalue()

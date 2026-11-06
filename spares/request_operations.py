"""Преобразование заявок на складские документы в проведённые операции."""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import Model

from .forms import OperationReceiptForm, OperationWriteOffForm
from .invoice_forms import InvoiceHeaderForm, InvoiceLineForm
from .invoice_services import post_receipt_invoice
from .transfer_forms import TransferForm
from .transfer_models import post_transfer


def _serialize_value(value):
    """Преобразует модель, дату или точное число для хранения в JSON."""
    if isinstance(value, Model):
        return value.pk
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def serialize_form_data(data):
    """Сохраняет идентификаторы и введённые значения вместо объектов формы."""
    return {name: _serialize_value(value) for name, value in data.items()}


def assignment_snapshot(assignment):
    """Фиксирует выбранного работника и технику до согласования списания."""
    return {'worker': assignment.worker_id, 'machine': assignment.machine_id, 'trailer': assignment.trailer_id}


def _validate_form(form):
    """Проверяет актуальные справочники и ограничения перед записью."""
    if form.is_valid():
        return form
    errors = form.errors.get_json_data()
    raise ValidationError([
        f'{form.fields[field].label} — {item["message"]}' if field in form.fields else item['message']
        for field, items in errors.items() for item in items
    ])


def _journal_result(route, entry):
    """Возвращает адрес точной записи в журнале простых операций."""
    return {'route': route, 'pk': entry.pk, 'query': {'entry': entry.pk}}


def _apply_receipt(payload, actor):
    """Проверяет сохранённые реквизиты и проводит приход одной позиции."""
    receipt = _validate_form(OperationReceiptForm(payload)).save()
    return _journal_result('operations:receipts', receipt)


def _apply_invoice(payload, actor):
    """Повторно проверяет реквизиты и проводит все позиции накладной."""
    header = _validate_form(InvoiceHeaderForm(payload['header'])).cleaned_data
    lines = [_validate_form(InvoiceLineForm(line)).cleaned_data for line in payload['lines']]
    invoice = post_receipt_invoice(
        actor=actor, header=header, lines=lines, preview_version=payload.get('preview_version'),
    )
    return {'route': 'invoices:detail', 'pk': invoice.pk}


def _apply_writeoff(payload, actor):
    """Проверяет остаток и неизменность назначения перед списанием."""
    form = _validate_form(OperationWriteOffForm(payload))
    if assignment_snapshot(form.cleaned_data['machine_list']) != payload['assignment']:
        raise ValidationError('Назначение техники изменилось после подачи заявки. Оформите новую заявку.')
    return _journal_result('operations:writeoffs', form.save())


def _apply_transfer(payload, actor):
    """Повторно проверяет склады и количество перед проведением перемещения."""
    transfer = post_transfer(actor=actor, **_validate_form(TransferForm(payload)).cleaned_data)
    return {'route': 'transfers:detail', 'pk': transfer.pk}


OPERATIONS = {
    'receipt': _apply_receipt,
    'receipt_invoice': _apply_invoice,
    'writeoff': _apply_writeoff,
    'transfer': _apply_transfer,
}


def apply_request(kind, payload, actor):
    """Проводит одну заявку от имени согласовавшего сотрудника и возвращает ссылку."""
    operation = OPERATIONS.get(kind)
    if operation is None:
        raise ValidationError('Неизвестный вид складской заявки.')
    try:
        return operation(payload, actor)
    except (IntegrityError, KeyError, TypeError, ValueError) as error:
        raise ValidationError('Реквизиты заявки изменились или недоступны. Проверьте заявку и справочники.') from error

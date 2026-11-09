"""Проверка, проведение и отмена накладных поставщиков."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .database_lock import lock_warehouse_writes
from .invoice_models import ReceiptInvoice
from .models import Receipt


MAX_INVOICE_LINES = 100


def validate_invoice_number(company, contractor, number):
    """Вернуть ключ номера после проверки дубликатов среди действующих и старых документов."""
    number_key = ReceiptInvoice.normalize_number(number)
    if not number_key or len(number_key) > 255:
        raise ValidationError('Укажите номер накладной длиной до 255 символов.')

    scope = {'company': company, 'contractor': contractor, 'cancelled_at__isnull': True}
    legacy_numbers = Receipt.objects.filter(**scope, invoice__isnull=True).values_list('invoice_number', flat=True)
    if ReceiptInvoice.objects.filter(**scope, number_key=number_key).exists() or any(
        ReceiptInvoice.normalize_number(legacy) == number_key for legacy in legacy_numbers.iterator()
    ):
        raise ValidationError('Действующая накладная с таким номером у этого поставщика уже есть.')
    return number_key


def validate_invoice_lines(lines):
    """Проверить количество строк и запретить повтор сочетания запчасти, единицы и цены."""
    if not 1 <= len(lines) <= MAX_INVOICE_LINES:
        raise ValidationError(f'Добавьте от 1 до {MAX_INVOICE_LINES} строк.')
    seen = set()
    for line in lines:
        key = (line['spare'].pk, getattr(line['measure'], 'pk', None), line['price'])
        if key in seen:
            raise ValidationError('Объедините строки с одинаковыми запчастью, единицей измерения и ценой.')
        seen.add(key)


def invoice_version(header, number_key):
    """Вернуть номер последней записи накладной для проверки актуальности предпросмотра."""
    return ReceiptInvoice.objects.filter(
        company=header['company'], contractor=header['contractor'], number_key=number_key,
    ).order_by('-pk').values_list('pk', flat=True).first() or 0


@transaction.atomic
def post_receipt_invoice(*, actor, header, lines, preview_version=None):
    """Сохранить накладную со всеми приходами после проверок даты, строк, номера и версии."""
    lock_warehouse_writes()
    if header['date'] > timezone.localdate():
        raise ValidationError('Нельзя провести накладную будущей датой.')
    validate_invoice_lines(lines)
    number_key = validate_invoice_number(header['company'], header['contractor'], header['number'])
    if preview_version is not None and invoice_version(header, number_key) != preview_version:
        raise ValidationError('История этой накладной изменилась. Загрузите файл для нового предпросмотра.')
    invoice = ReceiptInvoice.objects.create(
        **header, number_key=number_key, posted_by=actor, posted_by_name=actor.get_username(),
    )
    for line in lines:
        Receipt.objects.create(
            invoice=invoice, invoice_number=invoice.number, date=invoice.date,
            company=invoice.company, contractor=invoice.contractor, warehouse=invoice.warehouse,
            **line,
        )
    return invoice


@transaction.atomic
def cancel_receipt_invoice(*, pk, actor, reason):
    """Отменить все приходы накладной и сохранить реквизиты отмены одной транзакцией."""
    lock_warehouse_writes()
    invoice = ReceiptInvoice.objects.select_for_update().get(pk=pk)
    if invoice.cancelled_at is not None:
        raise ValidationError('Накладная уже отменена.')
    reason = ReceiptInvoice._meta.get_field('cancellation_reason').clean(reason.strip(), invoice)
    if not reason:
        raise ValidationError('Укажите причину отмены.')

    for line in invoice.lines.order_by('pk'):
        line.cancel(actor=actor, reason=reason, allow_invoice=True)
    invoice.cancelled_at = timezone.now()
    invoice.cancelled_by_name = actor.get_username()
    invoice.cancellation_reason = reason
    invoice.save(update_fields=['cancelled_at', 'cancelled_by_name', 'cancellation_reason'])
    return invoice

"""Подача, проверка и проведение инвентаризационных ведомостей."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from .inventory_counts import record_inventory_count, update_inventory_summary
from .inventory_sheet_models import InventorySheet, InventorySheetLine
from .models import InventoryCount, Stock
from .stock_adjustments import record_manual_stock, stock_version
from .validators import load_operation_actor


MAX_SHEET_LINES = 100


def _lock_stocks(stock_ids):
    """Заблокировать остатки в порядке их номеров и вернуть их по ключам."""
    return {
        stock.pk: stock
        for stock in Stock.objects.select_for_update().filter(pk__in=stock_ids).order_by('pk')
    }


@transaction.atomic
def submit_inventory_sheet(*, warehouse, actor, entries, note='', expected_versions=None):
    """Сохранить ведомость со снимками и сразу провести её, если автор вправе проверять."""
    actor = load_operation_actor(actor, 'Для операции нужен действующий автор.')
    entries = list(entries)
    if not 1 <= len(entries) <= MAX_SHEET_LINES:
        raise ValidationError(f'Укажите от 1 до {MAX_SHEET_LINES} позиций.')
    stock_ids = [stock.pk for stock, _ in entries]
    if len(set(stock_ids)) != len(stock_ids):
        raise ValidationError('Каждый остаток можно указать только один раз.')
    stocks = _lock_stocks(stock_ids)
    if len(stocks) != len(stock_ids) or any(stock.warehouse_id != warehouse.pk for stock in stocks.values()):
        raise ValidationError('Все позиции ведомости должны относиться к выбранному складу.')
    if expected_versions is not None and any(
        expected_versions.get(str(pk)) != stock_version(stock) for pk, stock in stocks.items()
    ):
        raise ValidationError('Остатки изменились после открытия формы. Загрузите актуальные данные и повторите пересчёт.')
    note = InventorySheet._meta.get_field('note').clean((note or '').strip(), None)
    sheet = InventorySheet.objects.create(
        warehouse=warehouse, created_by=actor, created_by_name=actor.get_username(), note=note,
    )
    for stock, counted_quantity in entries:
        current = stocks[stock.pk]
        count = record_inventory_count(
            current, actor=actor, counted_quantity=counted_quantity, note=f'Пересчёт по ведомости № {sheet.pk}.',
            update_summary=False,
        )
        InventorySheetLine.objects.create(sheet=sheet, count=count, stock_revision=stock_version(current))
    if actor.has_perm('spares.approve_inventorysheet'):
        return _record_review(sheet, actor=actor, approve=True, note='Проведена при создании проверяющим.')
    return sheet


def _apply_sheet_counts(sheet, actor):
    """Проверить актуальность всех пересчётов до применения сводок и корректировок."""
    lines = list(sheet.lines.select_related('count').order_by('count__stock_id', 'pk'))
    if not lines:
        raise ValidationError('Ведомость не содержит позиций.')
    stocks = _lock_stocks([line.count.stock_id for line in lines])
    latest_counts = dict(
        InventoryCount.objects.filter(stock_id__in=stocks)
        .exclude(sheet_line__sheet__status=InventorySheet.Status.REJECTED)
        .order_by().values('stock_id').annotate(latest=Max('pk')).values_list('stock_id', 'latest')
    )
    for line in lines:
        count = line.count
        stock = stocks.get(count.stock_id)
        if (
            stock is None or latest_counts.get(count.stock_id) != count.pk
            or stock_version(stock) != line.stock_revision
        ):
            raise ValidationError(
                f'Данные позиции «{count.stock_label}» изменились после пересчёта. '
                'Отклоните ведомость и создайте новую.',
            )
    for line in lines:
        count = line.count
        stock = stocks[count.stock_id]
        update_inventory_summary(stock, count)
        if count.difference:
            stock.actual_balance = count.counted_quantity
            line.adjustment = record_manual_stock(stock, actor=actor, reason=f'По ведомости № {sheet.pk}.')
            line.save(update_fields=['adjustment'])


def _record_review(sheet, *, actor, approve, note):
    """Записать решение и, при подтверждении, провести пересчёты в текущей транзакции."""
    note = InventorySheet._meta.get_field('review_note').clean((note or '').strip(), None)
    if not approve and not note:
        raise ValidationError('Укажите причину отклонения.')

    if approve:
        _apply_sheet_counts(sheet, actor)

    sheet.status = InventorySheet.Status.APPROVED if approve else InventorySheet.Status.REJECTED
    sheet.reviewed_by = actor
    sheet.reviewed_by_name = actor.get_username()
    sheet.reviewed_at = timezone.now()
    sheet.review_note = note
    sheet.save(update_fields=['status', 'reviewed_by', 'reviewed_by_name', 'reviewed_at', 'review_note'])
    return sheet


@transaction.atomic
def review_inventory_sheet(sheet, *, actor, approve, note=''):
    """Заблокировать ожидающую ведомость и принять решение другого проверяющего."""
    actor = load_operation_actor(actor, 'Для операции нужен действующий автор.')
    if not actor.has_perm('spares.approve_inventorysheet'):
        raise ValidationError('У вас нет права проверять ведомости.')
    try:
        sheet = InventorySheet.objects.select_for_update().get(pk=sheet.pk)
    except InventorySheet.DoesNotExist as error:
        raise ValidationError('Ведомость отсутствует.') from error
    if sheet.status != InventorySheet.Status.PENDING:
        raise ValidationError('Ведомость уже проверена.')
    if sheet.created_by_id == actor.pk:
        raise ValidationError('Автор ведомости не может проверить её самостоятельно.')
    return _record_review(sheet, actor=actor, approve=approve, note=note)

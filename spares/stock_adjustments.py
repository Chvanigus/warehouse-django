"""Сохранение ручных изменений остатков с записью в журнале."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import router, transaction

from .database_lock import lock_warehouse_writes
from .models import Stock, StockAdjustment
from .validators import require_operation_actor


def stock_version(stock):
    """Собрать сериализуемый снимок остатка для проверки параллельных изменений."""
    return [
        stock.pk, str(stock.actual_balance), str(stock.input_quantity), str(stock.output_quantity),
        stock.plan, str(stock.inventory), str(stock.inventory_book_balance),
    ]


def stock_identity_label(stock):
    """Собрать подпись позиции, которая останется в истории после изменения справочников."""
    labels = [str(stock.spare), str(stock.warehouse), str(stock.company)]
    if stock.measure_id is not None:
        labels.append(str(stock.measure))
    labels.append(f"Цена {Stock.key_for(stock)['price']:.2f}")
    return ' · '.join(labels)


def save_manual_stock(stock, *, actor, reason):
    """Сохранить ручное изменение и вернуть запись остатка."""
    record_manual_stock(stock, actor=actor, reason=reason)
    return stock


def record_manual_stock(stock, *, actor, reason):
    """Сохранить остаток и вернуть запись журнала, если количество изменилось."""
    using = router.db_for_write(Stock, instance=stock)
    opening = stock._state.adding
    with transaction.atomic(using=using):
        lock_warehouse_writes(using)
        before = Decimal('0.00')
        if opening:
            stock.input_quantity = stock.output_quantity = 0
        else:
            try:
                previous = Stock.objects.using(using).select_for_update().get(pk=stock.pk)
            except Stock.DoesNotExist as error:
                raise ValidationError('Позиция удалена. Откройте список остатков заново.') from error
            before = previous.actual_balance
            stock.input_quantity = previous.input_quantity
            stock.output_quantity = previous.output_quantity

        after = Stock._meta.get_field('actual_balance').clean(stock.actual_balance, stock)
        stock.actual_balance = after
        if before != after:
            reason = (reason or '').strip()
            if not reason:
                raise ValidationError('Укажите причину изменения остатка.')
            reason = StockAdjustment._meta.get_field('reason').clean(reason, None)
            require_operation_actor(actor, 'Для корректировки остатка нужен автор.')

        stock.save(using=using, force_insert=opening)
        if before != after:
            return StockAdjustment.objects.using(using).create(
                stock=stock, stock_label=stock_identity_label(stock),
                actor=actor, actor_name=actor.get_username(),
                before=before, after=after, reason=reason,
            )
    return None

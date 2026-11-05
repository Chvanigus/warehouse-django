from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import router, transaction

from .models import Stock, StockAdjustment


def save_manual_stock(stock, *, actor, reason):
    """Сохранить ручной ввод остатка и историю изменения одной транзакцией."""
    using = router.db_for_write(Stock, instance=stock)
    opening = stock._state.adding
    with transaction.atomic(using=using):
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
            if not getattr(actor, 'is_authenticated', False) or actor.pk is None:
                raise ValidationError('Для корректировки остатка нужен автор.')

        stock.save(using=using, force_insert=opening)
        if before != after:
            labels = [str(stock.spare), str(stock.warehouse), str(stock.company)]
            if stock.measure_id is not None:
                labels.append(str(stock.measure))
            labels.append(f"Цена {Stock.key_for(stock)['price']:.2f}")
            StockAdjustment.objects.using(using).create(
                stock=stock, stock_label=' · '.join(labels),
                actor=actor, actor_name=actor.get_username(),
                before=before, after=after, reason=reason,
            )
    return stock

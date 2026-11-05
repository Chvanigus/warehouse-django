from django.core.exceptions import ValidationError
from django.db import router, transaction

from .models import InventoryCount, Stock
from .stock_adjustments import stock_identity_label


def update_inventory_summary(stock, entry, *, using=None):
    stock.inventory = entry.counted_quantity
    stock.inventory_book_balance = entry.book_quantity
    stock.save(using=using, update_fields={'inventory', 'inventory_book_balance'})


def record_inventory_count(stock, *, actor, counted_quantity, note='', update_summary=True):
    if not getattr(actor, 'is_authenticated', False) or actor.pk is None:
        raise ValidationError('Для записи пересчёта нужен автор.')
    quantity = InventoryCount._meta.get_field('counted_quantity').clean(counted_quantity, None)
    note = InventoryCount._meta.get_field('note').clean(note.strip(), None)
    using = router.db_for_write(Stock, instance=stock)
    with transaction.atomic(using=using):
        current = Stock.objects.using(using).select_for_update().get(pk=stock.pk)
        entry = InventoryCount.objects.using(using).create(
            stock=current, actor=actor, actor_name=actor.get_username(), stock_label=stock_identity_label(current),
            book_quantity=current.actual_balance, counted_quantity=quantity, note=note,
        )
        if update_summary:
            update_inventory_summary(current, entry, using=using)
        return entry

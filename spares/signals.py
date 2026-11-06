"""Обработчики удаления складских документов."""

from django.db.models.signals import pre_delete
from django.dispatch import receiver

from spares.models import Receipt, Stock, WriteOff


@receiver(pre_delete, sender=Receipt)
@receiver(pre_delete, sender=WriteOff)
def reverse_stock_operation(sender, instance, using, **kwargs):
    """Обратить проведённую операцию перед удалением по её последней сохранённой версии."""
    # Загруженный объект может устареть, если документ успел изменить другой пользователь.
    operation = instance._stored(using, lock=True)
    if operation is not None and operation.cancelled_at is None:
        Stock.adjust(operation, -operation.quantity, using, persist=True, missing_ok=True)
